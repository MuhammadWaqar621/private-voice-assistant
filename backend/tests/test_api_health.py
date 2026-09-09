def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_personas(client):
    resp = client.get("/api/voice/personas")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert {"jazz", "bank"} <= ids


def test_turn_unknown_persona_404(client):
    resp = client.post(
        "/api/voice/turn",
        data={"persona": "nope", "history": "[]"},
        files={"audio": ("clip.webm", b"not-really-audio", "audio/webm")},
    )
    assert resp.status_code == 404


def test_turn_bad_history_json_400(client):
    resp = client.post(
        "/api/voice/turn",
        data={"persona": "jazz", "history": "not-json"},
        files={"audio": ("clip.webm", b"not-really-audio", "audio/webm")},
    )
    assert resp.status_code == 400
