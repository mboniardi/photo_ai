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


class TestGeoCheckAccept:
    def _accetta(self, c, ids):
        return c.post("/api/geo-check/accept", json={
            "photo_ids": [ids["sospetta"]],
            "latitude": 25.70, "longitude": 32.64,
            "location_name": "Luxor",
        })

    def test_scrive_la_posizione_proposta(self, client_geo):
        c, ids, db = client_geo
        assert self._accetta(c, ids).status_code == 200
        from database.photos import get_photo_by_id
        p = get_photo_by_id(db, ids["sospetta"])
        assert p["latitude"] == pytest.approx(25.70)
        assert p["location_name"] == "Luxor"
        assert p["location_source"] == "corrected"

    def test_cancella_descrizione_embedding_e_data_di_analisi(self, client_geo):
        c, ids, db = client_geo
        self._accetta(c, ids)
        from database.photos import get_photo_by_id
        p = get_photo_by_id(db, ids["sospetta"])
        assert p["description"] is None
        assert p["embedding"] is None
        assert p["analyzed_at"] is None

    def test_rimette_la_foto_in_coda(self, client_geo):
        c, ids, db = client_geo
        r = self._accetta(c, ids)
        assert r.json()["in_coda"] == 1
        from database.queue import get_queue_counts
        assert get_queue_counts(db).get("pending", 0) == 1

    def test_il_caso_sparisce_dall_elenco(self, client_geo):
        c, ids, _ = client_geo
        self._accetta(c, ids)
        assert c.get("/api/geo-check").json()["casi"] == []

    def test_rifiuta_coordinate_impossibili(self, client_geo):
        c, ids, _ = client_geo
        r = c.post("/api/geo-check/accept", json={
            "photo_ids": [ids["sospetta"]],
            "latitude": 120.0, "longitude": 32.64, "location_name": "x"})
        assert r.status_code == 422

    def test_rifiuta_una_lista_vuota(self, client_geo):
        c, _, _ = client_geo
        r = c.post("/api/geo-check/accept", json={
            "photo_ids": [], "latitude": 25.0, "longitude": 32.0,
            "location_name": "x"})
        assert r.status_code == 422

    def test_richiede_autenticazione(self, client_geo):
        c, ids, _ = client_geo
        anon = TestClient(c.app)
        r = anon.post("/api/geo-check/accept", json={
            "photo_ids": [ids["sospetta"]],
            "latitude": 25.70, "longitude": 32.64, "location_name": "Luxor"})
        assert r.status_code == 401

    def test_salta_un_id_inesistente_e_corregge_gli_altri(self, client_geo):
        c, ids, db = client_geo
        id_inesistente = 999999
        r = c.post("/api/geo-check/accept", json={
            "photo_ids": [ids["sospetta"], id_inesistente],
            "latitude": 25.70, "longitude": 32.64, "location_name": "Luxor"})
        assert r.status_code == 200
        body = r.json()
        assert body["aggiornate"] == 1
        assert body["in_coda"] == 1
        assert body["mancanti"] == [id_inesistente]
        from database.photos import get_photo_by_id
        p = get_photo_by_id(db, ids["sospetta"])
        assert p["latitude"] == pytest.approx(25.70)
        assert p["location_source"] == "corrected"

    def test_solo_id_inesistenti_non_aggiorna_nulla(self, client_geo):
        c, _, db = client_geo
        id_inesistente_1, id_inesistente_2 = 999998, 999999
        r = c.post("/api/geo-check/accept", json={
            "photo_ids": [id_inesistente_1, id_inesistente_2],
            "latitude": 25.70, "longitude": 32.64, "location_name": "Luxor"})
        assert r.status_code == 200
        body = r.json()
        assert body["aggiornate"] == 0
        assert sorted(body["mancanti"]) == sorted([id_inesistente_1, id_inesistente_2])
        from database.queue import get_queue_counts
        assert get_queue_counts(db).get("pending", 0) == 0


class TestGeoCheckOrdinamento:
    def test_i_casi_sono_ordinati_per_distanza_decrescente(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("LOCAL_DB", db)
        monkeypatch.setenv("SECRET_KEY", "test-secret")
        import config, importlib
        importlib.reload(config)
        from database.models import init_db
        from database.photos import insert_photo, update_photo
        init_db(db)

        def aggiungi(nome, ora, lat, lon, loc="x"):
            p = str(tmp_path / nome)
            Image.new("RGB", (10, 10)).save(p, "JPEG")
            pid = insert_photo(db, file_path=p, folder_path=str(tmp_path),
                               filename=nome, format="jpg", file_size=10,
                               width=10, height=10)
            update_photo(db, pid, exif_date=f"2026-04-01T{ora}:00", latitude=lat,
                         longitude=lon, location_name=loc, location_source="ai",
                         description="vecchia", analyzed_at="2026-04-02T00:00:00",
                         embedding="[0.1]")
            return pid

        # Gruppo 1: sequenza mattutina, foto sospetta a ~700 km dalle vicine.
        aggiungi("g1a.jpg", "08:00", 45.07, 7.68, loc="Torino")
        vicino_id = aggiungi("g1b.jpg", "08:05", 41.3851, 2.1734, loc="Barcellona")
        aggiungi("g1c.jpg", "08:10", 45.08, 7.69, loc="Torino")

        # Gruppo 2: sequenza serale, ore dopo, foto sospetta a ~10800 km.
        aggiungi("g2a.jpg", "20:00", 35.6762, 139.6503, loc="Tokyo")
        lontano_id = aggiungi("g2b.jpg", "20:05", 40.7128, -74.0060, loc="New York")
        aggiungi("g2c.jpg", "20:10", 35.6763, 139.6504, loc="Tokyo")

        from main import app
        from auth.session import create_session_token
        token = create_session_token({"email": "t@t.com", "name": "T", "picture": ""}, "test-secret")
        c = TestClient(app, cookies={"photo_ai_session": token})

        d = c.get("/api/geo-check").json()
        assert len(d["casi"]) == 2
        assert d["casi"][0]["photo_ids"] == [lontano_id]
        assert d["casi"][1]["photo_ids"] == [vicino_id]
        assert d["casi"][0]["distanza_km"] > d["casi"][1]["distanza_km"]


class TestGeoCheckConferma:
    """'E' gia' giusta': il caso sparisce per sempre e non costa nulla."""

    def test_marca_manual_e_il_caso_sparisce(self, client_geo):
        c, ids, db = client_geo
        r = c.post("/api/geo-check/confirm", json={"photo_ids": [ids["sospetta"]]})
        assert r.status_code == 200 and r.json()["confermate"] == 1
        from database.photos import get_photo_by_id
        assert get_photo_by_id(db, ids["sospetta"])["location_source"] == "manual"
        # manual e' fra le origini affidabili: il rilevatore non la discute piu'
        assert c.get("/api/geo-check").json()["casi"] == []

    def test_non_azzera_la_descrizione_e_non_accoda(self, client_geo):
        c, ids, db = client_geo
        c.post("/api/geo-check/confirm", json={"photo_ids": [ids["sospetta"]]})
        from database.photos import get_photo_by_id
        from database.queue import get_queue_counts
        assert get_photo_by_id(db, ids["sospetta"])["description"] == "vecchia"
        assert get_queue_counts(db)["pending"] == 0

    def test_rifiuta_lista_vuota(self, client_geo):
        c, _, _ = client_geo
        assert c.post("/api/geo-check/confirm", json={"photo_ids": []}).status_code == 422

    def test_richiede_autenticazione(self, client_geo):
        c, ids, _ = client_geo
        anon = TestClient(c.app)
        assert anon.post("/api/geo-check/confirm",
                         json={"photo_ids": [ids["sospetta"]]}).status_code == 401
