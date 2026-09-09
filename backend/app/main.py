from dotenv import load_dotenv

load_dotenv()  # must run before any app module reads GROQ_* env vars

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.voice import router as voice_router
from app.groq_client import groq_configured

app = FastAPI(title="Private Voice Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(voice_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "groq_configured": groq_configured()}
