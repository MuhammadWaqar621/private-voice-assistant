"""
In-memory state for real phone calls (app/api/twilio_voice.py).

Twilio calls our webhooks once per turn (no persistent connection to hold
state in, unlike the browser flow where the tab itself holds history), so
conversation history has to live somewhere on the server, keyed by
Twilio's CallSid. A synthesized reply also has to be reachable at a plain
URL for TwiML's <Play> to fetch - _audio_cache holds those bytes briefly
so /api/twilio/audio/{id} can serve them.

A single process's dict is enough for a demo (one uvicorn worker); this
is not meant to survive a restart or scale across multiple workers.
"""

import time
from threading import Lock

_AUDIO_TTL_SECONDS = 300  # Twilio fetches <Play> URLs within seconds of issuing them

_history: dict[str, list[dict]] = {}
_audio_cache: dict[str, tuple[bytes, float]] = {}
_greeting_cache: dict[str, str] = {}  # persona id -> base64 audio; permanent, greeting text never changes
_lock = Lock()


def get_cached_greeting(persona_id: str) -> str | None:
    """Pre-warmed at startup (see app/main.py) so the very first "Call"
    press of the day doesn't pay for a TTS round trip - a persona's
    greeting text is static, so synthesizing it once and reusing the
    audio is free correctness-wise."""
    with _lock:
        return _greeting_cache.get(persona_id)


def set_cached_greeting(persona_id: str, audio_base64: str) -> None:
    with _lock:
        _greeting_cache[persona_id] = audio_base64


def get_history(call_sid: str) -> list[dict]:
    with _lock:
        return list(_history.get(call_sid, []))


def append_turn(call_sid: str, role: str, content: str) -> None:
    with _lock:
        _history.setdefault(call_sid, []).append({"role": role, "content": content})


def clear_call(call_sid: str) -> None:
    with _lock:
        _history.pop(call_sid, None)


def cache_audio(audio_id: str, data: bytes) -> None:
    with _lock:
        _audio_cache[audio_id] = (data, time.time())
        _prune_audio_cache_locked()


def get_audio(audio_id: str) -> bytes | None:
    with _lock:
        entry = _audio_cache.get(audio_id)
        return entry[0] if entry else None


def _prune_audio_cache_locked() -> None:
    cutoff = time.time() - _AUDIO_TTL_SECONDS
    expired = [k for k, (_, ts) in _audio_cache.items() if ts < cutoff]
    for k in expired:
        _audio_cache.pop(k, None)
