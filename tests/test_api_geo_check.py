"""Test per api/geo_check.py."""
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_geo(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo, update_photo
    init_db(db)

    def aggiungi(nome, ora, lat, lon, src="ai", loc="x"):
        p = str(tmp_path / nome)
        Image.new("RGB", (10, 10)).save(p, "JPEG")
        pid = insert_photo(db, file_path=p, folder_path=str(tmp_path),
                           filename=nome, format="jpg", file_size=10,
                           width=10, height=10)
        update_photo(db, pid, exif_date=f"2026-04-01T{ora}:00", latitude=lat,
                     longitude=lon, location_name=loc, location_source=src,
                     description="vecchia", analyzed_at="2026-04-02T00:00:00",
                     embedding="[0.1]")
        return pid

    ids = {
        "prima": aggiungi("a.jpg", "10:00", 25.70, 32.64, loc="Luxor"),
        "sospetta": aggiungi("b.jpg", "10:05", 45.07, 7.68, loc="Torino"),
        "dopo": aggiungi("c.jpg", "10:10", 25.71, 32.65, loc="Karnak"),
    }
    from main import app
    from auth.session import create_session_token
    token = create_session_token({"email": "t@t.com", "name": "T", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token}), ids, db


class TestGeoCheckList:
    def test_risponde_200(self, client_geo):
        c, _, _ = client_geo
        assert c.get("/api/geo-check").status_code == 200

    def test_trova_la_foto_fuori_scala(self, client_geo):
        c, ids, _ = client_geo
        d = c.get("/api/geo-check").json()
        assert d["segnalate"] == 1
        assert len(d["casi"]) == 1
        assert d["casi"][0]["photo_ids"] == [ids["sospetta"]]

    def test_riporta_attuale_e_proposta(self, client_geo):
        c, _, _ = client_geo
        caso = c.get("/api/geo-check").json()["casi"][0]
        assert caso["attuale"]["location_name"] == "Torino"
        assert caso["proposta"]["location_name"] == "Luxor"
        assert caso["proposta"]["latitude"] == pytest.approx(25.70)
        assert caso["distanza_km"] > 2000

    def test_conta_le_foto_esaminate(self, client_geo):
        c, _, _ = client_geo
        assert c.get("/api/geo-check").json()["esaminate"] == 3

    def test_richiede_autenticazione(self, client_geo):
        c, _, _ = client_geo
        anon = TestClient(c.app)
        assert anon.get("/api/geo-check").status_code == 401
