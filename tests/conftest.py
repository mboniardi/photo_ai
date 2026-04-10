"""
Fixture condivise e configurazione pytest.
Aggiunge la root del progetto al sys.path in modo che
i moduli (config, database, services) siano importabili.
"""
import sys
import os
import sqlite3
import tempfile
import pytest

# Aggiungi la directory photo_ai/ al path degli import
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def tmp_db(tmp_path):
    """Database SQLite su file temporaneo, già inizializzato con lo schema."""
    from database.models import init_db
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


@pytest.fixture
def db_conn(tmp_db):
    """Connessione sqlite3 aperta sul db temporaneo (sync, row_factory=Row)."""
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
