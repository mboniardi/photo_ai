"""
CRUD per la tabella folders.
"""
from typing import Optional
from database import get_db


def insert_folder(
    db_path: Optional[str] = None,
    *,
    folder_path: str,
    display_name: Optional[str] = None,
    default_location_name: Optional[str] = None,
    default_latitude: Optional[float] = None,
    default_longitude: Optional[float] = None,
    auto_analyze: int = 0,
) -> int:
    """Inserisce una nuova cartella. Ritorna l'id assegnato."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO folders (
                folder_path, display_name,
                default_location_name, default_latitude, default_longitude,
                auto_analyze
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (folder_path, display_name or folder_path.rstrip("/").split("/")[-1],
             default_location_name, default_latitude, default_longitude,
             auto_analyze),
        )
        return cur.lastrowid


def get_folder_by_path(db_path: Optional[str], folder_path: str):
    """Ritorna il record folder o None."""
    with get_db(db_path) as conn:
        return conn.execute(
            "SELECT * FROM folders WHERE folder_path = ?", (folder_path,)
        ).fetchone()


def get_all_folders(db_path: Optional[str] = None) -> list:
    """Ritorna tutte le cartelle con conteggio live escludendo foto trashate."""
    with get_db(db_path) as conn:
        return conn.execute(
            """
            SELECT f.*,
                   COALESCE(p.live_count, 0) AS photo_count
            FROM folders f
            LEFT JOIN (
                SELECT folder_path, COUNT(*) AS live_count
                FROM photos
                WHERE is_trash = 0 OR is_trash IS NULL
                GROUP BY folder_path
            ) p ON p.folder_path = f.folder_path
            ORDER BY f.folder_path
            """
        ).fetchall()


def update_folder(
    db_path: Optional[str],
    folder_path: str,
    **fields,
) -> None:
    """Aggiorna i campi specificati di una cartella."""
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [folder_path]
    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE folders SET {set_clause} WHERE folder_path = ?",
            params,
        )


def update_folder_counts(
    db_path: Optional[str],
    folder_path: str,
    photo_count: int,
    analyzed_count: int,
) -> None:
    """Aggiorna i contatori foto/analizzate e last_scanned."""
    with get_db(db_path) as conn:
        conn.execute(
            """
            UPDATE folders
            SET photo_count = ?,
                analyzed_count = ?,
                last_scanned = datetime('now')
            WHERE folder_path = ?
            """,
            (photo_count, analyzed_count, folder_path),
        )


def delete_folder(db_path: Optional[str], folder_path: str) -> None:
    """Rimuove la cartella dalla libreria (non tocca i file)."""
    with get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM folders WHERE folder_path = ?", (folder_path,)
        )
