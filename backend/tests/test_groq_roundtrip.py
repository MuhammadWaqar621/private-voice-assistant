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

from app.company_profile import build_system_prompt
from app.groq_client import chat_reply, synthesize_speech, transcribe_audio
from tests.conftest import requires_groq

_JAZZ_DETAILS = """Jazz is a mobile network operator offering prepaid and postpaid SIMs.
Balance check: dial *111# for prepaid balance and remaining bundle data."""

_BANK_DETAILS = """Alliance Bank offers savings/current accounts, debit and credit cards,
and personal/auto/home loans."""

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


def test_company_grounded_reply_declines_real_account_data():
    system_prompt = build_system_prompt("Alliance Bank", _BANK_DETAILS)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "What is the exact balance in my account right now?"},
    ]
    reply = chat_reply(messages)
    assert reply.strip()
    # The system prompt instructs it to never invent real account data -
    # the reply should redirect rather than state a fabricated number.
    lowered = reply.lower()
    assert not any(f"${n}" in lowered for n in range(10))


def test_company_uses_grounded_fact_from_arbitrary_details():
    # Uses details for a company not in EXAMPLE_TEMPLATES to prove this
    # isn't special-cased to a couple of hardcoded businesses - any
    # company name/details a user provides should ground the reply.
    system_prompt = build_system_prompt(
        "Zylo Airlines", "Zylo's baggage allowance is 20kg for economy passengers."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "What's the baggage allowance for economy?"},
    ]
    reply = chat_reply(messages)
    assert "20" in reply  # the grounded fact from the supplied details


def test_company_replies_in_urdu_when_asked_in_urdu():
    # Mirrors the exact prompt shape app/api/voice.py builds from
    # Whisper's detected language (there's no real Urdu audio fixture to
    # drive this through STT, so it's applied directly here) - verifies
    # the LLM itself actually follows a non-English instruction rather
    # than defaulting to English regardless of what's asked. Run several
    # times: a small/fast model doesn't comply with 100% consistency, so
    # this only fails if it drifts back to English on every attempt.
    system_prompt = build_system_prompt("Jazz", _JAZZ_DETAILS)
    attempts = 3
    for attempt in range(attempts):
        messages = [
            {"role": "system", "content": system_prompt},
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
