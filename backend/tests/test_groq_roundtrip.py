"""
End-to-end tests against the real Groq API: TTS -> STT round trip and
persona-grounded LLM replies. These cost a tiny amount of real API usage
and require network + GROQ_API_KEY, so they're marked `integration` and
skipped automatically when the key isn't set (see tests/conftest.py).

TTS specifically depends on Groq's Orpheus model, which requires a
one-time terms acceptance in the Groq console (see backend/.env.example)
and has a modest free-tier daily token quota. Either condition surfaces
as an OpenAI SDK error with a distinct `code` - the TTS tests below detect
those specific codes and skip with a clear message rather than failing,
since neither is a bug in this codebase (one's a manual one-time step,
the other resets the next day / with a paid tier).
"""

from pathlib import Path

import pytest
from openai import APIStatusError

from app.groq_client import chat_reply, synthesize_speech, transcribe_audio
from app.personas import get_persona
from tests.conftest import requires_groq

pytestmark = [pytest.mark.integration, requires_groq]

FIXTURES = Path(__file__).parent / "fixtures"

_SKIPPABLE_TTS_ERROR_CODES = {
    "model_terms_required",  # one-time terms acceptance not done yet - see backend/.env.example
    "model_decommissioned",  # Groq retired the configured GROQ_TTS_MODEL
    "rate_limit_exceeded",  # free-tier daily token quota hit - resets daily / with a paid tier
}


def _synthesize_or_skip(text: str) -> bytes:
    try:
        return synthesize_speech(text)
    except APIStatusError as exc:
        body = getattr(exc, "body", None) or {}
        code = body.get("code") if isinstance(body, dict) else None
        if code in _SKIPPABLE_TTS_ERROR_CODES:
            pytest.skip(f"Groq TTS unavailable right now ({code}), not a code bug. Groq said: {exc}")
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
    lowered = transcript.text.lower()
    assert "fox" in lowered
    assert "dog" in lowered
    assert transcript.language.lower() == "english"


def test_stt_transcribes_prerecorded_fixture():
    # Uses a pre-recorded fixture (not Groq TTS output) so this passes
    # regardless of whether Groq's TTS model has had its terms accepted.
    audio = (FIXTURES / "balance_question.wav").read_bytes()
    transcript = transcribe_audio(audio, "balance_question.wav")
    assert "balance" in transcript.text.lower()
    assert transcript.language.lower() == "english"


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


def test_persona_replies_in_urdu_when_asked_in_urdu():
    # Mirrors the exact prompt shape app/api/voice.py builds from
    # Whisper's detected language (there's no real Urdu audio fixture to
    # drive this through STT, so it's applied directly here) - verifies
    # the LLM itself actually follows a non-English instruction rather
    # than defaulting to English regardless of what's asked. Run several
    # times: a small/fast model doesn't comply with 100% consistency, so
    # this only fails if it drifts back to English on every attempt.
    persona = get_persona("jazz")
    attempts = 3
    for attempt in range(attempts):
        messages = [
            {"role": "system", "content": persona.system_prompt},
            {"role": "user", "content": "[Reply only in Urdu.] Main apna balance kaise check karoon?"},
        ]
        reply = chat_reply(messages)
        assert reply.strip()
        # Urdu is written in Arabic-script characters (U+0600-U+06FF) - a
        # reply using that range confirms it actually replied in Urdu
        # script, not transliterated/English text.
        if any("؀" <= ch <= "ۿ" for ch in reply):
            return
    raise AssertionError(f"expected Urdu script in at least one of {attempts} attempts, last reply: {reply!r}")
