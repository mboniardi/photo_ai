import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    app.state.whitelist = None
    from auth.session import create_session_token
    token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token})


@pytest.fixture
def app_setup(tmp_path, monkeypatch):
    """Shared app setup without session cookie for auth tests."""
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    app.state.whitelist = None
    return app


class TestBrowseEndpoint:
    def test_lists_subdirs(self, tmp_path, client):
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        (tmp_path / "file.txt").write_text("hello")
        resp = client.get(f"/api/browse?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.json()
        names = [d["name"] for d in data["dirs"]]
        assert "alpha" in names
        assert "beta" in names
        assert "file.txt" not in names

    def test_excludes_hidden_dirs(self, tmp_path, client):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()
        resp = client.get(f"/api/browse?path={tmp_path}")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()["dirs"]]
        assert ".hidden" not in names
        assert "visible" in names

    def test_dirs_sorted_alphabetically(self, tmp_path, client):
        (tmp_path / "zebra").mkdir()
        (tmp_path / "apple").mkdir()
        (tmp_path / "mango").mkdir()
        resp = client.get(f"/api/browse?path={tmp_path}")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()["dirs"]]
        assert names == ["apple", "mango", "zebra"]

    def test_parent_of_root_is_root(self, client):
        resp = client.get("/api/browse?path=/")
        assert resp.status_code == 200
        assert resp.json()["parent"] == "/"

    def test_invalid_path_returns_400(self, client):
        resp = client.get("/api/browse?path=/nonexistent/path/xyz")
        assert resp.status_code == 400

    def test_file_path_returns_400(self, tmp_path, client):
        f = tmp_path / "afile.txt"
        f.write_text("content")
        resp = client.get(f"/api/browse?path={f}")
        assert resp.status_code == 400

    def test_requires_auth(self, app_setup):
        c = TestClient(app_setup)
        resp = c.get("/api/browse?path=/")
        assert resp.status_code == 401

    def test_response_contains_path_and_parent(self, tmp_path, client):
        resp = client.get(f"/api/browse?path={tmp_path}")
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data
        assert "parent" in data
        assert "dirs" in data

    def test_dirs_contain_name_and_path(self, tmp_path, client):
        sub = tmp_path / "subdir"
        sub.mkdir()
        resp = client.get(f"/api/browse?path={tmp_path}")
        assert resp.status_code == 200
        dirs = resp.json()["dirs"]
        assert len(dirs) == 1
        assert dirs[0]["name"] == "subdir"
        assert dirs[0]["path"] == str(sub)
