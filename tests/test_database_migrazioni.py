import sqlite3

from database.migrazioni import assicura_colonne


def test_aggiunge_solo_le_colonne_mancanti(tmp_db):
    aggiunte = assicura_colonne(tmp_db, "photos", {"colonna_prova": "TEXT", "filename": "TEXT"})
    assert aggiunte == ["colonna_prova"]


def test_e_idempotente(tmp_db):
    assicura_colonne(tmp_db, "photos", {"colonna_prova": "TEXT"})
    assert assicura_colonne(tmp_db, "photos", {"colonna_prova": "TEXT"}) == []


def test_init_db_su_database_esistente_aggiunge_le_colonne_nuove(tmp_db):
    # tmp_db e' gia' inizializzato dalla fixture; una seconda init_db non deve fallire
    from database.models import init_db
    init_db(tmp_db)
    cols = [r[1] for r in sqlite3.connect(tmp_db).execute("PRAGMA table_info(photos)")]
    assert {"phash", "origine", "derivati_at"} <= set(cols)
