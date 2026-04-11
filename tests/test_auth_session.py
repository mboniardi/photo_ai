"""Test per auth/session.py."""
import pytest
from fastapi.testclient import TestClient


SECRET = "test-secret-key-12345"


class TestCreateDecodeSessionToken:
    def test_roundtrip(self):
        from auth.session import create_session_token, decode_session_token
        user = {"email": "mario@gmail.com", "name": "Mario", "picture": "http://x"}
        token = create_session_token(user, SECRET)
        decoded = decode_session_token(token, SECRET)
        assert decoded["email"] == "mario@gmail.com"

    def test_wrong_secret_returns_none(self):
        from auth.session import create_session_token, decode_session_token
        token = create_session_token({"email": "x@x.com"}, SECRET)
        assert decode_session_token(token, "wrong-secret") is None

    def test_tampered_token_returns_none(self):
        from auth.session import decode_session_token
        assert decode_session_token("not.a.valid.token", SECRET) is None

    def test_token_is_string(self):
        from auth.session import create_session_token
        token = create_session_token({"email": "x@x.com"}, SECRET)
        assert isinstance(token, str)


class TestRequireAuth:
    def test_returns_401_without_cookie(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("LOCAL_DB", db)
        monkeypatch.setenv("SECRET_KEY", SECRET)
        import config, importlib
        importlib.reload(config)
        from database.models import init_db
        init_db(db)
        from main import app
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/api/photos")
        assert resp.status_code == 401

    def test_returns_200_with_valid_cookie(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("LOCAL_DB", db)
        monkeypatch.setenv("SECRET_KEY", SECRET)
        import config, importlib
        importlib.reload(config)
        from database.models import init_db
        init_db(db)
        from main import app
        from auth.session import create_session_token
        token = create_session_token({"email": "mario@gmail.com", "name": "Mario", "picture": ""}, SECRET)
        c = TestClient(app, raise_server_exceptions=False, cookies={"photo_ai_session": token})
        resp = c.get("/api/photos")
        assert resp.status_code == 200

    def test_returns_403_if_email_not_in_whitelist(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("LOCAL_DB", db)
        monkeypatch.setenv("SECRET_KEY", SECRET)
        import config, importlib
        importlib.reload(config)
        from database.models import init_db
        init_db(db)
        from main import app
        # Set a whitelist that does NOT include test@test.com
        from auth.whitelist import load_whitelist
        emails_file = tmp_path / "emails.txt"
        emails_file.write_text("other@gmail.com\n")
        app.state.whitelist = load_whitelist(str(emails_file))
        from auth.session import create_session_token
        token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, SECRET)
        c = TestClient(app, raise_server_exceptions=False, cookies={"photo_ai_session": token})
        resp = c.get("/api/photos")
        assert resp.status_code == 403
