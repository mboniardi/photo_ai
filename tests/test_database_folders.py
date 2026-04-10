"""
Test per database/folders.py — CRUD tabella folders.
"""
import pytest


class TestInsertFolder:
    def test_insert_returns_id(self, tmp_db):
        from database.folders import insert_folder
        fid = insert_folder(tmp_db, folder_path="/mnt/nas/foto",
                            display_name="Foto NAS")
        assert isinstance(fid, int) and fid > 0

    def test_duplicate_path_raises(self, tmp_db):
        from database.folders import insert_folder
        insert_folder(tmp_db, folder_path="/mnt/nas/foto")
        with pytest.raises(Exception):
            insert_folder(tmp_db, folder_path="/mnt/nas/foto")


class TestGetFolder:
    def test_get_by_path(self, tmp_db):
        from database.folders import insert_folder, get_folder_by_path
        insert_folder(tmp_db, folder_path="/mnt/nas/foto",
                      display_name="Vacanze")
        folder = get_folder_by_path(tmp_db, "/mnt/nas/foto")
        assert folder is not None
        assert folder["display_name"] == "Vacanze"

    def test_get_nonexistent_returns_none(self, tmp_db):
        from database.folders import get_folder_by_path
        assert get_folder_by_path(tmp_db, "/nonexistent") is None

    def test_get_all(self, tmp_db):
        from database.folders import insert_folder, get_all_folders
        insert_folder(tmp_db, folder_path="/mnt/a")
        insert_folder(tmp_db, folder_path="/mnt/b")
        folders = get_all_folders(tmp_db)
        assert len(folders) == 2


class TestUpdateFolder:
    def test_update_display_name(self, tmp_db):
        from database.folders import insert_folder, update_folder, get_folder_by_path
        insert_folder(tmp_db, folder_path="/mnt/nas/foto")
        update_folder(tmp_db, "/mnt/nas/foto", display_name="Nuovo Nome")
        folder = get_folder_by_path(tmp_db, "/mnt/nas/foto")
        assert folder["display_name"] == "Nuovo Nome"

    def test_update_counts(self, tmp_db):
        from database.folders import insert_folder, update_folder_counts, get_folder_by_path
        insert_folder(tmp_db, folder_path="/mnt/nas/foto")
        update_folder_counts(tmp_db, "/mnt/nas/foto",
                             photo_count=100, analyzed_count=42)
        folder = get_folder_by_path(tmp_db, "/mnt/nas/foto")
        assert folder["photo_count"] == 100
        assert folder["analyzed_count"] == 42

    def test_update_default_location(self, tmp_db):
        from database.folders import insert_folder, update_folder, get_folder_by_path
        insert_folder(tmp_db, folder_path="/mnt/nas/foto")
        update_folder(tmp_db, "/mnt/nas/foto",
                      default_location_name="Roma, Italia",
                      default_latitude=41.9028,
                      default_longitude=12.4964)
        folder = get_folder_by_path(tmp_db, "/mnt/nas/foto")
        assert folder["default_location_name"] == "Roma, Italia"
        assert abs(folder["default_latitude"] - 41.9028) < 0.001


class TestDeleteFolder:
    def test_delete_removes_folder(self, tmp_db):
        from database.folders import insert_folder, delete_folder, get_folder_by_path
        insert_folder(tmp_db, folder_path="/mnt/nas/foto")
        delete_folder(tmp_db, "/mnt/nas/foto")
        assert get_folder_by_path(tmp_db, "/mnt/nas/foto") is None
