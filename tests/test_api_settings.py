"""Test per api/settings.py — GET/PUT /api/settings."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    return TestClient(app)


class TestGetSettings:
    def test_returns_200(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200

    def test_returns_dict(self, client):
        data = client.get("/api/settings").json()
        assert isinstance(data, dict)


class TestPutSettings:
    def test_saves_ai_engine(self, client):
        client.put("/api/settings", json={"ai_engine": "ollama"})
        data = client.get("/api/settings").json()
        assert data.get("ai_engine") == "ollama"

    def test_saves_multiple_keys(self, client):
        client.put("/api/settings", json={
            "ai_engine": "gemini",
            "analysis_rpm_limit": "12",
        })
        data = client.get("/api/settings").json()
        assert data["ai_engine"] == "gemini"
        assert data["analysis_rpm_limit"] == "12"

    def test_returns_200(self, client):
        resp = client.put("/api/settings", json={"ai_engine": "gemini"})
        assert resp.status_code == 200

    def test_rejects_unknown_key(self, client):
        resp = client.put("/api/settings", json={"unknown_key": "value"})
        assert resp.status_code == 422
