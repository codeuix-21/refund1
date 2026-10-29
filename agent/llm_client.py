import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
MODEL_NAME = DEFAULT_MODEL


def get_available_model(base_url="http://localhost:11434", preferred="qwen2.5:3b") -> str:
    """Detect available model in Ollama; fallback gracefully."""
    try:
        req = Request(f"{base_url}/api/tags", method="GET")
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            if preferred in models:
                return preferred
            for m in models:
                if "qwen" in m:
                    return m
            if models:
                return models[0]
    except Exception:
        pass
    return preferred


def chat(message: str) -> str:
    """
    Send a message to the local Ollama model and return its response.
    """

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must be a non-empty string.")

    target_model = MODEL_NAME
    payload = {
        "model": target_model,
        "messages": [
            {
                "role": "user",
                "content": message
            }
        ],
        "stream": False
    }

    request = Request(
        url=OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

        return result["message"]["content"]

    except HTTPError as error:
        raise RuntimeError(
            f"Ollama returned HTTP {error.code}: "
            f"{error.read().decode('utf-8', errors='replace')}"
        ) from error

    except URLError as error:
        raise RuntimeError(
            "Could not connect to Ollama. Check that Ollama is running."
        ) from error

    except (KeyError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "Ollama returned an unexpected response."
        ) from error
