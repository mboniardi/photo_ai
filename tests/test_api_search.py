"""Test per api/search.py."""
import json
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_analyzed_photo(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo, update_photo
    init_db(db)
    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (100, 80)).save(photo_path, "JPEG")
    pid = insert_photo(db, file_path=photo_path, folder_path=str(tmp_path),
                       filename="test.jpg", format="jpg", file_size=1000,
                       width=100, height=80)
    update_photo(db, pid, overall_score=8.0,
                 embedding=json.dumps([1.0, 0.0, 0.0]),
                 analyzed_at="2023-06-01T10:00:00")
    from main import app
    from auth.session import create_session_token
    token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token}), pid


class FakeEngine:
    async def embed(self, text: str) -> list:
        return [1.0, 0.0, 0.0]


def _async_fake_engine():
    async def _inner():
        return FakeEngine()
    return _inner


class TestSearchPhotos:
    def test_returns_200(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        resp = c.post("/api/search", json={"query": "paesaggi"})
        assert resp.status_code == 200

    def test_returns_list(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        data = c.post("/api/search", json={"query": "paesaggi"}).json()
        assert isinstance(data, list)

    def test_result_has_similarity(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        data = c.post("/api/search", json={"query": "paesaggi"}).json()
        assert len(data) == 1
        assert "similarity" in data[0]

    def test_empty_query_returns_400(self, client_with_analyzed_photo, monkeypatch):
        c, _ = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        resp = c.post("/api/search", json={"query": "   "})
        assert resp.status_code == 400

    def test_with_orientation_filter(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        data = c.post("/api/search",
                      json={"query": "paesaggi", "orientation": "horizontal"}).json()
        assert len(data) == 1

    def test_vertical_filter_excludes_photo(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        # Photo is 100x80 (horizontal); vertical filter should return 0
        data = c.post("/api/search",
                      json={"query": "paesaggi", "orientation": "vertical"}).json()
        assert len(data) == 0
