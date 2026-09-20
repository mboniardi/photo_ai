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
