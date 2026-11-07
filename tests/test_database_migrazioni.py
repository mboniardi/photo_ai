import sqlite3

import pytest

from database.migrazioni import assicura_colonne


def test_aggiunge_solo_le_colonne_mancanti(tmp_db):
    aggiunte = assicura_colonne(tmp_db, "photos", {"colonna_prova": "TEXT", "filename": "TEXT"})
    assert aggiunte == ["colonna_prova"]


def test_e_idempotente(tmp_db):
    assicura_colonne(tmp_db, "photos", {"colonna_prova": "TEXT"})
    assert assicura_colonne(tmp_db, "photos", {"colonna_prova": "TEXT"}) == []


def test_tabella_non_ammessa_solleva_valueerror(tmp_db):
    with pytest.raises(ValueError):
        assicura_colonne(tmp_db, "photos; DROP TABLE photos", {"x": "TEXT"})


def test_init_db_su_database_legacy_aggiunge_le_colonne_nuove(tmp_path):
    # Database antecedente alle colonne nuove, creato a mano (non via init_db).
    # Include le colonne su cui init_db crea gia' indici (altrimenti fallirebbe).
    db = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE photos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "file_path TEXT UNIQUE NOT NULL, folder_path TEXT NOT NULL, "
        "filename TEXT NOT NULL, overall_score REAL, is_favorite INTEGER DEFAULT 0, "
        "analyzed_at TEXT)"
    )
    conn.execute(
        "INSERT INTO photos (file_path, folder_path, filename) "
        "VALUES ('/a/b.jpg', '/a', 'b.jpg')"
    )
    conn.commit()
    conn.close()

    from database.models import init_db
    init_db(db)

    conn = sqlite3.connect(db)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(photos)")]
        assert {"phash", "origine", "derivati_at"} <= set(cols)
        riga = conn.execute(
            "SELECT file_path, folder_path, filename, origine FROM photos"
        ).fetchone()
    finally:
        conn.close()
    assert riga == ("/a/b.jpg", "/a", "b.jpg", "nas")
