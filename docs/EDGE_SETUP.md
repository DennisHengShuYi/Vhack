# Edge LLM Setup (Offline Mode)

Run the SENTINEL agent locally without any cloud API keys using Ollama.

## Install Ollama

Download from https://ollama.com/download and install for your OS.

## Pull the model

```bash
ollama pull llama3.1:8b
```

Verify it's running:
```bash
ollama list
```

## Configure environment

Add to your `.env` at the project root:

```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
ACTIVE_PROVIDER=OLLAMA
```

Or leave `ACTIVE_PROVIDER` unset to use AUTO mode (prefers cloud, falls back to edge).

## Start the agent

Start the backend and agent as normal. The BRAIN pill in the header shows `EDGE` when Ollama is active.

## Switching modes at runtime

Click the **BRAIN** pill in the header and select `EDGE` to force Ollama, or `AUTO` to let the system self-heal.
