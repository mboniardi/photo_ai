"""Test per main.py — /health e startup."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient con DB temporaneo e API key fake per il worker."""
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("APP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("REMOTE_DB", str(tmp_path / "remote.db"))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-32-chars-minimum!")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    # Context manager garantisce che on_startup/on_shutdown vengano eseguiti
    with TestClient(app) as c:
        yield c


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


class TestWorkerStartup:
    def test_worker_is_running_after_startup(self, client):
        """Il QueueWorker deve essere avviato all'avvio dell'app."""
        import api.queue
        assert api.queue._worker is not None, "Worker non inizializzato — set_worker() mai chiamato"
        assert api.queue._worker.is_running, "Worker inizializzato ma non avviato"

