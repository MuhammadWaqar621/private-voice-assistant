"""
Full-stack integration test for POST /api/voice/turn: a real spoken clip
goes in, and a transcript + grounded reply must come out. The clips are
pre-recorded fixtures (tests/fixtures/*.wav, via Windows' built-in speech
synthesizer - see that directory) rather than Groq-synthesized, so this
suite exercises real STT + LLM regardless of whether Groq's TTS model has
had its terms accepted yet (see test_groq_roundtrip.py). Skips if
GROQ_API_KEY isn't set.
"""

import json
from pathlib import Path

import pytest

from tests.conftest import requires_groq

pytestmark = [pytest.mark.integration, requires_groq]

FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_turn_endpoint_full_pipeline(client):
    clip = _read_fixture("balance_question.wav")

    resp = client.post(
        "/api/voice/turn",
        data={"persona": "jazz", "history": "[]"},
        files={"audio": ("clip.wav", clip, "audio/wav")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "balance" in body["user_text"].lower()
    assert body["reply_text"].strip()
    assert isinstance(body["reply_audio_base64"], str)


def test_turn_endpoint_carries_history_context(client):
    first = client.post(
        "/api/voice/turn",
        data={"persona": "bank", "history": "[]"},
        files={"audio": ("clip1.wav", _read_fixture("name_statement.wav"), "audio/wav")},
    )
    assert first.status_code == 200
    first_body = first.json()

    history = json.dumps(
        [
            {"role": "user", "content": first_body["user_text"]},
            {"role": "assistant", "content": first_body["reply_text"]},
        ]
    )

    second = client.post(
        "/api/voice/turn",
        data={"persona": "bank", "history": history},
        files={"audio": ("clip2.wav", _read_fixture("name_question.wav"), "audio/wav")},
    )
    assert second.status_code == 200
    assert "ali" in second.json()["reply_text"].lower()
