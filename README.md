# lxmf-claude

An LXMF bot that bridges [Sideband](https://github.com/markqvist/Sideband) messages to an LLM. Supports [Claude](https://www.anthropic.com/) via the Anthropic API or any OpenAI-compatible API (e.g. [Ollama](https://ollama.com/)). Chat with an AI over the [Reticulum](https://reticulum.network/) mesh network, including LoRa.

## How it works

```
Sideband (Android)
    │
    │  LXMF over Reticulum
    │  (TCP, LoRa, AutoInterface, etc.)
    │
LXMF Bot (this project)
    │
    │  Anthropic API  ─or─  OpenAI-compatible API
    │
Claude (Haiku)         Ollama (local model)
```

The bot registers an LXMF delivery identity on your local Reticulum instance, listens for incoming messages, forwards them to the LLM, and sends the response back to the sender. It maintains per-sender conversation history so follow-up messages have context.

Backend is auto-detected: if `ANTHROPIC_API_KEY` is set (and the `anthropic` package is installed), it uses Claude. Otherwise it falls back to OpenAI/Ollama.

## Requirements

- Python 3.10+
- A running [Reticulum](https://reticulum.network/) shared instance (`rnsd`)
- One of:
  - An [Anthropic API key](https://console.anthropic.com/) (`pip install anthropic`)
  - [Ollama](https://ollama.com/) with a model pulled (`pip install openai`)

## Setup

```bash
git clone https://github.com/GlassOnTin/lxmf-claude.git
cd lxmf-claude
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Ensure `rnsd` is running and has network connectivity to your Reticulum mesh.

## Usage

```bash
source .venv/bin/activate

# For Claude:
export ANTHROPIC_API_KEY="sk-ant-..."
python3 claude_bot.py

# For Ollama (no API key needed):
python3 claude_bot.py
```

The bot prints its LXMF address on startup:

```
============================================================
  LXMF AI Bot
============================================================
  LXMF address: <your unique address>
  ...
============================================================
```

In Sideband, start a new conversation with that address. Messages you send will be answered by the LLM.

The identity is persisted at `~/.lxmf-claude/identity` so the address stays the same across restarts.

## Configuration

Edit the constants at the top of `claude_bot.py`:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Model used with Anthropic backend |
| `OLLAMA_MODEL` | `glm-5:cloud` | Model used with OpenAI/Ollama backend |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama API endpoint |
| `MAX_HISTORY` | `10` | Message pairs retained per sender |
| `MAX_RESPONSE_CHARS` | `1500` | Hard truncation limit for responses |
| `DISPLAY_NAME` | `AI Bot` | Name shown in Sideband announces |
| `SYSTEM_PROMPT` | *(concise assistant)* | Instructions for the LLM |

## Network topology

The bot connects to your local shared Reticulum instance (via unix socket). Configure your `~/.reticulum/config` with whatever interfaces you need — AutoInterface for LAN, TCPClientInterface for remote routers, RNodeInterface for LoRa, etc. The bot itself doesn't need to know about the transport layer.

## License

MIT
