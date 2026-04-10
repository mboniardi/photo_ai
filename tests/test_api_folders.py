"""Test per api/folders.py."""
import os
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    return TestClient(app), tmp_path


def make_photo_dir(tmp_path):
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    Image.new("RGB", (100, 80)).save(str(photo_dir / "a.jpg"), "JPEG")
    Image.new("RGB", (100, 80)).save(str(photo_dir / "b.jpg"), "JPEG")
    return str(photo_dir)


class TestGetFolders:
    def test_empty_list(self, client):
        c, _ = client
        resp = c.get("/api/folders")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_added_folder(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        folders = c.get("/api/folders").json()
        assert len(folders) == 1
        assert folders[0]["folder_path"] == photo_dir


class TestScanFolder:
    def test_returns_scan_result(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        resp = c.post("/api/folders/scan", json={"folder_path": photo_dir})
        assert resp.status_code == 200
        data = resp.json()
        assert data["new"] == 2

    def test_folder_created_in_db(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        folders = c.get("/api/folders").json()
        assert any(f["folder_path"] == photo_dir for f in folders)

    def test_nonexistent_path_returns_400(self, client):
        c, _ = client
        resp = c.post("/api/folders/scan",
                      json={"folder_path": "/nonexistent/path/xyz"})
        assert resp.status_code == 400

    def test_rescan_updates_counts(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        # Aggiungi una nuova foto
        Image.new("RGB", (50, 50)).save(str(tmp_path / "photos" / "c.jpg"), "JPEG")
        resp = c.post(f"/api/folders/rescan",
                      json={"folder_path": photo_dir})
        assert resp.status_code == 200
        data = resp.json()
        assert data["new"] == 1


class TestPutFolder:
    def test_update_display_name(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        resp = c.put("/api/folders/meta",
                     json={"folder_path": photo_dir,
                           "display_name": "Le Mie Foto"})
        assert resp.status_code == 200
        folders = c.get("/api/folders").json()
        assert folders[0]["display_name"] == "Le Mie Foto"


class TestDeleteFolder:
    def test_removes_from_list(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        resp = c.request("DELETE", "/api/folders",
                         json={"folder_path": photo_dir})
        assert resp.status_code == 200
        assert c.get("/api/folders").json() == []
