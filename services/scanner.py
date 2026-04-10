"""
Scan del filesystem per indicizzare foto nel DB (§6.2).
- Ricorsivo nelle sottocartelle
- Deduplicazione: skip se stesso file_path + file_size + exif_date
- Chiama exif_reader per estrarre metadati
"""
import os
from dataclasses import dataclass, field
from typing import Optional

from database import get_db
from database.photos import insert_photo, get_photos
from services.exif_reader import read_exif

# Estensioni supportate (minuscolo)
SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".heic", ".heif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2",
    ".png",
}

_EXT_TO_FORMAT = {
    ".jpg": "jpg", ".jpeg": "jpg",
    ".heic": "heic", ".heif": "heic",
    ".cr2": "raw", ".cr3": "raw", ".nef": "raw",
    ".arw": "raw", ".dng": "raw", ".orf": "raw", ".rw2": "raw",
    ".png": "png",
}


@dataclass
class ScanResult:
    new: int = 0
    skipped: int = 0
    errors: int = 0
    new_photo_ids: list = field(default_factory=list)


def _delete_photo_by_path(db_path: Optional[str], file_path: str) -> None:
    """Rimuove il record photo con il dato file_path (per re-indicizzazione)."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM photos WHERE file_path = ?", (file_path,))


def scan_folder(folder_path: str, db_path: Optional[str] = None) -> ScanResult:
    """
    Scansiona ricorsivamente folder_path.
    Inserisce nel DB i nuovi file; skippa quelli già indicizzati
    con stesso path + size + exif_date.
    Se un file è cambiato (stesso path, diversa size o exif_date),
    elimina il vecchio record e re-inserisce.
    Ritorna un ScanResult con i contatori.
    """
    result = ScanResult()

    # Indice veloce dei file già presenti: file_path → (file_size, exif_date)
    existing = {
        row["file_path"]: (row["file_size"], row["exif_date"])
        for row in get_photos(db_path, folder_path=folder_path, limit=100000)
    }

    for dirpath, _, filenames in os.walk(folder_path):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTS:
                continue

            abs_path = os.path.join(dirpath, fname)
            try:
                current_size = os.path.getsize(abs_path)
                meta = read_exif(abs_path)
                current_date = meta.get("exif_date")

                # Deduplicazione
                if abs_path in existing:
                    prev_size, prev_date = existing[abs_path]
                    if prev_size == current_size and prev_date == current_date:
                        result.skipped += 1
                        continue
                    # File cambiato: elimina il vecchio record prima di re-inserire
                    _delete_photo_by_path(db_path, abs_path)

                photo_id = insert_photo(
                    db_path,
                    file_path=abs_path,
                    folder_path=folder_path,
                    filename=fname,
                    format=_EXT_TO_FORMAT.get(ext, ext.lstrip(".")),
                    file_size=current_size,
                    width=meta.get("width"),
                    height=meta.get("height"),
                    exif_date=current_date,
                    camera_make=meta.get("camera_make"),
                    camera_model=meta.get("camera_model"),
                    lens_model=meta.get("lens_model"),
                    focal_length=meta.get("focal_length"),
                    aperture=meta.get("aperture"),
                    shutter_speed=meta.get("shutter_speed"),
                    iso=meta.get("iso"),
                    latitude=meta.get("latitude"),
                    longitude=meta.get("longitude"),
                    location_source="exif" if meta.get("latitude") else None,
                )
                result.new += 1
                result.new_photo_ids.append(photo_id)

            except Exception:
                result.errors += 1

    return result
