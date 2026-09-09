"""
The voice-call endpoints: one round trip per turn of the conversation.

The frontend records a short clip of the caller speaking, POSTs it here
along with the persona (which company) and the conversation so far. This
endpoint runs the full pipeline - transcribe (Groq Whisper) -> think (Groq
Llama, grounded by the persona's system prompt) -> speak (Groq Orpheus TTS)
- and returns the transcript, reply text, and reply audio together so the
frontend can display and play them in one step.

Speech synthesis is treated as best-effort: Groq's TTS model requires a
one-time terms acceptance in the Groq console (see backend/.env.example),
so a synthesis failure does not fail the whole turn - `reply_audio_base64`
comes back empty and the frontend falls back to the browser's own
text-to-speech voice for that reply.

The server is intentionally stateless: conversation history lives in the
browser tab (sent back on every turn) rather than a database, since a
demo call has no need to survive a page reload.
"""

import base64
import json

from fastapi import APIRouter, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.conversation_store import get_cached_greeting, set_cached_greeting
from app.groq_client import chat_reply, groq_configured, synthesize_speech, transcribe_audio
from app.personas import PERSONAS, get_persona

router = APIRouter(prefix="/api/voice", tags=["voice"])

_MAX_HISTORY_TURNS = 12  # caps prompt size/cost for a long-running demo call

# Groq's Orpheus TTS model (canopylabs/orpheus-v1-english) is English-only -
# feeding it non-English text produces mispronounced/garbled audio rather
# than a clean failure, so it's only used for English replies. For every
# other detected language, the reply goes back as text-only and the
# frontend's browser-voice fallback speaks it, using this BCP-47 tag to
# pick a matching voice/pronunciation instead of defaulting to English.
_LANGUAGE_TO_BCP47 = {
    "english": "en-US",
    "urdu": "ur-PK",
    "arabic": "ar-SA",
    "hindi": "hi-IN",
    "french": "fr-FR",
    "spanish": "es-ES",
    "german": "de-DE",
    "chinese": "zh-CN",
    "turkish": "tr-TR",
    "russian": "ru-RU",
    "persian": "fa-IR",
    "punjabi": "pa-IN",
    "pashto": "ps-AF",
    "bengali": "bn-BD",
}


def _bcp47_for(language_name: str) -> str:
    return _LANGUAGE_TO_BCP47.get(language_name.strip().lower(), "en-US")


class PersonaOut(BaseModel):
    id: str
    name: str
    description: str
    greeting: str


class TurnMessage(BaseModel):
    role: str
    content: str


class TurnResponse(BaseModel):
    user_text: str
    reply_text: str
    reply_audio_base64: str  # empty string means: use browser TTS for reply_text instead
    language: str  # BCP-47 tag (e.g. "ur-PK") for the frontend's browser-voice fallback


def _groq_not_configured_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "groq_not_configured",
            "message": "Groq is not configured. Set GROQ_API_KEY in backend/.env.",
        },
    )


class GreetingResponse(BaseModel):
    greeting_text: str
    greeting_audio_base64: str  # empty string means: use browser TTS for greeting_text instead
    language: str  # BCP-47 tag for the frontend's browser-voice fallback


def _try_synthesize(text: str, language_name: str) -> str:
    """Best-effort TTS: returns base64 audio, or "" when Groq's TTS
    shouldn't be used for this reply - either because it isn't usable
    right now (e.g. terms not yet accepted in the Groq console - see
    backend/.env.example), or because the reply isn't English (Orpheus is
    an English-only model - see _LANGUAGE_TO_BCP47's comment above).
    Callers fall back to the browser's own voice rather than failing the
    request."""
    if language_name.strip().lower() != "english":
        return ""
    try:
        return base64.b64encode(synthesize_speech(text)).decode("ascii")
    except Exception:  # noqa: BLE001 - any TTS failure just means "no server audio"
        return ""


@router.get("/personas", response_model=list[PersonaOut])
def list_personas() -> list[PersonaOut]:
    return [
        PersonaOut(id=p.id, name=p.name, description=p.description, greeting=p.greeting)
        for p in PERSONAS.values()
    ]


@router.get("/greeting/{persona}", response_model=GreetingResponse)
def get_greeting(persona: str) -> GreetingResponse:
    """Returns the persona's opening line - called once when the caller
    presses "Call", so the assistant speaks first, like a real IVR. The
    audio is pre-synthesized and cached at server startup (see
    app/main.py's warm-up step) since greeting text is static, so this is
    normally a cache hit with no Groq call (and no wait) on the critical
    "press Call" path; it only synthesizes here as a fallback if warm-up
    hadn't completed yet (e.g. a request right as the server starts)."""
    if not groq_configured():
        raise _groq_not_configured_error()

    persona_obj = get_persona(persona)
    if persona_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown persona '{persona}'")

    cached = get_cached_greeting(persona)
    if cached is not None:
        return GreetingResponse(greeting_text=persona_obj.greeting, greeting_audio_base64=cached, language="en-US")

    # Greeting text is always English (authored in personas.py), unlike a
    # caller's reply, so this always goes through Groq TTS rather than
    # _try_synthesize's language gate.
    try:
        audio_base64 = base64.b64encode(synthesize_speech(persona_obj.greeting)).decode("ascii")
    except Exception:  # noqa: BLE001
        audio_base64 = ""
    if audio_base64:
        set_cached_greeting(persona, audio_base64)
    return GreetingResponse(greeting_text=persona_obj.greeting, greeting_audio_base64=audio_base64, language="en-US")


@router.post("/turn", response_model=TurnResponse)
async def take_turn(
    audio: UploadFile,
    persona: str = Form(...),
    history: str = Form("[]"),
) -> TurnResponse:
    if not groq_configured():
        raise _groq_not_configured_error()

    persona_obj = get_persona(persona)
    if persona_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown persona '{persona}'")

    try:
        parsed_history = json.loads(history)
        prior_turns = [TurnMessage.model_validate(m) for m in parsed_history]
    except (json.JSONDecodeError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="`history` must be a JSON array of {role, content}")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty audio clip")

    try:
        transcript = transcribe_audio(audio_bytes, audio.filename or "clip.webm")
    except Exception as exc:  # noqa: BLE001 - surface any Groq failure clearly, don't crash
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "transcription_failed", "message": str(exc)},
        )

    user_text = transcript.text
    if not user_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "empty_transcript", "message": "Didn't catch any speech in that clip - try again."},
        )

    messages = [{"role": "system", "content": persona_obj.system_prompt}]
    for turn in prior_turns[-_MAX_HISTORY_TURNS:]:
        if turn.role in ("user", "assistant"):
            messages.append({"role": turn.role, "content": turn.content})
    # The language directive is embedded directly in the user message
    # (not a separate system message) - empirically, a smaller/faster
    # model follows an instruction attached to the very message it's
    # responding to far more reliably than one a message earlier, which
    # it can otherwise drift back to English on despite the persona's own
    # language-matching rule.
    messages.append(
        {
            "role": "user",
            "content": f"[Reply only in {transcript.language}.] {user_text}",
        }
    )

    try:
        reply_text = chat_reply(messages)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "llm_failed", "message": str(exc)},
        )

    if not reply_text.strip():
        reply_text = "Sorry, I didn't quite catch that - could you say it again?"

    return TurnResponse(
        user_text=user_text,
        reply_text=reply_text,
        reply_audio_base64=_try_synthesize(reply_text, transcript.language),
        language=_bcp47_for(transcript.language),
    )
