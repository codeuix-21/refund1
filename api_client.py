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


def ensure_ollama_daemon(base_url=OLLAMA_BASE_URL, timeout=3):
    """
    Check if Ollama is running; if not, attempt to start it in the background if installed.
    Returns True if Ollama is reachable, False otherwise.
    """
    if is_ollama_available(base_url, timeout=1):
        return True

    import os
    import shutil
    import subprocess
    import time
    from pathlib import Path

    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidate = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.exists():
            ollama_bin = str(candidate)

    if ollama_bin:
        try:
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
            for _ in range(8):
                time.sleep(0.5)
                if is_ollama_available(base_url, timeout=1):
                    return True
        except Exception:
            pass

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
