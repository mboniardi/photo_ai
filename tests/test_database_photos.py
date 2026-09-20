"""
Test per database/photos.py — CRUD tabella photos.
"""
import pytest


PHOTO_DEFAULTS = {
    "file_path": "/mnt/nas/foto/test.jpg",
    "folder_path": "/mnt/nas/foto",
    "filename": "test.jpg",
    "format": "jpg",
    "file_size": 1024000,
    "width": 3000,
    "height": 2000,
}


class TestInsertPhoto:
    def test_insert_returns_id(self, tmp_db):
        from database.photos import insert_photo
        photo_id = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        assert isinstance(photo_id, int)
        assert photo_id > 0

    def test_insert_duplicate_file_path_raises(self, tmp_db):
        from database.photos import insert_photo
        insert_photo(tmp_db, **PHOTO_DEFAULTS)
        with pytest.raises(Exception):
            insert_photo(tmp_db, **PHOTO_DEFAULTS)


class TestGetPhotoById:
    def test_get_existing(self, tmp_db):
        from database.photos import insert_photo, get_photo_by_id
        photo_id = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        photo = get_photo_by_id(tmp_db, photo_id)
        assert photo is not None
        assert photo["filename"] == "test.jpg"
        assert photo["file_path"] == "/mnt/nas/foto/test.jpg"

    def test_get_nonexistent_returns_none(self, tmp_db):
        from database.photos import get_photo_by_id
        assert get_photo_by_id(tmp_db, 99999) is None


class TestGetPhotos:
    def test_returns_list(self, tmp_db):
        from database.photos import insert_photo, get_photos
        insert_photo(tmp_db, **PHOTO_DEFAULTS)
        photos = get_photos(tmp_db)
        assert isinstance(photos, list)
        assert len(photos) == 1

    def test_filter_by_folder(self, tmp_db):
        from database.photos import insert_photo, get_photos
        insert_photo(tmp_db, **PHOTO_DEFAULTS)
        insert_photo(tmp_db,
                     file_path="/mnt/other/img.jpg",
                     folder_path="/mnt/other",
                     filename="img.jpg",
                     format="jpg",
                     file_size=512,
                     width=100,
                     height=100)
        results = get_photos(tmp_db, folder_path="/mnt/nas/foto")
        assert len(results) == 1
        assert results[0]["folder_path"] == "/mnt/nas/foto"

    def test_filter_favorites(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photos
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        update_photo(tmp_db, pid, is_favorite=1)
        results = get_photos(tmp_db, is_favorite=True)
        assert len(results) == 1

    def test_filter_trash(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photos
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        update_photo(tmp_db, pid, is_trash=1)
        results = get_photos(tmp_db, is_trash=True)
        assert len(results) == 1

    def test_pagination(self, tmp_db):
        from database.photos import insert_photo, get_photos
        for i in range(5):
            insert_photo(tmp_db,
                         file_path=f"/mnt/nas/foto/img{i}.jpg",
                         folder_path="/mnt/nas/foto",
                         filename=f"img{i}.jpg",
                         format="jpg",
                         file_size=1000,
                         width=100,
                         height=100)
        page1 = get_photos(tmp_db, limit=3, offset=0)
        page2 = get_photos(tmp_db, limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2


class TestUpdatePhoto:
    def test_update_favorite(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photo_by_id
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        update_photo(tmp_db, pid, is_favorite=1)
        photo = get_photo_by_id(tmp_db, pid)
        assert photo["is_favorite"] == 1

    def test_update_description(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photo_by_id
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        update_photo(tmp_db, pid, user_description="Mia descrizione")
        photo = get_photo_by_id(tmp_db, pid)
        assert photo["user_description"] == "Mia descrizione"

    def test_update_ai_fields(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photo_by_id
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        update_photo(tmp_db, pid,
                     description="Una bella foto",
                     technical_score=7.0,
                     aesthetic_score=8.0,
                     overall_score=7.65,
                     subject="tramonto",
                     atmosphere="romantica",
                     colors='["arancione","rosso"]',
                     ai_engine="gemini",
                     analyzed_at="2024-01-01T12:00:00")
        photo = get_photo_by_id(tmp_db, pid)
        assert photo["technical_score"] == 7.0
        assert photo["overall_score"] == 7.65
        assert photo["subject"] == "tramonto"


class TestDeletePhotoByPath:
    def test_delete_existing(self, tmp_db):
        from database.photos import insert_photo, delete_photo_by_path, get_photo_by_id
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        delete_photo_by_path(tmp_db, PHOTO_DEFAULTS["file_path"])
        assert get_photo_by_id(tmp_db, pid) is None

    def test_delete_nonexistent_is_noop(self, tmp_db):
        from database.photos import delete_photo_by_path
        # Should not raise
        delete_photo_by_path(tmp_db, "/nonexistent/path.jpg")


class TestGetPhotoIdByPath:
    def test_returns_id_for_existing(self, tmp_db):
        from database.photos import insert_photo, get_photo_id_by_path
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        result = get_photo_id_by_path(tmp_db, PHOTO_DEFAULTS["file_path"])
        assert result == pid

    def test_returns_none_for_missing(self, tmp_db):
        from database.photos import get_photo_id_by_path
        assert get_photo_id_by_path(tmp_db, "/nonexistent/path.jpg") is None


class TestExifOrientationInDb:
    def test_insert_and_read_orientation(self, tmp_db):
        from database.photos import insert_photo, get_photo_by_id
        pid = insert_photo(tmp_db, **{**PHOTO_DEFAULTS, "exif_orientation": 6})
        photo = get_photo_by_id(tmp_db, pid)
        assert photo["exif_orientation"] == 6

    def test_insert_without_orientation_is_null(self, tmp_db):
        from database.photos import insert_photo, get_photo_by_id
        pid = insert_photo(tmp_db, **PHOTO_DEFAULTS)
        photo = get_photo_by_id(tmp_db, pid)
        assert photo["exif_orientation"] is None


class TestCountPhotos:
    def test_count_all(self, tmp_db):
        from database.photos import insert_photo, count_photos
        for i in range(3):
            insert_photo(tmp_db,
                         file_path=f"/mnt/nas/foto/img{i}.jpg",
                         folder_path="/mnt/nas/foto",
                         filename=f"img{i}.jpg",
                         format="jpg",
                         file_size=1000,
                         width=100,
                         height=100)
        assert count_photos(tmp_db) == 3

    def test_count_by_folder(self, tmp_db):
        from database.photos import insert_photo, count_photos
        insert_photo(tmp_db, **PHOTO_DEFAULTS)
        assert count_photos(tmp_db, folder_path="/mnt/nas/foto") == 1
        assert count_photos(tmp_db, folder_path="/other") == 0


class TestLibraryStatusCounts:
    """Il pannello della coda mostrava le righe di analysis_queue, che e' un
    registro storico: a coda vuota segnava 100% con migliaia di foto mai
    analizzate. Questi contatori descrivono la LIBRERIA."""

    def _foto(self, db, *, analizzata=False, emb=None, trash=0):
        import json
        from database.photos import insert_photo, update_photo
        import uuid
        pid = insert_photo(db, file_path=f"/x/{uuid.uuid4()}.jpg", folder_path="/x",
                           filename="a.jpg", format="jpg", file_size=1, width=4, height=3)
        campi = {}
        if analizzata: campi["analyzed_at"] = "2026-01-01T00:00:00"
        if emb is not None: campi["embedding"] = json.dumps(emb)
        if trash: campi["is_trash"] = 1
        if campi: update_photo(db, pid, **campi)
        return pid

    def test_counts_split_ai_and_embedding(self, tmp_db):
        from database.photos import count_library_status
        self._foto(tmp_db)                                      # mai analizzata
        self._foto(tmp_db)                                      # mai analizzata
        self._foto(tmp_db, analizzata=True, emb=[0.1] * 4)      # completa
        self._foto(tmp_db, analizzata=True, emb=[0.1] * 99)     # dimensione sbagliata
        self._foto(tmp_db, analizzata=True)                     # senza vettore

        s = count_library_status(tmp_db, embedding_dim=4)
        assert s["total"] == 5
        assert s["to_analyze"] == 2
        assert s["to_embed"] == 2      # dimensione errata + mancante
        assert s["complete"] == 1

    def test_trashed_photos_are_excluded(self, tmp_db):
        from database.photos import count_library_status
        self._foto(tmp_db)
        self._foto(tmp_db, trash=1)
        s = count_library_status(tmp_db, embedding_dim=4)
        assert s["total"] == 1 and s["to_analyze"] == 1

    def test_empty_embedding_counts_as_missing(self, tmp_db):
        from database.photos import count_library_status
        self._foto(tmp_db, analizzata=True, emb=[])
        s = count_library_status(tmp_db, embedding_dim=4)
        assert s["to_embed"] == 1 and s["complete"] == 0


class TestGeoCheckQueries:
    def test_legge_solo_le_foto_georeferenziate_in_ordine(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photos_for_geo_check
        a = insert_photo(tmp_db, file_path="/x/a.jpg", folder_path="/x",
                         filename="a.jpg", format="jpg", file_size=1, width=4, height=3)
        b = insert_photo(tmp_db, file_path="/x/b.jpg", folder_path="/x",
                         filename="b.jpg", format="jpg", file_size=1, width=4, height=3)
        c = insert_photo(tmp_db, file_path="/x/c.jpg", folder_path="/x",
                         filename="c.jpg", format="jpg", file_size=1, width=4, height=3)
        update_photo(tmp_db, a, latitude=25.0, longitude=32.0, exif_date="2026-04-01T12:00:00")
        update_photo(tmp_db, b, latitude=26.0, longitude=32.0, exif_date="2026-04-01T09:00:00")
        update_photo(tmp_db, c, exif_date="2026-04-01T10:00:00")   # senza coordinate
        righe = get_photos_for_geo_check(tmp_db)
        assert [r["id"] for r in righe] == [b, a]

    def test_esclude_il_cestino(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photos_for_geo_check
        pid = insert_photo(tmp_db, file_path="/x/t.jpg", folder_path="/x",
                           filename="t.jpg", format="jpg", file_size=1, width=4, height=3)
        update_photo(tmp_db, pid, latitude=25.0, longitude=32.0,
                     exif_date="2026-04-01T12:00:00", is_trash=1)
        assert get_photos_for_geo_check(tmp_db) == []

    def test_clear_analysis_azzera_l_analisi_e_non_la_posizione(self, tmp_db):
        from database.photos import insert_photo, update_photo, get_photo_by_id, clear_analysis
        pid = insert_photo(tmp_db, file_path="/x/d.jpg", folder_path="/x",
                           filename="d.jpg", format="jpg", file_size=1, width=4, height=3)
        update_photo(tmp_db, pid, description="sbagliata", subject="s", atmosphere="a",
                     strengths="f", weaknesses="d", technical_score=7.0,
                     aesthetic_score=8.0, overall_score=7.5, colors='["rosso"]',
                     embedding="[0.1, 0.2]", analyzed_at="2026-01-01T00:00:00",
                     latitude=25.0, longitude=32.0, location_name="Luxor",
                     is_favorite=1, user_description="mia nota")
        clear_analysis(tmp_db, pid)
        p = get_photo_by_id(tmp_db, pid)
        assert p["description"] is None
        assert p["embedding"] is None
        assert p["analyzed_at"] is None
        assert p["subject"] is None and p["overall_score"] is None
        # la posizione e i dati dell'utente restano
        assert p["latitude"] == 25.0 and p["location_name"] == "Luxor"
        assert p["is_favorite"] == 1 and p["user_description"] == "mia nota"


class TestUnanalyzedPhotoIds:
    def _foto(self, db, cartella, *, analizzata=False, trash=0):
        import uuid
        from database.photos import insert_photo, update_photo
        pid = insert_photo(db, file_path=f"{cartella}/{uuid.uuid4()}.jpg", folder_path=cartella,
                           filename="a.jpg", format="jpg", file_size=1, width=4, height=3)
        campi = {}
        if analizzata: campi["analyzed_at"] = "2026-01-01T00:00:00"
        if trash: campi["is_trash"] = 1
        if campi: update_photo(db, pid, **campi)
        return pid

    def test_solo_le_non_analizzate_della_cartella(self, tmp_db):
        from database.photos import get_unanalyzed_photo_ids
        da_fare = self._foto(tmp_db, "/a")
        self._foto(tmp_db, "/a", analizzata=True)
        self._foto(tmp_db, "/b")
        assert get_unanalyzed_photo_ids(tmp_db, folder_path="/a") == [da_fare]

    def test_esclude_il_cestino(self, tmp_db):
        from database.photos import get_unanalyzed_photo_ids
        self._foto(tmp_db, "/a", trash=1)
        assert get_unanalyzed_photo_ids(tmp_db, folder_path="/a") == []

    def test_senza_cartella_prende_tutta_la_libreria(self, tmp_db):
        from database.photos import get_unanalyzed_photo_ids
        a = self._foto(tmp_db, "/a"); b = self._foto(tmp_db, "/b")
        assert sorted(get_unanalyzed_photo_ids(tmp_db)) == sorted([a, b])

    def test_nessun_limite_arbitrario(self, tmp_db):
        """api/folders.py aveva limit=10000: su una cartella piu' grande
        troncava in silenzio."""
        from database.photos import get_unanalyzed_photo_ids
        attesi = [self._foto(tmp_db, "/a") for _ in range(120)]
        assert len(get_unanalyzed_photo_ids(tmp_db, folder_path="/a")) == len(attesi)


class TestBulkSetLocation:
    """Assegnare una posizione a centinaia di foto in un colpo solo, prima di
    mandarle all'AI: senza coordinate il modello inventa il luogo e le
    descrizioni sarebbero tutte da rifare."""

    def _foto(self, db, *, lat=None, lon=None, src=None, descr=None, fav=0):
        import uuid
        from database.photos import insert_photo, update_photo
        pid = insert_photo(db, file_path=f"/x/{uuid.uuid4()}.jpg", folder_path="/x",
                           filename="a.jpg", format="jpg", file_size=1, width=4, height=3)
        campi = {}
        if lat is not None: campi.update(latitude=lat, longitude=lon, location_source=src)
        if descr: campi["description"] = descr
        if fav: campi["is_favorite"] = 1
        if campi: update_photo(db, pid, **campi)
        return pid

    def _assegna(self, db, ids, overwrite=False):
        from database.photos import bulk_set_location
        return bulk_set_location(db, photo_ids=ids, latitude=37.0, longitude=-110.0,
                                 location_name="Monument Valley", overwrite=overwrite)

    def test_senza_overwrite_salta_chi_ha_gia_una_posizione(self, tmp_db):
        from database.photos import get_photo_by_id
        vuota = self._foto(tmp_db)
        con_gps = self._foto(tmp_db, lat=36.0, lon=-111.0, src="exif")
        r = self._assegna(tmp_db, [vuota, con_gps])
        assert r["aggiornate"] == 1 and r["saltate"] == 1
        assert get_photo_by_id(tmp_db, vuota)["latitude"] == 37.0
        # il GPS della fotocamera non si tocca
        p = get_photo_by_id(tmp_db, con_gps)
        assert p["latitude"] == 36.0 and p["location_source"] == "exif"

    def test_con_overwrite_scrive_su_tutte(self, tmp_db):
        from database.photos import get_photo_by_id
        vuota = self._foto(tmp_db)
        con_gps = self._foto(tmp_db, lat=36.0, lon=-111.0, src="exif")
        r = self._assegna(tmp_db, [vuota, con_gps], overwrite=True)
        assert r["aggiornate"] == 2 and r["saltate"] == 0
        p = get_photo_by_id(tmp_db, con_gps)
        assert p["latitude"] == 37.0 and p["location_source"] == "manual"

    def test_scrive_nome_e_origine_manual(self, tmp_db):
        from database.photos import get_photo_by_id
        pid = self._foto(tmp_db)
        self._assegna(tmp_db, [pid])
        p = get_photo_by_id(tmp_db, pid)
        assert p["location_name"] == "Monument Valley"
        assert p["location_source"] == "manual"
        assert p["longitude"] == -110.0

    def test_non_tocca_nient_altro(self, tmp_db):
        from database.photos import get_photo_by_id
        pid = self._foto(tmp_db, descr="descrizione mia", fav=1)
        self._assegna(tmp_db, [pid])
        p = get_photo_by_id(tmp_db, pid)
        assert p["description"] == "descrizione mia" and p["is_favorite"] == 1
        assert p["analyzed_at"] is None

    def test_gli_id_inesistenti_finiscono_in_mancanti(self, tmp_db):
        pid = self._foto(tmp_db)
        r = self._assegna(tmp_db, [pid, 999999])
        assert r["aggiornate"] == 1 and r["mancanti"] == [999999]

    def test_lista_vuota(self, tmp_db):
        r = self._assegna(tmp_db, [])
        assert r == {"aggiornate": 0, "saltate": 0, "mancanti": []}

    def test_centinaia_di_foto_in_una_sola_chiamata(self, tmp_db):
        ids = [self._foto(tmp_db) for _ in range(250)]
        r = self._assegna(tmp_db, ids)
        assert r["aggiornate"] == 250


class TestPhotoIdsForSelection:
    """'Seleziona tutte le N' deve prendere tutto cio' che corrisponde ai
    filtri, non le sole 100 gia' caricate nella griglia."""

    def _foto(self, db, cartella, *, lat=None, trash=0):
        import uuid
        from database.photos import insert_photo, update_photo
        pid = insert_photo(db, file_path=f"{cartella}/{uuid.uuid4()}.jpg", folder_path=cartella,
                           filename="a.jpg", format="jpg", file_size=1, width=4, height=3)
        campi = {}
        if lat is not None: campi.update(latitude=lat, longitude=1.0)
        if trash: campi["is_trash"] = 1
        if campi: update_photo(db, pid, **campi)
        return pid

    def test_rispetta_il_filtro_cartella(self, tmp_db):
        from database.photos import get_photo_ids_for_selection
        a = self._foto(tmp_db, "/a"); self._foto(tmp_db, "/b")
        r = get_photo_ids_for_selection(tmp_db, folder_path="/a")
        assert r["ids"] == [a]

    def test_indica_quali_hanno_gia_una_posizione(self, tmp_db):
        from database.photos import get_photo_ids_for_selection
        senza = self._foto(tmp_db, "/a")
        con = self._foto(tmp_db, "/a", lat=45.0)
        r = get_photo_ids_for_selection(tmp_db, folder_path="/a")
        assert sorted(r["ids"]) == sorted([senza, con])
        assert r["con_posizione"] == [con]

    def test_nessun_limite_a_cento(self, tmp_db):
        from database.photos import get_photo_ids_for_selection
        for _ in range(230): self._foto(tmp_db, "/a")
        assert len(get_photo_ids_for_selection(tmp_db, folder_path="/a")["ids"]) == 230

    def test_rispetta_il_filtro_analizzate(self, tmp_db):
        from database.photos import get_photo_ids_for_selection, update_photo
        da_fare = self._foto(tmp_db, "/a")
        fatta = self._foto(tmp_db, "/a")
        update_photo(tmp_db, fatta, analyzed_at="2026-01-01T00:00:00")
        assert get_photo_ids_for_selection(tmp_db, folder_path="/a", analyzed_only=False)["ids"] == [da_fare]

    def test_esclude_il_cestino_se_richiesto(self, tmp_db):
        from database.photos import get_photo_ids_for_selection
        viva = self._foto(tmp_db, "/a"); self._foto(tmp_db, "/a", trash=1)
        assert get_photo_ids_for_selection(tmp_db, folder_path="/a", is_trash=False)["ids"] == [viva]


class TestMarkLocationConfirmed:
    """Quando la posizione attuale e' gia' giusta ed e' la proposta a sbagliare:
    si marca 'manual' e basta. Niente rianalisi, quindi nessun costo."""

    def _foto(self, db, *, lat=None, src=None, descr=None):
        import uuid
        from database.photos import insert_photo, update_photo
        pid = insert_photo(db, file_path=f"/x/{uuid.uuid4()}.jpg", folder_path="/x",
                           filename="a.jpg", format="jpg", file_size=1, width=4, height=3)
        campi = {}
        if lat is not None: campi.update(latitude=lat, longitude=2.0, location_source=src)
        if descr: campi.update(description=descr, analyzed_at="2026-01-01T00:00:00",
                               embedding="[0.1]")
        if campi: update_photo(db, pid, **campi)
        return pid

    def test_marca_manual_senza_toccare_le_coordinate(self, tmp_db):
        from database.photos import mark_location_confirmed, get_photo_by_id
        pid = self._foto(tmp_db, lat=30.0, src="ai")
        assert mark_location_confirmed(tmp_db, photo_ids=[pid]) == 1
        p = get_photo_by_id(tmp_db, pid)
        assert p["location_source"] == "manual"
        assert p["latitude"] == 30.0 and p["longitude"] == 2.0

    def test_non_tocca_analisi_ne_embedding(self, tmp_db):
        from database.photos import mark_location_confirmed, get_photo_by_id
        pid = self._foto(tmp_db, lat=30.0, src="ai", descr="descrizione buona")
        mark_location_confirmed(tmp_db, photo_ids=[pid])
        p = get_photo_by_id(tmp_db, pid)
        assert p["description"] == "descrizione buona"
        assert p["analyzed_at"] is not None and p["embedding"] == "[0.1]"

    def test_salta_chi_non_ha_coordinate(self, tmp_db):
        from database.photos import mark_location_confirmed, get_photo_by_id
        senza = self._foto(tmp_db)
        assert mark_location_confirmed(tmp_db, photo_ids=[senza]) == 0
        assert get_photo_by_id(tmp_db, senza)["location_source"] is None

    def test_lista_vuota(self, tmp_db):
        from database.photos import mark_location_confirmed
        assert mark_location_confirmed(tmp_db, photo_ids=[]) == 0


class TestFiltriFinoraMorti:
    """Date, luogo, orientamento e formati multipli: presenti nel pannello
    dell'interfaccia e ignorati dal codice. Qui si verificano davvero."""

    def _foto(self, db, *, data=None, luogo=None, lat=None, w=4, h=3, fmt="jpg"):
        import uuid
        from database.photos import insert_photo, update_photo
        pid = insert_photo(db, file_path=f"/x/{uuid.uuid4()}.{fmt}", folder_path="/x",
                           filename=f"a.{fmt}", format=fmt, file_size=1, width=w, height=h)
        campi = {}
        if data: campi["exif_date"] = data
        if luogo: campi["location_name"] = luogo
        if lat is not None: campi.update(latitude=lat, longitude=1.0)
        if campi: update_photo(db, pid, **campi)
        return pid

    def _ids(self, db, **f):
        from database.photos import get_photos
        return [r["id"] for r in get_photos(db, **f)]

    def test_filtro_su_presenza_di_coordinate(self, tmp_db):
        senza = self._foto(tmp_db)
        con = self._foto(tmp_db, lat=45.0)
        assert self._ids(tmp_db, has_location=False) == [senza]
        assert self._ids(tmp_db, has_location=True) == [con]
        assert sorted(self._ids(tmp_db)) == sorted([senza, con])

    def test_filtro_data_da_e_a(self, tmp_db):
        vecchia = self._foto(tmp_db, data="2006-07-05T10:00:00")
        nuova = self._foto(tmp_db, data="2026-04-01T10:00:00")
        assert self._ids(tmp_db, date_from="2020-01-01") == [nuova]
        assert self._ids(tmp_db, date_to="2020-01-01") == [vecchia]
        assert self._ids(tmp_db, date_from="2006-07-01", date_to="2006-07-31") == [vecchia]

    def test_filtro_luogo_e_parziale(self, tmp_db):
        luxor = self._foto(tmp_db, luogo="Tempio di Luxor, Egitto")
        self._foto(tmp_db, luogo="Necropoli di Saqqara")
        assert self._ids(tmp_db, location="luxor") == [luxor]

    def test_filtro_orientamento(self, tmp_db):
        oriz = self._foto(tmp_db, w=100, h=50)
        vert = self._foto(tmp_db, w=50, h=100)
        quad = self._foto(tmp_db, w=80, h=80)
        assert self._ids(tmp_db, orientation="horizontal") == [oriz]
        assert self._ids(tmp_db, orientation="vertical") == [vert]
        assert self._ids(tmp_db, orientation="square") == [quad]

    def test_piu_formati_insieme(self, tmp_db):
        """Il client manda 'jpg,png': prima diventava format = 'jpg,png' e non
        corrispondeva a nulla."""
        j = self._foto(tmp_db, fmt="jpg")
        p_ = self._foto(tmp_db, fmt="png")
        self._foto(tmp_db, fmt="cr2")
        assert sorted(self._ids(tmp_db, format="jpg,png")) == sorted([j, p_])
        assert self._ids(tmp_db, format="jpg") == [j]

    def test_i_filtri_valgono_anche_per_seleziona_tutte(self, tmp_db):
        """La griglia e la selezione devono vedere le stesse foto."""
        from database.photos import get_photos, get_photo_ids_for_selection
        self._foto(tmp_db, lat=45.0)
        senza = self._foto(tmp_db)
        griglia = [r["id"] for r in get_photos(tmp_db, has_location=False)]
        selezione = get_photo_ids_for_selection(tmp_db, has_location=False)["ids"]
        assert griglia == selezione == [senza]
