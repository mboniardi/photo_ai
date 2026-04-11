"""Test per api/photos.py."""
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_photo(tmp_path, monkeypatch):
    """Client con una foto già inserita nel DB."""
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo
    init_db(db)

    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (800, 600), (100, 150, 200)).save(photo_path, "JPEG")
    pid = insert_photo(db,
                       file_path=photo_path,
                       folder_path=str(tmp_path),
                       filename="test.jpg",
                       format="jpg",
                       file_size=50000,
                       width=800,
                       height=600)
    from main import app
    from auth.session import create_session_token
    token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token}), pid, photo_path


class TestListPhotos:
    def test_returns_200(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get("/api/photos")
        assert resp.status_code == 200

    def test_returns_list(self, client_with_photo):
        c, pid, _ = client_with_photo
        data = c.get("/api/photos").json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_filter_by_folder(self, client_with_photo, tmp_path):
        c, pid, photo_path = client_with_photo
        resp = c.get(f"/api/photos?folder_path={tmp_path}")
        assert len(resp.json()) == 1

    def test_pagination(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get("/api/photos?limit=10&offset=0")
        assert resp.status_code == 200


class TestGetPhoto:
    def test_returns_photo(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.jpg"

    def test_404_for_missing(self, client_with_photo):
        c, _, _ = client_with_photo
        resp = c.get("/api/photos/99999")
        assert resp.status_code == 404


class TestUpdatePhoto:
    def test_set_favorite(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.put(f"/api/photos/{pid}", json={"is_favorite": 1})
        assert resp.status_code == 200
        data = c.get(f"/api/photos/{pid}").json()
        assert data["is_favorite"] == 1

    def test_set_user_description(self, client_with_photo):
        c, pid, _ = client_with_photo
        c.put(f"/api/photos/{pid}",
              json={"user_description": "La mia foto preferita"})
        data = c.get(f"/api/photos/{pid}").json()
        assert data["user_description"] == "La mia foto preferita"

    def test_unfavorite_with_zero(self, client_with_photo):
        c, pid, _ = client_with_photo
        c.put(f"/api/photos/{pid}", json={"is_favorite": 1})
        c.put(f"/api/photos/{pid}", json={"is_favorite": 0})
        data = c.get(f"/api/photos/{pid}").json()
        assert data["is_favorite"] == 0


class TestThumbnail:
    def test_returns_jpeg_bytes(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}/thumbnail")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"

    def test_thumbnail_is_valid_image(self, client_with_photo):
        import io
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}/thumbnail")
        img = Image.open(io.BytesIO(resp.content))
        assert max(img.size) <= 400

    def test_thumbnail_has_cache_control(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}/thumbnail")
        assert "cache-control" in resp.headers


class TestImageEndpoint:
    def test_returns_image(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}/image")
        assert resp.status_code == 200
        assert "image" in resp.headers["content-type"]
