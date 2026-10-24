import os

from fastapi.testclient import TestClient

from app import api


def test_ask_without_api_key_env(monkeypatch) -> None:
    monkeypatch.delenv("CLOUDNOVA_API_KEY", raising=False)
    client = TestClient(api.app)
    r = client.post(
        "/ask",
        json={"question": "How much have we given back in refunds?", "use_llm": False},
    )
    assert r.status_code == 200
    assert r.json()["rows"][0]["refunds_usd"] > 0


def test_ask_requires_key_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDNOVA_API_KEY", "secret-test-key")
    client = TestClient(api.app)
    denied = client.post(
        "/ask",
        json={"question": "How much have we given back in refunds?", "use_llm": False},
    )
    assert denied.status_code == 401
    ok = client.post(
        "/ask",
        headers={"X-API-Key": "secret-test-key"},
        json={"question": "How much have we given back in refunds?", "use_llm": False},
    )
    assert ok.status_code == 200
