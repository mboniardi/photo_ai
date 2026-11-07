"""
Test della vecchia rotta JSON /api/takeout/import.

Vale la stessa precedenza dell'import di un album: `exif`, `manual` e
`corrected` sono dati certi o corretti a mano e un import non li disfa mai,
nemmeno con force. Force puo' solo sostituire un'ipotesi dell'AI o un Takeout
precedente.
"""
import importlib
import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

import config


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "api.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("TAKEOUT_JSON_PATH", str(tmp_path / "takeout_json"))
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    os.makedirs(tmp_path / "takeout_json")
    from main import app
    monkeypatch.setattr(app.state, "whitelist", None, raising=False)
    from auth.session import create_session_token
    token = create_session_token(
        {"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token}), db


def _json_takeout(nome="IMG_1.jpg", lat=45.4642, lon=9.19):
    percorso = os.path.join(config.TAKEOUT_JSON_PATH, nome + ".json")
    with open(percorso, "w", encoding="utf-8") as fh:
        json.dump({"title": nome, "geoData": {"latitude": lat, "longitude": lon}}, fh)


def _foto(db, nome="IMG_1.jpg", lat=None, lon=None, src=None):
    from database.photos import insert_photo, update_photo
    pid = insert_photo(db, file_path=f"/mnt/nas/{nome}", folder_path="/mnt/nas",
                       filename=nome)
    if lat is not None or src is not None:
        update_photo(db, pid, latitude=lat, longitude=lon, location_source=src)
    return pid


def _riga(db, pid):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM photos WHERE id = ?", (pid,)).fetchone()
    finally:
        conn.close()


@pytest.mark.parametrize("sorgente", ["manual", "corrected", "exif"])
@pytest.mark.parametrize("force", [False, True])
def test_non_sovrascrive_mai_una_posizione_certa(client, sorgente, force):
    """L'anti-obiettivo numero uno: una posizione corretta a mano resta."""
    c, db = client
    pid = _foto(db, lat=45.0, lon=7.0, src=sorgente)
    _json_takeout()
    resp = c.post("/api/takeout/import", json={"force": force})
    assert resp.status_code == 200, resp.text
    riga = _riga(db, pid)
    assert riga["latitude"] == pytest.approx(45.0)
    assert riga["longitude"] == pytest.approx(7.0)
    assert riga["location_source"] == sorgente
    assert resp.json()["updated"] == 0
    assert resp.json()["skipped_protected"] == 1


@pytest.mark.parametrize("sorgente", ["ai", "takeout"])
def test_con_force_sostituisce_un_ipotesi_o_un_takeout_precedente(client, sorgente):
    c, db = client
    pid = _foto(db, lat=10.0, lon=10.0, src=sorgente)
    _json_takeout()
    resp = c.post("/api/takeout/import", json={"force": True})
    riga = _riga(db, pid)
    assert riga["latitude"] == pytest.approx(45.4642)
    assert riga["location_source"] == "takeout"
    assert resp.json()["updated"] == 1


@pytest.mark.parametrize("sorgente", ["ai", "takeout"])
def test_senza_force_non_tocca_chi_ha_gia_delle_coordinate(client, sorgente):
    c, db = client
    pid = _foto(db, lat=10.0, lon=10.0, src=sorgente)
    _json_takeout()
    resp = c.post("/api/takeout/import", json={"force": False})
    assert _riga(db, pid)["latitude"] == pytest.approx(10.0)
    assert resp.json()["skipped_already_has"] == 1


def test_riempie_chi_non_ha_coordinate(client):
    c, db = client
    pid = _foto(db)
    _json_takeout()
    resp = c.post("/api/takeout/import", json={"force": False})
    assert _riga(db, pid)["latitude"] == pytest.approx(45.4642)
    assert _riga(db, pid)["location_source"] == "takeout"
    assert resp.json()["updated"] == 1


def test_la_spunta_force_nella_spa_e_spenta_di_default():
    """
    Era accesa: un import JSON sovrascriveva qualunque coordinata, comprese
    quelle corrette a mano, da una casella gia' spuntata.
    """
    percorso = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "static", "index.html")
    with open(percorso, encoding="utf-8") as fh:
        sorgente = fh.read()
    assert "const takeoutForce = ref(false);" in sorgente
    assert "const takeoutForce = ref(true);" not in sorgente
