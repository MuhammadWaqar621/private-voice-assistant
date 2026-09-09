# Private Voice Assistant

An AI-powered voice helpline demo — the kind of assistant a telecom (Jazz)
or a bank could put in front of an IVR: the caller speaks, the assistant
listens, understands, and answers back out loud, grounded in that
company's own facts.

This is a **browser-based demo**, not a real phone system: there's no
Twilio/telephony integration, so it doesn't answer literal incoming phone
calls. Instead, the browser's microphone stands in for the phone line -
the same listen → think → speak loop a real call-center voicebot runs,
minus the carrier plumbing.

## How it works

One Groq API key drives the whole pipeline:

1. **Listen** — the browser records a short clip while you hold the "talk"
   button; it's sent to Groq's **Whisper** model for speech-to-text.
2. **Think** — the transcript, plus the conversation so far, goes to a
   **Groq-hosted LLM** along with a system prompt for whichever company
   persona you picked (see `backend/app/personas.py`). The persona is
   instructed to stay in scope, never invent real account data, and offer
   a human handoff when it can't help.
3. **Speak** — the reply text is sent to Groq's **Orpheus** TTS model and
   played back. If Orpheus isn't available yet (see **Enabling Groq's
   voice** below), the browser's own built-in voice speaks the reply
   instead, so the demo always works.

```
 Browser mic ──▶ FastAPI /api/voice/turn ──▶ Groq Whisper (STT)
                                          ──▶ Groq LLM (persona-grounded reply)
                                          ──▶ Groq Orpheus (TTS) ──▶ Browser <audio>
                                                   │
                                                   └─ falls back to the browser's
                                                      own voice if Orpheus isn't
                                                      enabled yet
```

The backend is stateless — conversation history lives in the browser tab
and is sent back with each turn, so there's no database to run.

## Project layout

```
backend/    FastAPI app (Groq STT/LLM/TTS wrapper, persona config, API)
frontend/   React + TypeScript call UI (Vite)
```

## Prerequisites

- Python 3.11+
- Node.js 20+ (or Docker, if you don't have Node installed - see below)
- A free [Groq API key](https://console.groq.com/keys)
- Chrome or Edge (for microphone recording + the browser voice fallback)

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

copy .env.example .env        # Windows: copy, macOS/Linux: cp
# then edit .env and set GROQ_API_KEY

uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
copy .env.example .env   # already points at http://localhost:8000 by default
npm run dev
```

Open the URL Vite prints (typically http://localhost:5173), pick a
persona, press **Call**, then hold **Hold to talk** while you speak and
release to send.

No Node.js installed? Run the frontend via Docker instead:

```bash
docker run --rm -it -p 5173:5173 -v "${PWD}/frontend:/app" -w /app node:20-alpine sh -c "npm install && npm run dev -- --host 0.0.0.0"
```

### 3. (Optional) Run both with Docker Compose

```bash
docker compose up --build
```

Backend on `:8000`, frontend on `:4173`.

## Enabling Groq's own voice (Orpheus TTS)

Groq's previous TTS model (`playai-tts`) has been decommissioned; its
replacement, `canopylabs/orpheus-v1-english`, requires a one-time terms
acceptance by the org admin:

1. Visit https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english
2. Accept the model terms.

Until that's done, `synthesize_speech()` calls fail gracefully - the
backend still returns the assistant's text reply, and the frontend speaks
it with the browser's own `speechSynthesis` voice instead. No restart or
code change is needed once you accept the terms; the next reply will use
Groq's voice automatically.

## Adding a new company persona

Add an entry to `PERSONAS` in `backend/app/personas.py`: an id, a display
name, a short description, an opening greeting, and a block of "knowledge"
facts the assistant may rely on. Nothing else needs to change - the
frontend's persona dropdown and the `/api/voice/*` endpoints look personas
up by id automatically.

## Testing

### Backend

```bash
cd backend
pytest -v                    # unit tests + real Groq API integration tests
pytest -v -m "not integration"   # skip the tests that call the live Groq API
```

The integration tests actually call Groq's STT and LLM endpoints (using
pre-recorded `.wav` fixtures in `tests/fixtures/` so they don't depend on
TTS being available) to verify the real pipeline - not just mocks. TTS
round-trip tests skip automatically (with a clear message) until Orpheus's
terms are accepted, per above.

### Frontend

```bash
cd frontend
npm test          # vitest unit tests for the API client
npm run build     # type-checks and production-builds the app
```

## Design notes / limitations

- **Not a phone line.** Answering real inbound calls would need a
  telephony provider (e.g. Twilio Voice + Media Streams) wired to this
  same backend pipeline. That requires your own phone number and billing
  account, so it's out of scope for this demo - the architecture above is
  built so that swap is additive (a new `/api/voice/twilio-stream`
  endpoint) rather than a rewrite.
- **Turn-based, not full-duplex streaming.** Groq's Whisper endpoint is
  request/response, not a live socket, so this is "hold to talk, release
  to get an answer" rather than a caller and the AI talking over each
  other. Groq's inference is fast enough that this still feels close to
  real-time.
- **No real account data, ever.** Personas are explicitly instructed to
  never fabricate balances, transactions, or personal data, and to offer
  a human handoff for anything requiring identity verification.
