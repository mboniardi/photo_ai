"""Test per auth/google_oauth.py."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


SECRET = "test-secret-key"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "fake-client-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def _make_authed_client(app):
    from auth.session import create_session_token
    token = create_session_token(
        {"email": "mario@gmail.com", "name": "Mario", "picture": "https://x"},
        SECRET,
    )
    return TestClient(app, raise_server_exceptions=False, cookies={"photo_ai_session": token})


class TestAuthMe:
    def test_returns_401_without_cookie(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_returns_user_with_valid_cookie(self, client):
        c = _make_authed_client(client.app)
        resp = c.get("/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "mario@gmail.com"
        assert data["name"] == "Mario"


class TestAuthLogout:
    def test_redirects_to_login(self, client):
        resp = client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "/auth/login" in resp.headers["location"]

    def test_clears_cookie(self, client):
        resp = client.get("/auth/logout", follow_redirects=False)
        set_cookie = resp.headers.get("set-cookie", "")
        assert "photo_ai_session" in set_cookie


class TestApiProtection:
    def test_api_returns_401_without_auth(self, client):
        resp = client.get("/api/photos")
        assert resp.status_code == 401

    def test_health_is_public(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
