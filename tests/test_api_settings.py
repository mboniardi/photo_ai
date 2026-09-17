"""Test per api/settings.py — GET/PUT /api/settings."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    from auth.session import create_session_token
    token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token})


class TestGetSettings:
    def test_returns_200(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200

    def test_returns_dict(self, client):
        data = client.get("/api/settings").json()
        assert isinstance(data, dict)


class TestPutSettings:
    def test_saves_ai_engine(self, client):
        client.put("/api/settings", json={"ai_engine": "groq"})
        data = client.get("/api/settings").json()
        assert data.get("ai_engine") == "groq"

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


class TestDeepSeekSetting:
    def test_deepseek_api_key_is_allowed(self):
        from api.settings import ALLOWED_KEYS
        assert "deepseek_api_key" in ALLOWED_KEYS

    def test_build_engine_returns_deepseek(self):
        from api.settings import build_engine
        from services.ai.deepseek import DeepSeekEngine
        engine = build_engine("deepseek", api_key="sk-test")
        assert isinstance(engine, DeepSeekEngine)

    def test_build_engine_rejects_unknown(self):
        from api.settings import build_engine
        with pytest.raises(ValueError, match="sconosciuto"):
            build_engine("inesistente", api_key="x")

    def test_engine_api_key_returns_configured_key(self, client):
        import config
        from database.settings import set_setting
        from api.settings import engine_api_key
        set_setting(config.LOCAL_DB, key="groq_api_key", value="gsk-configured")
        assert engine_api_key("groq") == "gsk-configured"

    def test_engine_api_key_rejects_unknown(self, client):
        from api.settings import engine_api_key
        with pytest.raises(ValueError, match="sconosciuto"):
            engine_api_key("inesistente")
