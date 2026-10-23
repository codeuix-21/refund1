import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5:7b"


def chat(message: str) -> str:
    """
    Send a message to the local Ollama model and return its response.
    """

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must be a non-empty string.")

    payload = {
        "model": MODEL_NAME,
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