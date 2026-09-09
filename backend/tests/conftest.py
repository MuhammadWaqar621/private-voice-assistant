import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()

from app.groq_client import groq_configured
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


requires_groq = pytest.mark.skipif(not groq_configured(), reason="GROQ_API_KEY not set")
