import io
import json
import pytest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

from agent.llm_client import chat

def _mock_http_response(body_dict: dict, status_code: int = 200):
    body_bytes = json.dumps(body_dict).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body_bytes
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp

def test_chat_success():
    fake_payload = {
        "message": {
            "role": "assistant",
            "content": "Return is ready for pickup."
        }
    }
    with patch("agent.llm_client.urlopen", return_value=_mock_http_response(fake_payload)):
        reply = chat("Assess return RET-1")
    assert reply == "Return is ready for pickup."

def test_chat_http_error():
    err_body = io.BytesIO(b'{"error": "model not found"}')
    http_err = HTTPError(url="http://localhost:11434/api/chat", code=404, msg="Not Found", hdrs={}, fp=err_body)
    with patch("agent.llm_client.urlopen", side_effect=http_err):
        with pytest.raises(RuntimeError, match="Ollama returned HTTP 404"):
            chat("Hello")

def test_chat_connection_error():
    url_err = URLError(reason="Connection refused")
    with patch("agent.llm_client.urlopen", side_effect=url_err):
        with pytest.raises(RuntimeError, match="Could not connect to Ollama"):
            chat("Hello")

def test_chat_malformed_json():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"invalid-non-json"
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    with patch("agent.llm_client.urlopen", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="Ollama returned an unexpected response"):
            chat("Hello")

def test_chat_missing_message_structure():
    fake_payload = {"wrong_key": 123}
    with patch("agent.llm_client.urlopen", return_value=_mock_http_response(fake_payload)):
        with pytest.raises(RuntimeError, match="Ollama returned an unexpected response"):
            chat("Hello")

@pytest.mark.parametrize("bad_input", [
    "",
    "   ",
    "\n\t",
    None,
    123,
    [],
    {},
])
def test_chat_invalid_input(bad_input):
    with pytest.raises(ValueError, match="Message must be a non-empty string"):
        chat(bad_input)
