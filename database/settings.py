"""
CRUD per la tabella settings (chiave-valore).
"""
from typing import Optional
from database import get_db


def get_setting(
    db_path: Optional[str] = None,
    key: str = "",
    default: Optional[str] = None,
) -> Optional[str]:
    """Ritorna il valore della chiave, o default se non esiste."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(
    db_path: Optional[str] = None,
    key: str = "",
    value: str = "",
) -> None:
    """Inserisce o aggiorna una chiave (upsert)."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_all_settings(db_path: Optional[str] = None) -> dict:
    """Ritorna tutte le impostazioni come dizionario {key: value}."""
    with get_db(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}
