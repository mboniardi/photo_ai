"""Test per api/queue.py."""
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_photo(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo
    init_db(db)
    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (100, 100)).save(photo_path, "JPEG")
    pid = insert_photo(db,
                       file_path=photo_path,
                       folder_path=str(tmp_path),
                       filename="test.jpg",
                       format="jpg",
                       file_size=1000,
                       width=100,
                       height=100)
    from main import app
    return TestClient(app), pid


class TestQueueStatus:
    def test_returns_200(self, client_with_photo):
        c, _ = client_with_photo
        resp = c.get("/api/queue/status")
        assert resp.status_code == 200

    def test_has_required_fields(self, client_with_photo):
        c, _ = client_with_photo
        data = c.get("/api/queue/status").json()
        for field in ["pending", "processing", "done", "error", "is_running"]:
            assert field in data, f"Campo mancante: {field}"


class TestAddToQueue:
    def test_add_photo(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/queue/add",
                      json={"photo_ids": [pid], "priority": 5})
        assert resp.status_code == 200

    def test_queue_count_increases(self, client_with_photo):
        c, pid = client_with_photo
        c.post("/api/queue/add", json={"photo_ids": [pid], "priority": 5})
        data = c.get("/api/queue/status").json()
        assert data["pending"] == 1

    def test_add_folder(self, client_with_photo, tmp_path, monkeypatch):
        c, pid = client_with_photo
        import config
        resp = c.post("/api/queue/add-folder",
                      json={"folder_path": str(tmp_path)})
        assert resp.status_code == 200


class TestPauseResume:
    def test_pause_returns_200(self, client_with_photo):
        c, _ = client_with_photo
        assert c.post("/api/queue/pause").status_code == 200

    def test_resume_returns_200(self, client_with_photo):
        c, _ = client_with_photo
        assert c.post("/api/queue/resume").status_code == 200


class TestDeleteQueueItem:
    def test_removes_pending_item(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/queue/add",
                      json={"photo_ids": [pid], "priority": 5})
        # Recupera l'id dalla coda tramite status (semplificato: usiamo DB diretto)
        import config
        from database.queue import get_next_pending
        item = get_next_pending(config.LOCAL_DB)
        del_resp = c.delete(f"/api/queue/{item['id']}")
        assert del_resp.status_code == 200
        data = c.get("/api/queue/status").json()
        assert data["pending"] == 0
