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


class TestAuthCallback:
    def test_callback_with_authorized_email_sets_cookie_and_redirects(self, client, tmp_path, monkeypatch):
        from auth.whitelist import load_whitelist
        # Set up whitelist with mario@gmail.com
        emails_file = tmp_path / "emails.txt"
        emails_file.write_text("mario@gmail.com\n")

        # Patch load_whitelist to return our test whitelist
        monkeypatch.setattr(
            "auth.google_oauth.load_whitelist",
            lambda path: load_whitelist(str(emails_file))
        )

        mock_token = {
            "userinfo": {
                "email": "mario@gmail.com",
                "name": "Mario Rossi",
                "picture": "https://example.com/pic.jpg",
            }
        }

        with patch("auth.google_oauth.oauth") as mock_oauth:
            mock_oauth.google.authorize_access_token = AsyncMock(return_value=mock_token)
            resp = client.get("/auth/callback", follow_redirects=False)

        assert resp.status_code in (302, 307)
        assert resp.headers["location"] == "/"
        assert "photo_ai_session" in resp.headers.get("set-cookie", "")

    def test_callback_with_unauthorized_email_returns_403(self, client, tmp_path, monkeypatch):
        from auth.whitelist import load_whitelist
        # Empty whitelist — nobody authorized
        emails_file = tmp_path / "emails.txt"
        emails_file.write_text("")

        # Patch load_whitelist to return our test whitelist
        monkeypatch.setattr(
            "auth.google_oauth.load_whitelist",
            lambda path: load_whitelist(str(emails_file))
        )

        mock_token = {
            "userinfo": {
                "email": "hacker@evil.com",
                "name": "Hacker",
                "picture": "",
            }
        }

        with patch("auth.google_oauth.oauth") as mock_oauth:
            mock_oauth.google.authorize_access_token = AsyncMock(return_value=mock_token)
            resp = client.get("/auth/callback")

        assert resp.status_code == 403


class TestCallbackUrlBehindProxy:
    """Dietro cloudflared la richiesta arriva al container come
    http://localhost:8081: l'URL dedotto dalla richiesta non coincide con
    quello registrato su Google, e il login fallisce lato Google."""

    class _FakeUrl:
        path = "/auth/callback"
        def __str__(self):
            return "http://localhost:8081/auth/callback"

    class _FakeRequest:
        def url_for(self, name):
            return TestCallbackUrlBehindProxy._FakeUrl()

    def test_uses_public_base_url_when_configured(self, monkeypatch):
        import config
        from auth.google_oauth import callback_url
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://photo.primafila.com")
        assert callback_url(self._FakeRequest()) == "https://photo.primafila.com/auth/callback"

    def test_tolerates_a_trailing_slash(self, monkeypatch):
        import config
        from auth.google_oauth import callback_url
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://photo.primafila.com/")
        assert callback_url(self._FakeRequest()) == "https://photo.primafila.com/auth/callback"

    def test_falls_back_to_the_request_when_not_configured(self, monkeypatch):
        import config
        from auth.google_oauth import callback_url
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
        assert callback_url(self._FakeRequest()) == "http://localhost:8081/auth/callback"


class TestSecureCookie:
    def _set(self):
        from fastapi.responses import Response
        from auth.session import set_session_cookie
        r = Response()
        set_session_cookie(r, {"email": "a@b.c", "name": "A", "picture": ""})
        return r.headers["set-cookie"]

    def test_secure_flag_when_served_over_https(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://photo.primafila.com")
        monkeypatch.setattr(config, "SECRET_KEY", "test-secret")
        assert "secure" in self._set().lower()

    def test_no_secure_flag_in_plain_http(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "")
        monkeypatch.setattr(config, "SECRET_KEY", "test-secret")
        assert "secure" not in self._set().lower()

    def test_httponly_is_kept(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://photo.primafila.com")
        monkeypatch.setattr(config, "SECRET_KEY", "test-secret")
        assert "httponly" in self._set().lower()
