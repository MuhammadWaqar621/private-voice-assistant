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
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from openai import OpenAI, RateLimitError

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

DEFAULT_STT_MODEL = "whisper-large-v3-turbo"  # turbo trades a little accuracy for much lower latency
DEFAULT_TTS_MODEL = "canopylabs/orpheus-v1-english"
DEFAULT_TTS_VOICE = "troy"
DEFAULT_LLM_MODEL = "openai/gpt-oss-20b"  # smaller/faster than -120b; persona replies are short anyway

# Groq enforces quota per model, independently - if the primary model's
# daily/per-minute limit is hit, a different model still has its own
# untouched budget (confirmed by direct testing against this same Groq
# account: querynest-website hit gpt-oss-120b's 200k-tokens/day cap while
# qwen3.8-27b kept succeeding the whole time). chat_reply() below tries
# these in order on a rate-limit error instead of failing the call.
#
# This is our own VETTED order, not "whatever Groq happens to list" -
# each id here was evaluated for answer quality before being added
# (gpt-oss-20b hallucinated an unsupported detail in isolated testing on
# a sibling project's system prompt; qwen3.8-27b didn't). `groq/compound`
# is deliberately excluded - it runs on top of gpt-oss-120b internally
# and shares that model's quota rather than having its own.
#
# Which of these ids are actually still live gets checked dynamically
# against Groq's /v1/models (cached, see _live_model_chain()) rather than
# assumed - Groq does retire/rename models over time.
_FALLBACK_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
_MODEL_LIST_TTL_SECONDS = 3600
_model_list_cache: set[str] = set()
_model_list_cached_at: float = 0.0

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


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str  # e.g. "English", "Urdu" - Whisper's own detected-language name


def transcribe_audio(audio_bytes: bytes, filename: str) -> Transcript:
    """Speech-to-text via Groq's Whisper endpoint. Requests verbose_json
    (rather than the default plain-text response) specifically to get
    Whisper's own language detection back too - app/api/voice.py uses it
    so the assistant replies in the same language the caller spoke,
    rather than always answering in English regardless of input. Raises
    on any API failure - callers translate that into a clear HTTP error."""
    client = get_groq_client()
    model = _clean(os.getenv("GROQ_STT_MODEL")) or DEFAULT_STT_MODEL
    response = client.audio.transcriptions.create(
        model=model,
        file=(filename, audio_bytes),
        response_format="verbose_json",
    )
    return Transcript(text=response.text, language=response.language)


def synthesize_speech(text: str) -> bytes:
    """Text-to-speech via Groq's Orpheus TTS endpoint, returning raw WAV
    bytes (Orpheus only supports response_format="wav", unlike the
    decommissioned playai-tts which returned mp3). `text` is capped at
    _TTS_MAX_CHARS characters before being sent, to bound cost/latency on
    a very long assistant reply."""
    client = get_groq_client()
    model = _clean(os.getenv("GROQ_TTS_MODEL")) or DEFAULT_TTS_MODEL
    voice = _clean(os.getenv("GROQ_TTS_VOICE")) or DEFAULT_TTS_VOICE
    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text[:_TTS_MAX_CHARS],
        response_format="wav",
    )
    return response.read()


def _live_model_chain(primary: str) -> list[str]:
    """[primary, *_FALLBACK_MODELS], filtered down to whichever ids Groq
    actually still serves right now, so a retired/renamed model (this
    has happened before - see the fallback-chain rationale above) drops
    out of the chain automatically instead of wasting a call on every
    single request. Cached for _MODEL_LIST_TTL_SECONDS so this only
    queries Groq's /v1/models occasionally, not on every chat_reply()."""
    global _model_list_cache, _model_list_cached_at  # noqa: PLW0603 - simple process-local cache

    vetted = list(dict.fromkeys([primary, *_FALLBACK_MODELS]))  # de-dup, preserve order
    now = time.monotonic()
    if not _model_list_cache or (now - _model_list_cached_at) > _MODEL_LIST_TTL_SECONDS:
        try:
            live = get_groq_client().models.list()
            _model_list_cache = {m.id for m in live.data}
            _model_list_cached_at = now
        except Exception:  # noqa: BLE001 - listing failed; use whatever we had (or the full vetted list)
            if not _model_list_cache:
                return vetted

    chain = [m for m in vetted if m in _model_list_cache]
    # If the live listing looked empty/wrong somehow, don't strand the
    # caller with zero models to try.
    return chain or vetted


def chat_reply(messages: list[dict]) -> str:
    """One chat-completion turn via Groq's Llama/GPT-OSS models.
    `messages` is the standard OpenAI chat list ([{role, content}, ...]),
    system prompt included by the caller (see app/personas.py). max_tokens
    is capped at 120 - personas are instructed to reply in 1-3 short
    sentences (see app/personas.py's _BASE_RULES), and a lower cap also
    means the model physically cannot ramble into a slow, long reply.

    On a rate-limit error, retries against the next model in the fallback
    chain (see _FALLBACK_MODELS above) instead of failing the call - each
    model has its own independent Groq quota."""
    client = get_groq_client()
    primary = _clean(os.getenv("GROQ_LLM_MODEL")) or DEFAULT_LLM_MODEL

    last_exc: Optional[Exception] = None
    for model in _live_model_chain(primary):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.4,
                max_tokens=120,
            )
            return response.choices[0].message.content or ""
        except RateLimitError as exc:
            last_exc = exc
            continue
    raise last_exc or RuntimeError("No Groq chat model available")
