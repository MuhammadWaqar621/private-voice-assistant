import asyncio
import base64
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # must run before any app module reads GROQ_* env vars

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.twilio_voice import router as twilio_router
from app.api.voice import router as voice_router
from app.conversation_store import set_cached_greeting
from app.groq_client import chat_reply, groq_configured, synthesize_speech
from app.personas import PERSONAS

logger = logging.getLogger(__name__)


def _warm_up_groq() -> None:
    """Pre-synthesizes each persona's greeting (cached permanently - see
    app/conversation_store.py) and fires one throwaway chat completion, so
    the *first* real "Call" press of a fresh server doesn't also pay for
    Groq's TLS/connection setup on top of normal per-turn latency (that
    one-time warm-up was measured to add several seconds - see the
    project README's latency notes). Runs in a thread off the event loop
    since these are blocking network calls; failures are logged and
    swallowed; on-demand synthesis (app/api/voice.py) still works if this
    hasn't finished yet."""
    if not groq_configured():
        return
    for persona in PERSONAS.values():
        try:
            audio = synthesize_speech(persona.greeting)
            set_cached_greeting(persona.id, base64.b64encode(audio).decode("ascii"))
        except Exception:  # noqa: BLE001 - warm-up is best-effort, never fatal
            logger.warning("Groq TTS warm-up failed for persona %r", persona.id, exc_info=True)
    try:
        chat_reply([{"role": "user", "content": "Reply with OK."}])
    except Exception:  # noqa: BLE001
        logger.warning("Groq LLM warm-up call failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.get_event_loop().run_in_executor(None, _warm_up_groq)
    yield


app = FastAPI(title="Private Voice Assistant", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Any localhost/127.0.0.1 port, not a hardcoded one - the frontend's
    # dev-server port varies (e.g. when a default port is already taken by
    # something else on the machine and Vite/Docker picks another).
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_router)
app.include_router(twilio_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "groq_configured": groq_configured()}
