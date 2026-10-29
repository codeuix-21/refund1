import pytest
from understanding import solve_arithmetic, fast_intent_classify, INTENT_CHAT
from conversation import ConversationSession


def test_solve_arithmetic_basic():
    assert solve_arithmetic("2+2") == "2+2 = 4"
    assert solve_arithmetic("what is 2+2") == "2+2 = 4"
    assert solve_arithmetic("what is 2 + 2?") == "2 + 2 = 4"
    assert solve_arithmetic("solve that: 2 + 2") == "2 + 2 = 4"
    assert solve_arithmetic("what is 2+2 and solve that") == "2+2 = 4"


def test_solve_arithmetic_operations():
    assert solve_arithmetic("what is 15 plus 25") == "15 + 25 = 40"
    assert solve_arithmetic("what is 50 minus 18") == "50 - 18 = 32"
    assert solve_arithmetic("can you calculate 7 * 8?") == "7 * 8 = 56"
    assert solve_arithmetic("100 / 4") == "100 / 4 = 25"
    assert solve_arithmetic("solve (10 + 5) * 2") == "(10 + 5) * 2 = 30"


def test_solve_arithmetic_non_math():
    assert solve_arithmetic("hello there") is None
    assert solve_arithmetic("I want to return ORD-124") is None
    assert solve_arithmetic("what is your return policy") is None


def test_fast_intent_classify_math():
    assert fast_intent_classify("what is 2+2") == INTENT_CHAT
    assert fast_intent_classify("solve that: 2 + 2") == INTENT_CHAT


def test_conversation_answers_math_offline(monkeypatch):
    monkeypatch.setattr("conversation.is_ollama_available", lambda: False)
    session = ConversationSession([])
    reply = session.handle_turn("what is 2+2 and solve that")
    assert "4" in reply
    assert "2+2 = 4" in reply
