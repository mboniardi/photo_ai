"""Test per api/export.py."""
import io
import zipfile
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
    pid = insert_photo(db, file_path=photo_path, folder_path=str(tmp_path),
                       filename="test.jpg", format="jpg", file_size=1000,
                       width=100, height=100)
    from main import app
    return TestClient(app), pid


class TestExportZip:
    def test_returns_200(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        assert resp.status_code == 200

    def test_content_type_is_zip(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        assert resp.headers["content-type"] == "application/zip"

    def test_filename_has_timestamp_prefix(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        cd = resp.headers["content-disposition"]
        assert "foto_selezione_" in cd
        assert ".zip" in cd

    def test_zip_contains_photo_file(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert "test.jpg" in zf.namelist()

    def test_empty_photo_ids_returns_400(self, client_with_photo):
        c, _ = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": []})
        assert resp.status_code == 400

    def test_invalid_photo_id_returns_404(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [99999]})
        assert resp.status_code == 404

    def test_multiple_photos_in_zip(self, client_with_photo, tmp_path, monkeypatch):
        c, pid = client_with_photo
        import config
        from database.photos import insert_photo
        photo2 = str(tmp_path / "second.jpg")
        Image.new("RGB", (50, 50)).save(photo2, "JPEG")
        pid2 = insert_photo(config.LOCAL_DB, file_path=photo2,
                            folder_path=str(tmp_path), filename="second.jpg",
                            format="jpg", file_size=500, width=50, height=50)
        resp = c.post("/api/export/zip", json={"photo_ids": [pid, pid2]})
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert len(zf.namelist()) == 2
