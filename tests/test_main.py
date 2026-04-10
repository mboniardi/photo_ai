"""Test per main.py — /health e startup."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient con DB temporaneo."""
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    return TestClient(app)


class TestHealthEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_has_status_field(self, client):
        data = client.get("/health").json()
        assert "status" in data

    def test_has_version(self, client):
        data = client.get("/health").json()
        assert "version" in data

    def test_has_uptime(self, client):
        data = client.get("/health").json()
        assert "uptime_s" in data
        assert isinstance(data["uptime_s"], (int, float))


class TestAllRoutersRegistered:
    def test_settings_route_exists(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code != 404

    def test_folders_route_exists(self, client):
        resp = client.get("/api/folders")
        assert resp.status_code != 404

    def test_photos_route_exists(self, client):
        resp = client.get("/api/photos")
        assert resp.status_code != 404

    def test_queue_route_exists(self, client):
        resp = client.get("/api/queue/status")
        assert resp.status_code != 404
