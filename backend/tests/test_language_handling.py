"""
Unit tests for the language-matching logic in app/api/voice.py: Groq's
Orpheus TTS model is English-only, so a non-English reply must skip Groq
TTS entirely (garbled audio is worse than no audio) and hand back a
BCP-47 tag so the frontend's browser-voice fallback can pronounce it
correctly instead of defaulting to English.
"""

from unittest.mock import patch

from app.api.voice import _bcp47_for, _try_synthesize


def test_bcp47_known_languages():
    assert _bcp47_for("English") == "en-US"
    assert _bcp47_for("Urdu") == "ur-PK"
    assert _bcp47_for("urdu") == "ur-PK"  # case-insensitive
    assert _bcp47_for("Arabic") == "ar-SA"


def test_bcp47_unknown_language_falls_back_to_english():
    assert _bcp47_for("Klingon") == "en-US"


def test_try_synthesize_skips_groq_for_non_english():
    with patch("app.api.voice.synthesize_speech") as mock_synthesize:
        result = _try_synthesize("Yeh Urdu jawab hai.", "Urdu")
    mock_synthesize.assert_not_called()
    assert result == ""


def test_try_synthesize_calls_groq_for_english():
    with patch("app.api.voice.synthesize_speech", return_value=b"fake-wav-bytes") as mock_synthesize:
        result = _try_synthesize("This is an English reply.", "English")
    mock_synthesize.assert_called_once()
    assert result != ""
