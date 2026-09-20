"""Test per api/folders.py."""
import os
import pytest
from fastapi.testclient import TestClient
from PIL import Image


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
    from auth.session import create_session_token
    token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token}), tmp_path


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


def _segna_analizzata(db, file_path):
    from database.photos import get_photo_id_by_path, update_photo
    pid = get_photo_id_by_path(db, file_path)
    update_photo(db, pid, analyzed_at="2026-01-01T00:00:00", description="gia' descritta")
    return pid


class TestAutoAnalyzeNonRifaIlGiaFatto:
    """L'analisi AI si paga: aggiungere una cartella non deve rianalizzare
    le foto che hanno gia' una descrizione."""

    def test_scan_accoda_solo_le_non_analizzate(self, client, tmp_path):
        import config
        c, tmp = client
        d = make_photo_dir(tmp)
        c.post("/api/folders/scan", json={"folder_path": d})       # senza auto_analyze
        _segna_analizzata(config.LOCAL_DB, os.path.join(d, "a.jpg"))
        r = c.post("/api/folders/scan", json={"folder_path": d, "auto_analyze": 1})
        assert r.json()["queued"] == 1                              # solo b.jpg
        assert c.get("/api/queue/status").json()["pending"] == 1

    def test_scan_senza_auto_analyze_non_accoda_nulla(self, client, tmp_path):
        c, tmp = client
        d = make_photo_dir(tmp)
        r = c.post("/api/folders/scan", json={"folder_path": d, "auto_analyze": 0})
        assert r.json()["queued"] == 0
        assert c.get("/api/queue/status").json()["pending"] == 0


class TestRescanRispettaAutoAnalyze:
    """L'etichetta dice 'Auto-analyze new photos': finora il flag veniva letto
    solo in aggiunta, mai piu' dopo, quindi le foto nuove non partivano."""

    def test_rescan_accoda_le_foto_nuove_se_la_cartella_e_marcata(self, client, tmp_path):
        from PIL import Image
        import config
        c, tmp = client
        d = make_photo_dir(tmp)
        c.post("/api/folders/scan", json={"folder_path": d, "auto_analyze": 1})
        c.delete("/api/queue/clear")
        _segna_analizzata(config.LOCAL_DB, os.path.join(d, "a.jpg"))
        _segna_analizzata(config.LOCAL_DB, os.path.join(d, "b.jpg"))

        Image.new("RGB", (60, 40)).save(os.path.join(d, "nuova.jpg"), "JPEG")
        r = c.post("/api/folders/rescan", json={"folder_path": d})
        assert r.json()["queued"] == 1
        assert c.get("/api/queue/status").json()["pending"] == 1

    def test_rescan_non_accoda_se_la_cartella_non_e_marcata(self, client, tmp_path):
        from PIL import Image
        c, tmp = client
        d = make_photo_dir(tmp)
        c.post("/api/folders/scan", json={"folder_path": d, "auto_analyze": 0})
        Image.new("RGB", (60, 40)).save(os.path.join(d, "nuova.jpg"), "JPEG")
        r = c.post("/api/folders/rescan", json={"folder_path": d})
        assert r.json()["queued"] == 0
        assert c.get("/api/queue/status").json()["pending"] == 0

    def test_rescan_non_ripesca_il_pregresso_mai_analizzato(self, client, tmp_path):
        """Il flag promette le foto NUOVE. Una cartella lasciata apposta senza
        analisi non deve mettersi a spendere solo perche' la si rescansiona."""
        from PIL import Image
        c, tmp = client
        d = make_photo_dir(tmp)
        c.post("/api/folders/scan", json={"folder_path": d, "auto_analyze": 1})
        c.delete("/api/queue/clear")          # a.jpg e b.jpg restano non analizzate
        Image.new("RGB", (60, 40)).save(os.path.join(d, "nuova.jpg"), "JPEG")
        r = c.post("/api/folders/rescan", json={"folder_path": d})
        assert r.json()["queued"] == 1        # solo nuova.jpg, non a.jpg e b.jpg
