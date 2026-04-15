"""
CRUD per la tabella photos.
Ogni funzione accetta un db_path opzionale (usato nei test);
se omesso usa config.LOCAL_DB tramite get_db().
"""
from typing import Optional
from database import get_db


_ALLOWED_SORT_COLUMNS = frozenset({
    "id", "filename", "exif_date", "file_size", "width", "height",
    "overall_score", "technical_score", "aesthetic_score",
    "analyzed_at", "created_at", "updated_at", "folder_path",
})


def insert_photo(
    db_path: Optional[str] = None,
    *,
    file_path: str,
    folder_path: str,
    filename: str,
    format: Optional[str] = None,
    file_size: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    exif_orientation: Optional[int] = None,
    exif_date: Optional[str] = None,
    camera_make: Optional[str] = None,
    camera_model: Optional[str] = None,
    lens_model: Optional[str] = None,
    focal_length: Optional[float] = None,
    aperture: Optional[float] = None,
    shutter_speed: Optional[str] = None,
    iso: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    location_name: Optional[str] = None,
    location_source: Optional[str] = None,
) -> int:
    """Inserisce una nuova foto. Ritorna l'id assegnato."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO photos (
                file_path, folder_path, filename, format, file_size,
                width, height, exif_orientation, exif_date,
                camera_make, camera_model, lens_model,
                focal_length, aperture, shutter_speed, iso,
                latitude, longitude, location_name, location_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_path, folder_path, filename, format, file_size,
                width, height, exif_orientation, exif_date,
                camera_make, camera_model, lens_model,
                focal_length, aperture, shutter_speed, iso,
                latitude, longitude, location_name, location_source,
            ),
        )
        return cur.lastrowid


def get_photo_by_id(db_path: Optional[str], photo_id: int):
    """Ritorna il record photo come sqlite3.Row o None se non trovato."""
    with get_db(db_path) as conn:
        return conn.execute(
            "SELECT * FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()


def get_photos(
    db_path: Optional[str] = None,
    *,
    folder_path: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    is_trash: Optional[bool] = None,
    analyzed_only: Optional[bool] = None,
    min_score: Optional[float] = None,
    format: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    orientation: Optional[str] = None,
    sort_by: str = "id",
    sort_desc: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list:
    """
    Lista foto con filtri combinati (AND logico).
    Ritorna lista di sqlite3.Row.
    """
    if sort_by not in _ALLOWED_SORT_COLUMNS:
        sort_by = "id"

    conditions = []
    params = []

    if folder_path is not None:
        conditions.append("folder_path = ?")
        params.append(folder_path)
    if is_favorite is True:
        conditions.append("is_favorite = 1")
    elif is_favorite is False:
        conditions.append("is_favorite = 0")
    if is_trash is True:
        conditions.append("is_trash = 1")
    elif is_trash is False:
        conditions.append("is_trash = 0")
    if analyzed_only is True:
        conditions.append("analyzed_at IS NOT NULL")
    if analyzed_only is False:
        conditions.append("analyzed_at IS NULL")
    if min_score is not None:
        conditions.append("overall_score >= ?")
        params.append(min_score)
    if format is not None:
        conditions.append("format = ?")
        params.append(format)
    if date_from is not None:
        conditions.append("substr(exif_date, 1, 10) >= ?")
        params.append(date_from)
    if date_to is not None:
        conditions.append("substr(exif_date, 1, 10) <= ?")
        params.append(date_to)
    if location is not None:
        conditions.append("location_name LIKE ?")
        params.append(f"%{location}%")
    if orientation == "horizontal":
        conditions.append("width > height")
    elif orientation == "vertical":
        conditions.append("height > width")
    elif orientation == "square":
        conditions.append("width = height")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = f"ORDER BY {sort_by} {'DESC' if sort_desc else 'ASC'}"

    with get_db(db_path) as conn:
        return conn.execute(
            f"SELECT * FROM photos {where} {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()


def count_photos(
    db_path: Optional[str] = None,
    *,
    folder_path: Optional[str] = None,
    analyzed_only: Optional[bool] = None,
    is_trash: Optional[bool] = None,
) -> int:
    """Conta foto con filtri opzionali."""
    conditions = []
    params = []

    if folder_path is not None:
        conditions.append("folder_path = ?")
        params.append(folder_path)
    if analyzed_only is True:
        conditions.append("analyzed_at IS NOT NULL")
    if analyzed_only is False:
        conditions.append("analyzed_at IS NULL")
    if is_trash is True:
        conditions.append("is_trash = 1")
    elif is_trash is False:
        conditions.append("(is_trash = 0 OR is_trash IS NULL)")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db(db_path) as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM photos {where}", params
        ).fetchone()
        return row[0]


def get_photo_id_by_path(db_path: Optional[str], file_path: str) -> Optional[int]:
    """Ritorna l'id del record photo con il dato file_path, o None se non trovato."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM photos WHERE file_path = ?", (file_path,)
        ).fetchone()
        return row["id"] if row else None


def purge_trash(db_path: Optional[str]) -> int:
    """Rimuove definitivamente dal DB tutte le foto con is_trash=1. Ritorna il numero di record eliminati."""
    with get_db(db_path) as conn:
        cur = conn.execute("DELETE FROM photos WHERE is_trash = 1")
        return cur.rowcount


def delete_photo_by_path(db_path: Optional[str], file_path: str) -> None:
    """Rimuove il record photo con il dato file_path."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM photos WHERE file_path = ?", (file_path,))


def update_photo(db_path: Optional[str], photo_id: int, **fields) -> None:
    """
    Aggiorna i campi specificati di una foto.
    Aggiorna automaticamente updated_at.
    """
    if not fields:
        return

    fields["updated_at"] = "datetime('now')"
    set_clause = ", ".join(
        f"{k} = datetime('now')" if k == "updated_at" else f"{k} = ?"
        for k in fields
    )
    values = [v for k, v in fields.items() if k != "updated_at"]
    values.append(photo_id)

    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE photos SET {set_clause} WHERE id = ?",
            values,
        )
