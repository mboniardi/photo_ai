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


class TestUpdatePhotoLocation:
    def test_set_location_with_source(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.put(f"/api/photos/{pid}", json={
            "latitude": 30.0444,
            "longitude": 31.2357,
            "location_name": "Cairo, Egypt",
            "location_source": "manual",
        })
        assert resp.status_code == 200
        data = c.get(f"/api/photos/{pid}").json()
        assert data["latitude"] == pytest.approx(30.0444, abs=1e-4)
        assert data["longitude"] == pytest.approx(31.2357, abs=1e-4)
        assert data["location_name"] == "Cairo, Egypt"
        assert data["location_source"] == "manual"

    def test_location_source_not_required(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.put(f"/api/photos/{pid}", json={
            "latitude": 41.9028,
            "longitude": 12.4964,
            "location_name": "Roma, Italia",
        })
        assert resp.status_code == 200
        data = c.get(f"/api/photos/{pid}").json()
        assert data["location_source"] is None


class TestThumbnailConcurrencyLimit:
    """Una griglia da 100 foto chiede 100 miniature insieme. Ogni decodifica di
    uno scan da 6608x4128 occupa ~82 MB: senza un tetto, il pool di thread di
    uvicorn ne avvia decine e il container viene ucciso dall'OOM killer —
    successo davvero in produzione il 18 settembre 2026."""

    def test_a_limit_exists_and_is_bounded(self):
        from api.photos import _thumbnail_slots
        import config
        assert _thumbnail_slots._value == config.THUMBNAIL_MAX_CONCURRENT
        assert 1 <= config.THUMBNAIL_MAX_CONCURRENT <= 16

    def test_only_n_decodings_run_at_once(self, client_with_photo, monkeypatch):
        import threading, time
        import api.photos as m

        c, pid, _ = client_with_photo
        monkeypatch.setattr(m, "_thumbnail_slots", threading.Semaphore(2))

        insieme, picco, lock = 0, 0, threading.Lock()

        def lenta(path, size=400):
            nonlocal insieme, picco
            with lock:
                insieme += 1
                picco = max(picco, insieme)
            time.sleep(0.15)
            with lock:
                insieme -= 1
            return b"\xff\xd8\xff\xd9"

        monkeypatch.setattr(m, "generate_thumbnail", lenta)

        errori = []
        def chiedi():
            try:
                assert c.get(f"/api/photos/{pid}/thumbnail").status_code == 200
            except Exception as e:
                errori.append(e)

        ts = [threading.Thread(target=chiedi) for _ in range(8)]
        for x in ts: x.start()
        for x in ts: x.join(timeout=30)

        assert not errori, errori
        assert picco <= 2, f"decodifiche simultanee: {picco}, atteso al massimo 2"


def _altra_foto(db, tmp_path, nome, *, lat=None):
    from database.photos import insert_photo, update_photo
    pth = str(tmp_path / nome)
    Image.new("RGB", (60, 40)).save(pth, "JPEG")
    pid = insert_photo(db, file_path=pth, folder_path=str(tmp_path), filename=nome,
                       format="jpg", file_size=100, width=60, height=40)
    if lat is not None:
        update_photo(db, pid, latitude=lat, longitude=1.0, location_source="exif")
    return pid


class TestBulkLocation:
    """Assegnare la stessa posizione a un gruppo selezionato a mano, prima di
    mandarlo all'AI."""

    def _payload(self, ids, overwrite=False):
        return {"photo_ids": ids, "latitude": 37.0, "longitude": -110.0,
                "location_name": "Monument Valley", "overwrite": overwrite}

    def test_assegna_e_riporta_i_conteggi(self, client_with_photo):
        import config
        c, pid, _ = client_with_photo
        r = c.put("/api/photos/bulk-location", json=self._payload([pid]))
        assert r.status_code == 200
        assert r.json() == {"ok": True, "aggiornate": 1, "saltate": 0, "mancanti": []}
        assert c.get(f"/api/photos/{pid}").json()["location_source"] == "manual"

    def test_senza_overwrite_salta_chi_ha_gia_il_gps(self, client_with_photo, tmp_path):
        import config
        c, pid, _ = client_with_photo
        con_gps = _altra_foto(config.LOCAL_DB, tmp_path, "gps.jpg", lat=45.0)
        r = c.put("/api/photos/bulk-location", json=self._payload([pid, con_gps]))
        assert r.json()["aggiornate"] == 1 and r.json()["saltate"] == 1
        assert c.get(f"/api/photos/{con_gps}").json()["latitude"] == 45.0

    def test_con_overwrite_scrive_anche_su_quelle(self, client_with_photo, tmp_path):
        import config
        c, pid, _ = client_with_photo
        con_gps = _altra_foto(config.LOCAL_DB, tmp_path, "gps2.jpg", lat=45.0)
        r = c.put("/api/photos/bulk-location",
                  json=self._payload([pid, con_gps], overwrite=True))
        assert r.json()["aggiornate"] == 2
        assert c.get(f"/api/photos/{con_gps}").json()["latitude"] == 37.0

    def test_rifiuta_coordinate_impossibili(self, client_with_photo):
        c, pid, _ = client_with_photo
        r = c.put("/api/photos/bulk-location",
                  json={"photo_ids": [pid], "latitude": 99.0, "longitude": 0.0})
        assert r.status_code == 422

    def test_rifiuta_selezione_vuota(self, client_with_photo):
        c, _, _ = client_with_photo
        r = c.put("/api/photos/bulk-location",
                  json={"photo_ids": [], "latitude": 37.0, "longitude": -110.0})
        assert r.status_code == 422

    def test_richiede_autenticazione(self, client_with_photo):
        c, pid, _ = client_with_photo
        anon = TestClient(c.app)
        assert anon.put("/api/photos/bulk-location",
                        json=self._payload([pid])).status_code == 401

    def test_la_rotta_non_viene_scambiata_per_un_id(self, client_with_photo):
        """/{photo_id} intercetterebbe 'bulk-location' e proverebbe a leggerlo
        come numero: la rotta deve essere dichiarata prima."""
        c, pid, _ = client_with_photo
        assert c.put("/api/photos/bulk-location",
                     json=self._payload([pid])).status_code == 200


class TestPhotoIds:
    def test_ritorna_gli_id_e_quelli_gia_posizionati(self, client_with_photo, tmp_path):
        import config
        c, pid, _ = client_with_photo
        con_gps = _altra_foto(config.LOCAL_DB, tmp_path, "g3.jpg", lat=45.0)
        d = c.get("/api/photos/ids").json()
        assert sorted(d["ids"]) == sorted([pid, con_gps])
        assert d["con_posizione"] == [con_gps]

    def test_rispetta_i_filtri(self, client_with_photo, tmp_path):
        c, pid, _ = client_with_photo
        d = c.get("/api/photos/ids", params={"folder_path": "/inesistente"}).json()
        assert d["ids"] == []

    def test_richiede_autenticazione(self, client_with_photo):
        c, _, _ = client_with_photo
        assert TestClient(c.app).get("/api/photos/ids").status_code == 401


class TestFiltriDelleRotte:
    """I filtri del pannello devono arrivare fino al database: date, luogo,
    orientamento e coordinate erano nell'interfaccia e ignorati dalle rotte."""

    def _prepara(self, db, tmp_path):
        from database.photos import insert_photo, update_photo
        def f(nome, **campi):
            pth = str(tmp_path / nome)
            Image.new("RGB", (campi.pop("w", 60), campi.pop("h", 40))).save(pth, "JPEG")
            pid = insert_photo(db, file_path=pth, folder_path=str(tmp_path), filename=nome,
                               format="jpg", file_size=100, width=60, height=40)
            if campi: update_photo(db, pid, **campi)
            return pid
        return f

    def test_filtro_coordinate(self, client_with_photo, tmp_path):
        import config
        c, pid, _ = client_with_photo          # la foto della fixture non ha coordinate
        f = self._prepara(config.LOCAL_DB, tmp_path)
        con = f("c.jpg", latitude=45.0, longitude=9.0)
        senza = [p["id"] for p in c.get("/api/photos", params={"has_location": "false"}).json()]
        assert pid in senza and con not in senza
        conn = [p["id"] for p in c.get("/api/photos", params={"has_location": "true"}).json()]
        assert conn == [con]

    def test_filtro_date(self, client_with_photo, tmp_path):
        import config
        c, _, _ = client_with_photo
        f = self._prepara(config.LOCAL_DB, tmp_path)
        vecchia = f("v.jpg", exif_date="2006-07-05T10:00:00")
        f("n.jpg", exif_date="2026-04-01T10:00:00")
        ids = [p["id"] for p in c.get("/api/photos", params={"date_to": "2020-01-01"}).json()]
        assert ids == [vecchia]

    def test_filtro_luogo(self, client_with_photo, tmp_path):
        import config
        c, _, _ = client_with_photo
        f = self._prepara(config.LOCAL_DB, tmp_path)
        lux = f("l.jpg", location_name="Tempio di Luxor")
        f("s.jpg", location_name="Saqqara")
        ids = [p["id"] for p in c.get("/api/photos", params={"location": "luxor"}).json()]
        assert ids == [lux]

    def test_gli_stessi_filtri_valgono_per_gli_id(self, client_with_photo, tmp_path):
        """La griglia e 'Seleziona tutte' devono vedere le stesse foto."""
        import config
        c, _, _ = client_with_photo
        f = self._prepara(config.LOCAL_DB, tmp_path)
        f("g.jpg", latitude=45.0, longitude=9.0)
        par = {"has_location": "false"}
        griglia = sorted(p["id"] for p in c.get("/api/photos", params=par).json())
        selezione = sorted(c.get("/api/photos/ids", params=par).json()["ids"])
        assert griglia == selezione
