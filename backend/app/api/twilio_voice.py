"""
Real-phone-call endpoints for Twilio Voice. Point a Twilio phone number's
"A call comes in" webhook at POST {your public URL}/api/twilio/voice and
anyone who dials that number talks to the same persona/Groq pipeline the
browser demo uses (app/api/voice.py) - just reached over the phone
network instead of a browser tab.

How a call flows through this file:
  1. Twilio POSTs to /voice when the call connects. We reply with TwiML
     that plays the persona's greeting and opens a <Gather> to listen.
  2. Twilio does its own speech-to-text on what the caller says (Twilio's
     built-in recognizer, not Groq Whisper - see the module-level note
     below on why) and POSTs the transcript to /gather.
  3. /gather runs that transcript through the same persona-grounded Groq
     LLM as the browser flow, synthesizes the reply with Groq TTS, and
     replies with TwiML that plays it and re-opens <Gather> for the next
     turn - repeating until the caller hangs up.
  4. /audio/{id}.wav serves a synthesized reply's bytes so TwiML's <Play>
     (which needs a fetchable URL, not inline audio) can retrieve it.
  5. /status is Twilio's call-status callback, used only to free the
     in-memory conversation history once a call ends.

Why Twilio's own speech-to-text instead of Groq Whisper: Twilio only
exposes a caller's raw audio via a WebSocket "Media Stream" of 8kHz mulaw
chunks, which would need real-time buffering, silence detection, and
transcoding to hand to Whisper - a much larger undertaking than this
demo's scope, and not something that can be verified without a live
Twilio account and phone call to test against. Twilio's <Gather
input="speech"> does speech-to-text for you and simply POSTs back the
resulting text, which plugs directly into the same chat_reply() call the
browser flow uses. The trade-off: STT quality/latency there is whatever
Twilion's own recognizer gives you, not Groq Whisper's.

This can't be tested end-to-end without a Twilio account (phone number +
Account SID/Auth Token) and a public URL for Twilio to reach (ngrok for
local testing, or a real deployment) - see the README's Twilio section.
What *can* be verified without that - and was - is that these endpoints
return correct TwiML and behave correctly given requests shaped exactly
like Twilio's, since Twilio is just an HTTP client hitting a webhook.
"""

import os
import uuid

from fastapi import APIRouter, Form, HTTPException, Response

from app.conversation_store import append_turn, cache_audio, clear_call, get_audio, get_history
from app.groq_client import chat_reply, synthesize_speech
from app.personas import Persona, get_persona

router = APIRouter(prefix="/api/twilio", tags=["twilio"])

_ENDED_CALL_STATUSES = {"completed", "failed", "busy", "no-answer", "canceled"}


def _persona_for_call() -> Persona:
    """One Twilio number maps to one persona for this demo (configurable
    via TWILIO_DEFAULT_PERSONA) - a production system would look this up
    by the `To` number Twilio sends, for a pool of numbers/companies."""
    persona_id = os.getenv("TWILIO_DEFAULT_PERSONA", "jazz").strip() or "jazz"
    return get_persona(persona_id) or get_persona("jazz")  # type: ignore[return-value]


def _twiml_response(xml: str) -> Response:
    return Response(content=xml, media_type="application/xml")


def _speak_and_gather_twiml(prompt_audio_url: str | None, prompt_text: str) -> str:
    """<Play> the given audio if Groq TTS produced any, else fall back to
    Twilio's own <Say> voice for that same text - mirrors the browser
    flow's Groq-TTS-with-browser-voice-fallback pattern (app/api/voice.py)
    so a Groq TTS outage degrades gracefully here too, not just online."""
    prompt = f"<Play>{prompt_audio_url}</Play>" if prompt_audio_url else f"<Say>{_xml_escape(prompt_text)}</Say>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  {prompt}
  <Gather input="speech" action="/api/twilio/gather" method="POST" speechTimeout="auto" speechModel="phone_call">
  </Gather>
  <Say>Sorry, I didn't hear anything. Goodbye.</Say>
  <Hangup/>
</Response>"""


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _cache_and_url(request_base_url: str, audio_bytes: bytes) -> str:
    audio_id = uuid.uuid4().hex
    cache_audio(audio_id, audio_bytes)
    return f"{request_base_url.rstrip('/')}/api/twilio/audio/{audio_id}.wav"


@router.post("/voice")
async def incoming_call() -> Response:
    """Twilio's "a call comes in" webhook - answers with the persona's
    greeting and starts listening for the caller's first turn."""
    persona = _persona_for_call()
    audio_url = None
    try:
        # Not routed through app.main's greeting cache (that stores
        # browser-flow base64 JSON, not a fetchable URL Twilio can <Play>)
        # - a real deployment could share a cache keyed the same way;
        # skipped here to keep this module's scope to the call flow itself.
        audio_bytes = synthesize_speech(persona.greeting)
        audio_url = _cache_and_url(_public_base_url(), audio_bytes)
    except Exception:  # noqa: BLE001 - fall back to Twilio's own voice below
        pass
    return _twiml_response(_speak_and_gather_twiml(audio_url, persona.greeting))


@router.post("/gather")
async def gather_result(
    CallSid: str = Form(...),
    SpeechResult: str = Form(""),
) -> Response:
    """Twilio's <Gather> callback: SpeechResult is the transcript from
    Twilio's own speech recognition (see module docstring for why this
    isn't Groq Whisper here). Runs it through the same persona-grounded
    Groq LLM + TTS as the browser flow and keeps the call going."""
    persona = _persona_for_call()

    if not SpeechResult.strip():
        return _twiml_response(
            """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Sorry, I didn't catch that.</Say>
  <Gather input="speech" action="/api/twilio/gather" method="POST" speechTimeout="auto"></Gather>
  <Say>Goodbye.</Say>
  <Hangup/>
</Response>"""
        )

    history = get_history(CallSid)
    messages = [{"role": "system", "content": persona.system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": SpeechResult})

    try:
        reply_text = chat_reply(messages)
    except Exception:  # noqa: BLE001 - a Groq outage shouldn't drop the call
        reply_text = "Sorry, I'm having trouble right now. Please try calling back shortly."

    append_turn(CallSid, "user", SpeechResult)
    append_turn(CallSid, "assistant", reply_text)

    audio_url = None
    try:
        audio_bytes = synthesize_speech(reply_text)
        audio_url = _cache_and_url(_public_base_url(), audio_bytes)
    except Exception:  # noqa: BLE001 - fall back to Twilio's own voice below
        pass

    return _twiml_response(_speak_and_gather_twiml(audio_url, reply_text))


@router.get("/audio/{audio_id}.wav")
def get_call_audio(audio_id: str) -> Response:
    """Serves a synthesized reply's bytes so TwiML's <Play> (issued by
    /voice or /gather above) can fetch them - <Play> needs a URL, not
    inline audio."""
    data = get_audio(audio_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    return Response(content=data, media_type="audio/wav")


@router.post("/status")
async def call_status(CallSid: str = Form(...), CallStatus: str = Form("")) -> Response:
    """Twilio's call-status callback (configure it on the number, or via
    <Dial>/<Gather> action params) - frees this call's in-memory history
    once it ends, so long-running server memory doesn't grow unbounded
    across many calls."""
    if CallStatus in _ENDED_CALL_STATUSES:
        clear_call(CallSid)
    return Response(status_code=204)


def _public_base_url() -> str:
    """The externally-reachable URL Twilio can fetch <Play> audio from -
    a plain localhost URL is useless to Twilio's servers. Set
    PUBLIC_BASE_URL to your ngrok/deployment URL (see README)."""
    url = os.getenv("PUBLIC_BASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "PUBLIC_BASE_URL is not set - Twilio needs a publicly reachable URL to fetch "
            "synthesized audio from (e.g. your ngrok URL). See backend/.env.example."
        )
    return url
