#!/usr/bin/env python3
"""LXMF AI Bot — bridges LXMF messages to a local LLM via Ollama."""

import os
import sys
import signal
import time
import threading
from pathlib import Path

import RNS
import LXMF
from openai import OpenAI

DATA_DIR = Path.home() / ".lxmf-claude"
IDENTITY_PATH = DATA_DIR / "identity"
STORAGE_PATH = DATA_DIR / "storage"

MAX_HISTORY = 10        # message pairs per sender
MAX_RESPONSE_CHARS = 1500
OLLAMA_BASE_URL = "http://localhost:11434/v1"
MODEL = "glm-5:cloud"
DISPLAY_NAME = "AI Bot"

SYSTEM_PROMPT = (
    "You are a helpful assistant reachable over a low-bandwidth LoRa mesh network (Reticulum/LXMF). "
    "Keep responses under 500 characters. Be concise and direct. "
    "If a topic needs a longer answer, give a brief summary and offer to elaborate."
)

# Conversation history per sender, keyed by sender hash (hex)
conversations: dict[str, list[dict]] = {}
conversations_lock = threading.Lock()

llm_client: OpenAI = None
lxm_router: LXMF.LXMRouter = None
delivery_destination: RNS.Destination = None
shutdown_event = threading.Event()


def get_or_create_identity() -> RNS.Identity:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)

    if IDENTITY_PATH.exists():
        identity = RNS.Identity.from_file(str(IDENTITY_PATH))
        RNS.log(f"Loaded existing identity from {IDENTITY_PATH}", RNS.LOG_INFO)
    else:
        identity = RNS.Identity()
        identity.to_file(str(IDENTITY_PATH))
        RNS.log(f"Created new identity, saved to {IDENTITY_PATH}", RNS.LOG_INFO)

    return identity


def get_llm_response(sender_hash: str, user_message: str) -> str:
    with conversations_lock:
        if sender_hash not in conversations:
            conversations[sender_hash] = []
        history = conversations[sender_hash]

    history.append({"role": "user", "content": user_message})

    if len(history) > MAX_HISTORY * 2:
        history[:] = history[-(MAX_HISTORY * 2):]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        response = llm_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1024,
        )
        assistant_text = response.choices[0].message.content

        if len(assistant_text) > MAX_RESPONSE_CHARS:
            assistant_text = assistant_text[:MAX_RESPONSE_CHARS - 3] + "..."

        history.append({"role": "assistant", "content": assistant_text})
        return assistant_text

    except Exception as e:
        history.pop()
        error_msg = f"Error calling LLM: {type(e).__name__}: {e}"
        RNS.log(error_msg, RNS.LOG_ERROR)
        return f"[Bot error: {type(e).__name__}. Try again later.]"


def send_response(destination_hash: bytes, response_text: str):
    dest_identity = RNS.Identity.recall(destination_hash)
    if dest_identity is None:
        RNS.log("Cannot recall identity for sender, requesting path...", RNS.LOG_WARNING)
        RNS.Transport.request_path(destination_hash)
        time.sleep(5)
        dest_identity = RNS.Identity.recall(destination_hash)
        if dest_identity is None:
            RNS.log("Still cannot recall sender identity, dropping response", RNS.LOG_ERROR)
            return

    lxmf_dest = RNS.Destination(
        dest_identity,
        RNS.Destination.OUT,
        RNS.Destination.SINGLE,
        "lxmf",
        "delivery",
    )

    lxm = LXMF.LXMessage(
        lxmf_dest,
        delivery_destination,
        response_text,
        desired_method=LXMF.LXMessage.DIRECT,
    )
    lxm.try_propagation_on_fail = True

    def outbound_delivery_callback(message):
        if message.state == LXMF.LXMessage.DELIVERED:
            RNS.log(f"Response delivered to {RNS.prettyhexrep(destination_hash)}", RNS.LOG_INFO)
        elif message.state == LXMF.LXMessage.FAILED:
            RNS.log(f"Response delivery FAILED to {RNS.prettyhexrep(destination_hash)}", RNS.LOG_WARNING)

    lxm.delivery_callback = outbound_delivery_callback
    lxm_router.handle_outbound(lxm)
    RNS.log(f"Queued response to {RNS.prettyhexrep(destination_hash)}", RNS.LOG_INFO)


def message_received(message: LXMF.LXMessage):
    sender_hash = message.source_hash
    sender_hex = RNS.hexrep(sender_hash, delimit=False)
    content = message.content_as_string()

    RNS.log(f"Message from {RNS.prettyhexrep(sender_hash)}: {content}", RNS.LOG_INFO)

    def handle():
        response = get_llm_response(sender_hex, content)
        RNS.log(f"LLM response ({len(response)} chars): {response[:100]}...", RNS.LOG_INFO)
        send_response(sender_hash, response)

    threading.Thread(target=handle, daemon=True).start()


def shutdown_handler(signum, frame):
    RNS.log("Shutting down...", RNS.LOG_INFO)
    shutdown_event.set()


def main():
    global llm_client, lxm_router, delivery_destination

    llm_client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    reticulum = RNS.Reticulum()
    identity = get_or_create_identity()

    lxm_router = LXMF.LXMRouter(identity=identity, storagepath=str(STORAGE_PATH))
    lxm_router.register_delivery_callback(message_received)
    delivery_destination = lxm_router.register_delivery_identity(
        identity, display_name=DISPLAY_NAME
    )

    RNS.Identity.remember(
        packet_hash=None,
        destination_hash=delivery_destination.hash,
        public_key=identity.get_public_key(),
        app_data=None,
    )

    bot_hash = RNS.hexrep(delivery_destination.hash, delimit=False)

    print()
    print("=" * 60)
    print("  LXMF AI Bot")
    print("=" * 60)
    print(f"  LXMF address: {bot_hash}")
    print(f"  Identity:     {IDENTITY_PATH}")
    print(f"  Model:        {MODEL}")
    print(f"  Ollama:       {OLLAMA_BASE_URL}")
    print()
    print("  Add this address in Sideband to start chatting.")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    lxm_router.announce(delivery_destination.hash)
    RNS.log("Announced LXMF delivery destination", RNS.LOG_INFO)

    while not shutdown_event.is_set():
        shutdown_event.wait(timeout=1)

    RNS.log("Bot stopped.", RNS.LOG_INFO)


if __name__ == "__main__":
    main()
