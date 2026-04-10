"""
Test per database/models.py — schema SQLite e init_db().
"""
import sqlite3
import pytest


def table_names(db_path: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]


def column_names(db_path: str, table: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


class TestInitDb:
    def test_creates_photos_table(self, tmp_path):
        from database.models import init_db
        db = str(tmp_path / "db.db")
        init_db(db)
        assert "photos" in table_names(db)

    def test_creates_folders_table(self, tmp_path):
        from database.models import init_db
        db = str(tmp_path / "db.db")
        init_db(db)
        assert "folders" in table_names(db)

    def test_creates_analysis_queue_table(self, tmp_path):
        from database.models import init_db
        db = str(tmp_path / "db.db")
        init_db(db)
        assert "analysis_queue" in table_names(db)

    def test_creates_settings_table(self, tmp_path):
        from database.models import init_db
        db = str(tmp_path / "db.db")
        init_db(db)
        assert "settings" in table_names(db)

    def test_idempotent(self, tmp_path):
        from database.models import init_db
        db = str(tmp_path / "db.db")
        init_db(db)
        init_db(db)  # seconda chiamata non deve sollevare eccezioni

    def test_wal_mode_enabled(self, tmp_path):
        from database.models import init_db
        db = str(tmp_path / "db.db")
        init_db(db)
        with sqlite3.connect(db) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


class TestPhotosSchema:
    def test_required_columns(self, tmp_db):
        cols = column_names(tmp_db, "photos")
        for col in ["id", "file_path", "folder_path", "filename", "format",
                    "exif_date", "width", "height", "file_size",
                    "camera_make", "camera_model", "lens_model",
                    "focal_length", "aperture", "shutter_speed", "iso",
                    "latitude", "longitude", "location_name", "location_source",
                    "description", "technical_score", "aesthetic_score",
                    "overall_score", "subject", "atmosphere", "colors",
                    "strengths", "weaknesses", "ai_engine", "embedding",
                    "analyzed_at", "is_favorite", "is_trash", "user_description",
                    "created_at", "updated_at"]:
            assert col in cols, f"Colonna mancante in photos: {col}"


class TestFoldersSchema:
    def test_required_columns(self, tmp_db):
        cols = column_names(tmp_db, "folders")
        for col in ["id", "folder_path", "display_name",
                    "default_location_name", "default_latitude",
                    "default_longitude", "photo_count", "analyzed_count",
                    "last_scanned", "auto_analyze"]:
            assert col in cols, f"Colonna mancante in folders: {col}"


class TestQueueSchema:
    def test_required_columns(self, tmp_db):
        cols = column_names(tmp_db, "analysis_queue")
        for col in ["id", "photo_id", "priority", "status",
                    "error_msg", "attempts", "queued_at", "processed_at"]:
            assert col in cols, f"Colonna mancante in analysis_queue: {col}"


class TestSettingsSchema:
    def test_required_columns(self, tmp_db):
        cols = column_names(tmp_db, "settings")
        assert "key" in cols
        assert "value" in cols
