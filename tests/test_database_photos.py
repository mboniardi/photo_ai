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
