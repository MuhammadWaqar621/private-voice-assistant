"""
Vercel serverless entry point for the FastAPI backend.

Vercel's Python runtime auto-detects an ASGI application named `app` in
any module under api/ and wraps it as a serverless function - it does not
run `uvicorn` itself, Vercel's runtime handles the ASGI protocol directly.
`vercel.json`'s rewrite sends every incoming path (not just /api/index) to
this one function, so FastAPI's own routing in app/main.py (which already
prefixes every real route with /api/voice/..., /api/twilio/..., or
/api/health) takes over from there. One serverless function ends up
serving the whole backend; this file's only job is to make the existing
`app` object importable and re-export it under the name Vercel looks for.

Not used by local development - `uvicorn app.main:app` (see README) still
runs the app directly. This file only exists for the Vercel deployment.
"""

import sys
from pathlib import Path

# Make sure the project root (one level up from api/, where the `app`
# package lives) is on sys.path regardless of the exact working directory
# Vercel's builder invokes this file from - mirrors how `uvicorn
# app.main:app` works when run from the backend/ directory locally.
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app  # noqa: E402  (import after the sys.path fix above)

__all__ = ["app"]
