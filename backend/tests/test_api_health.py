def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_templates(client):
    resp = client.get("/api/voice/templates")
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()}
    assert len(names) >= 2  # example quick-fill templates exist


def test_turn_missing_company_name_400(client):
    resp = client.post(
        "/api/voice/turn",
        data={"company_name": "", "company_details": "", "history": "[]"},
        files={"audio": ("clip.webm", b"not-really-audio", "audio/webm")},
    )
    assert resp.status_code == 400


def test_turn_bad_history_json_400(client):
    resp = client.post(
        "/api/voice/turn",
        data={"company_name": "Acme Widgets", "company_details": "", "history": "not-json"},
        files={"audio": ("clip.webm", b"not-really-audio", "audio/webm")},
    )
    assert resp.status_code == 400
