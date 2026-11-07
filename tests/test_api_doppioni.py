"""Test per le rotte /api/takeout/doppioni."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_doppioni(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    # Lo store dei derivati va isolato: la risoluzione cancella file.
    monkeypatch.setenv("DERIVATI_PATH", str(tmp_path / "derivati"))
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo
    from database import get_db
    init_db(db)
    ids = []
    for nome, cartella in (("g.jpg", "google:/Vacanza"), ("n.jpg", "/mnt/nas")):
        ids.append(insert_photo(db, file_path=f"{cartella}/{nome}", folder_path=cartella,
                                filename=nome, format="jpg", file_size=1,
                                width=10, height=10))
    with get_db(db) as conn:
        sid = conn.execute(
            "INSERT INTO doppioni_sospetti (photo_id_google, photo_id_nas, motivo, distanza)"
            " VALUES (?, ?, 'phash', 4)", tuple(ids)).lastrowid
    from main import app
    from auth.session import create_session_token
    token = create_session_token({"email": "t@t.com", "name": "T", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token}), sid, ids, db


def test_get_elenca_i_sospetti(client_doppioni):
    c, sid, ids, _ = client_doppioni
    r = c.get("/api/takeout/doppioni")
    assert r.status_code == 200
    dati = r.json()
    assert [e["id"] for e in dati] == [sid]
    assert dati[0]["motivo"] == "phash" and dati[0]["distanza"] == 4
    assert dati[0]["photo_id_google"] == ids[0]


def test_post_stessa_foto_false_respinge(client_doppioni):
    c, sid, ids, db = client_doppioni
    r = c.post(f"/api/takeout/doppioni/{sid}", json={"stessa_foto": False})
    assert r.status_code == 200
    assert r.json()["stato"] == "respinto"
    assert c.get("/api/takeout/doppioni").json() == []


def test_post_stessa_foto_true_cancella_la_riga_google(client_doppioni):
    c, sid, ids, db = client_doppioni
    r = c.post(f"/api/takeout/doppioni/{sid}", json={"stessa_foto": True})
    assert r.status_code == 200
    from database.photos import get_photo_by_id
    assert get_photo_by_id(db, ids[0]) is None
    assert get_photo_by_id(db, ids[1]) is not None


def test_post_due_volte_da_409(client_doppioni):
    c, sid, ids, _ = client_doppioni
    assert c.post(f"/api/takeout/doppioni/{sid}", json={"stessa_foto": False}).status_code == 200
    assert c.post(f"/api/takeout/doppioni/{sid}", json={"stessa_foto": True}).status_code == 409


def test_post_inesistente_da_404(client_doppioni):
    c, *_ = client_doppioni
    assert c.post("/api/takeout/doppioni/999", json={"stessa_foto": True}).status_code == 404


def test_post_senza_corpo_valido_da_422(client_doppioni):
    c, sid, *_ = client_doppioni
    assert c.post(f"/api/takeout/doppioni/{sid}", json={}).status_code == 422
