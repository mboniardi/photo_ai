"""
Gestione connessioni SQLite.
Espone get_db(): context manager che fornisce una connessione
con row_factory=sqlite3.Row, WAL mode e autocommit/rollback.
"""
import sqlite3
from contextlib import contextmanager
from typing import Optional
import config


@contextmanager
def get_db(db_path: Optional[str] = None):
    """
    Context manager per connessioni SQLite.
    - row_factory = sqlite3.Row (accesso per nome colonna)
    - WAL mode (letture concorrenti senza lock)
    - Commit automatico al successo, rollback in caso di eccezione
    """
    path = db_path or config.LOCAL_DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
