"""
End-to-end tests against the real Groq API: TTS -> STT round trip and
persona-grounded LLM replies. These cost a tiny amount of real API usage
and require network + GROQ_API_KEY, so they're marked `integration` and
skipped automatically when the key isn't set (see tests/conftest.py).

TTS specifically depends on Groq's Orpheus model, which requires a
one-time terms acceptance in the Groq console (see backend/.env.example).
Until that's done, Groq raises model_terms_required - the TTS tests below
detect that specific error and skip with a clear message rather than
failing, since it's a manual step outside this codebase.
"""

from pathlib import Path

import pytest
from openai import BadRequestError

from app.groq_client import chat_reply, synthesize_speech, transcribe_audio
from app.personas import get_persona
from tests.conftest import requires_groq

pytestmark = [pytest.mark.integration, requires_groq]

FIXTURES = Path(__file__).parent / "fixtures"


def _synthesize_or_skip(text: str) -> bytes:
    try:
        return synthesize_speech(text)
    except BadRequestError as exc:
        body = getattr(exc, "body", None) or {}
        code = body.get("code") if isinstance(body, dict) else None
        if code in ("model_terms_required", "model_decommissioned"):
            pytest.skip(
                "Groq TTS model needs one-time terms acceptance - see "
                "backend/.env.example (GROQ_TTS_MODEL). "
                f"Groq said: {exc}"
            )
        raise


def test_tts_produces_audio_bytes():
    audio = _synthesize_or_skip("This is a test of the voice assistant.")
    assert isinstance(audio, bytes)
    assert len(audio) > 1000  # a real audio clip, not an empty/error response


def test_tts_then_stt_recovers_recognizable_text():
    spoken_text = "The quick brown fox jumps over the lazy dog."
    audio = _synthesize_or_skip(spoken_text)
    transcript = transcribe_audio(audio, "roundtrip.mp3")
    # Whisper won't be byte-perfect, but core words should survive the
    # synthesize -> recognize round trip.
    lowered = transcript.lower()
    assert "fox" in lowered
    assert "dog" in lowered


def test_stt_transcribes_prerecorded_fixture():
    # Uses a pre-recorded fixture (not Groq TTS output) so this passes
    # regardless of whether Groq's TTS model has had its terms accepted.
    audio = (FIXTURES / "balance_question.wav").read_bytes()
    transcript = transcribe_audio(audio, "balance_question.wav")
    assert "balance" in transcript.lower()


def test_persona_grounded_reply_declines_real_account_data():
    persona = get_persona("bank")
    messages = [
        {"role": "system", "content": persona.system_prompt},
        {"role": "user", "content": "What is the exact balance in my account right now?"},
    ]
    reply = chat_reply(messages)
    assert reply.strip()
    # The persona is instructed never to invent real account data - the
    # reply should redirect rather than state a fabricated number.
    lowered = reply.lower()
    assert not any(f"${n}" in lowered for n in range(10))


def test_persona_uses_grounded_fact():
    persona = get_persona("jazz")
    messages = [
        {"role": "system", "content": persona.system_prompt},
        {"role": "user", "content": "How do I check my prepaid balance?"},
    ]
    reply = chat_reply(messages)
    assert "111" in reply  # the *111# short code from the persona's knowledge
