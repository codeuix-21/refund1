"""
Client for interacting with the local Ollama LLM service.
Provides robust chat completions, health checks, and fallback mechanisms.
"""

import json
import requests

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"
REQUEST_TIMEOUT = 120


def is_ollama_available(base_url=OLLAMA_BASE_URL, timeout=3):
    """Check if the local Ollama daemon is reachable and responding."""
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False


def chat_completion(
    messages,
    model=DEFAULT_MODEL,
    base_url=OLLAMA_BASE_URL,
    format=None,
    temperature=0.4,
    timeout=REQUEST_TIMEOUT
):
    """
    Send a multi-turn chat request to Ollama.
    Returns the assistant's string reply, or raises requests.RequestException on failure.
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }

    if format == "json":
        payload["format"] = "json"

    endpoint = f"{base_url}/api/chat"
    response = requests.post(endpoint, json=payload, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    message = data.get("message", {})
    return message.get("content", "").strip()


def chat_json(
    messages,
    model=DEFAULT_MODEL,
    base_url=OLLAMA_BASE_URL,
    temperature=0.1,
    timeout=REQUEST_TIMEOUT
):
    """
    Send a chat request expecting a JSON response.
    Parses and returns the dictionary, or None if parsing fails.
    """
    raw_reply = chat_completion(
        messages,
        model=model,
        base_url=base_url,
        format="json",
        temperature=temperature,
        timeout=timeout
    )
    try:
        return json.loads(raw_reply)
    except (json.JSONDecodeError, TypeError):
        return None
