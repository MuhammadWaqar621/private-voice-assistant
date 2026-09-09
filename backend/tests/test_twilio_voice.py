"""
Tests for the Twilio webhook endpoints (app/api/twilio_voice.py). Twilio
itself is just an HTTP client hitting these routes with form-encoded POST
requests and reading back TwiML - so these tests simulate exactly that
shape without needing a real Twilio account, phone number, or call. What
they can't verify is the parts that only exist on Twilio's side (does a
real call actually reach /voice, does Twilio's speech recognition produce
a good SpeechResult) - that needs a real account, per the README.
"""

import re

import pytest

from app.conversation_store import get_history
from tests.conftest import requires_groq

pytestmark = [pytest.mark.integration, requires_groq]


@pytest.fixture(autouse=True)
def public_base_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.ngrok-free.app")
    monkeypatch.setenv("TWILIO_DEFAULT_PERSONA", "jazz")


def test_incoming_call_returns_gather_twiml(client):
    resp = client.post("/api/twilio/voice")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text
    assert "<Gather" in body
    assert 'action="/api/twilio/gather"' in body
    # Either a <Play> of Groq-synthesized audio or a <Say> fallback - both
    # are valid depending on whether Groq TTS is available right now.
    assert "<Play>" in body or "<Say>" in body


def test_gather_with_speech_advances_conversation(client):
    call_sid = "CAtest0000000000000000000000001"
    resp = client.post(
        "/api/twilio/gather",
        data={"CallSid": call_sid, "SpeechResult": "How do I check my prepaid balance?"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert "<Gather" in body  # keeps listening for the next turn

    history = get_history(call_sid)
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "How do I check my prepaid balance?"}
    assert history[1]["role"] == "assistant"
    assert history[1]["content"].strip()


def test_gather_with_empty_speech_reprompts_without_calling_llm(client):
    resp = client.post(
        "/api/twilio/gather",
        data={"CallSid": "CAtest0000000000000000000000002", "SpeechResult": ""},
    )
    assert resp.status_code == 200
    assert "didn't catch that" in resp.text.lower()
    assert "<Gather" in resp.text


def test_played_audio_url_is_actually_fetchable(client):
    resp = client.post(
        "/api/twilio/gather",
        data={"CallSid": "CAtest0000000000000000000000003", "SpeechResult": "Hello"},
    )
    match = re.search(r"<Play>(.*?)</Play>", resp.text)
    if match is None:
        pytest.skip("Groq TTS produced no audio this run (see test_groq_roundtrip's skip conditions)")
    audio_url = match.group(1)
    assert audio_url.startswith("https://example.ngrok-free.app/api/twilio/audio/")

    audio_path = audio_url.removeprefix("https://example.ngrok-free.app")
    audio_resp = client.get(audio_path)
    assert audio_resp.status_code == 200
    assert audio_resp.headers["content-type"] == "audio/wav"
    assert len(audio_resp.content) > 1000


def test_status_callback_clears_history_on_call_end(client):
    call_sid = "CAtest0000000000000000000000004"
    client.post("/api/twilio/gather", data={"CallSid": call_sid, "SpeechResult": "Hi"})
    assert len(get_history(call_sid)) == 2

    resp = client.post("/api/twilio/status", data={"CallSid": call_sid, "CallStatus": "completed"})
    assert resp.status_code == 204
    assert get_history(call_sid) == []


def test_audio_endpoint_404s_for_unknown_id(client):
    resp = client.get("/api/twilio/audio/does-not-exist.wav")
    assert resp.status_code == 404
