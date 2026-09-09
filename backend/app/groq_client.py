"""
Thin wrapper around the Groq API for speech-to-text (Whisper), text-to-speech
(PlayAI TTS), and chat completions (Llama / GPT-OSS via Groq's
OpenAI-compatible endpoint). One API key covers all three, so the whole
voice pipeline - listen, think, speak - runs through this one module.

Groq exposes an OpenAI-compatible API, so the `openai` package is reused
here too, just pointed at Groq's base URL - no separate SDK is needed.

Env vars:
  - GROQ_API_KEY: required for anything in this module to work.
  - GROQ_STT_MODEL: Whisper model for transcribe_audio().
  - GROQ_TTS_MODEL / GROQ_TTS_VOICE: model/voice for synthesize_speech().
  - GROQ_LLM_MODEL: chat-completion model for chat_reply().
"""

import os
from functools import lru_cache
from typing import Optional

from openai import OpenAI

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

DEFAULT_STT_MODEL = "whisper-large-v3"
DEFAULT_TTS_MODEL = "canopylabs/orpheus-v1-english"
DEFAULT_TTS_VOICE = "troy"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"

# Hard cap on how much text synthesize_speech() will send to Groq per call -
# bounds cost/latency on a very long assistant reply. Callers may pass
# longer text; it is simply truncated here rather than rejected.
_TTS_MAX_CHARS = 2000


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _api_key() -> Optional[str]:
    return _clean(os.getenv("GROQ_API_KEY"))


def groq_configured() -> bool:
    """True iff GROQ_API_KEY is set to a non-empty value."""
    return _api_key() is not None


@lru_cache
def get_groq_client() -> OpenAI:
    api_key = _api_key()
    if api_key is None:
        raise RuntimeError("Groq is not configured (GROQ_API_KEY env var).")
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Speech-to-text via Groq's Whisper endpoint. Raises on any API
    failure - callers translate that into a clear HTTP error."""
    client = get_groq_client()
    model = _clean(os.getenv("GROQ_STT_MODEL")) or DEFAULT_STT_MODEL
    response = client.audio.transcriptions.create(model=model, file=(filename, audio_bytes))
    return response.text


def synthesize_speech(text: str) -> bytes:
    """Text-to-speech via Groq's PlayAI TTS endpoint, returning raw MP3
    bytes. `text` is capped at _TTS_MAX_CHARS characters before being
    sent, to bound cost/latency on a very long assistant reply."""
    client = get_groq_client()
    model = _clean(os.getenv("GROQ_TTS_MODEL")) or DEFAULT_TTS_MODEL
    voice = _clean(os.getenv("GROQ_TTS_VOICE")) or DEFAULT_TTS_VOICE
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text[:_TTS_MAX_CHARS],
        response_format="mp3",
    )
    return response.read()


def chat_reply(messages: list[dict]) -> str:
    """One chat-completion turn via Groq's Llama/GPT-OSS models.
    `messages` is the standard OpenAI chat list ([{role, content}, ...]),
    system prompt included by the caller (see app/personas.py)."""
    client = get_groq_client()
    model = _clean(os.getenv("GROQ_LLM_MODEL")) or DEFAULT_LLM_MODEL
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        max_tokens=300,
    )
    return response.choices[0].message.content or ""
