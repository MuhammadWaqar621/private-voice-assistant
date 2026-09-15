import asyncio
import base64
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # must run before any app module reads GROQ_* env vars

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.twilio_voice import router as twilio_router
from app.api.voice import router as voice_router
from app.company_profile import EXAMPLE_TEMPLATES, default_greeting, greeting_cache_key
from app.conversation_store import set_cached_greeting
from app.groq_client import chat_reply, groq_configured, synthesize_speech

logger = logging.getLogger(__name__)


def _warm_up_groq() -> None:
    """Pre-synthesizes the greeting for each example template (cached
    permanently - see app/conversation_store.py) and fires one throwaway
    chat completion, so the *first* real "Call" press of a fresh server
    doesn't also pay for Groq's TLS/connection setup on top of normal
    per-turn latency (that one-time warm-up was measured to add several
    seconds - see the project README's latency notes). A company a user
    types in fresh (not one of the examples) still gets its greeting
    synthesized on demand by app/api/voice.py - this just covers the
    common case of a visitor using a quick-fill template. Runs in a
    thread off the event loop since these are blocking network calls;
    failures are logged and swallowed."""
    if not groq_configured():
        return
    for template in EXAMPLE_TEMPLATES:
        try:
            greeting = default_greeting(template["name"])
            audio = synthesize_speech(greeting)
            set_cached_greeting(greeting_cache_key(template["name"]), base64.b64encode(audio).decode("ascii"))
        except Exception:  # noqa: BLE001 - warm-up is best-effort, never fatal
            logger.warning("Groq TTS warm-up failed for template %r", template["name"], exc_info=True)
    try:
        chat_reply([{"role": "user", "content": "Reply with OK."}])
    except Exception:  # noqa: BLE001
        logger.warning("Groq LLM warm-up call failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Vercel serverless note: this fires warm-up in the background without
    # awaiting it, same as always, but on Vercel each cold start is a fresh
    # container/process (see app/conversation_store.py's Vercel note), so
    # warm-up reruns on every cold start rather than once for the app's
    # whole lifetime, and may not finish before the container is frozen
    # between requests. Neither is a correctness problem - it's the same
    # "best-effort, never fatal" warm-up as local dev, worst case a given
    # cold instance's first request pays the full latency this was meant
    # to hide instead of hitting a warm cache.
    asyncio.get_event_loop().run_in_executor(None, _warm_up_groq)
    yield


app = FastAPI(title="Private Voice Assistant", version="0.1.0", lifespan=lifespan)

# FRONTEND_ORIGIN: comma-separated exact origins to allow in addition to
# localhost (e.g. "https://your-app.vercel.app,https://your-domain.com").
# Needed once frontend and backend are deployed separately - as they are
# on Vercel, one project per README's "Deploying on Vercel" section - since
# they then live on different origins and the localhost-only regex below
# would otherwise silently block every request from the deployed frontend
# (a fetch() CORS failure, not a 4xx from this server - easy to miss).
# Left unset, only localhost/127.0.0.1 origins are allowed, same as before.
_extra_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGIN", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    # Any localhost/127.0.0.1 port, not a hardcoded one - the frontend's
    # dev-server port varies (e.g. when a default port is already taken by
    # something else on the machine and Vite/Docker picks another).
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_origins=_extra_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_router)
app.include_router(twilio_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "groq_configured": groq_configured()}
