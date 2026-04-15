"""
Scan del filesystem per indicizzare foto nel DB (§6.2).
- Ricorsivo nelle sottocartelle
- Deduplicazione: skip se stesso file_path + file_size + exif_date
- Chiama exif_reader per estrarre metadati
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import config
from database.photos import insert_photo, get_photos, update_photo
from services.exif_reader import read_exif

logger = logging.getLogger(__name__)

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
    new_photo_ids: list[int] = field(default_factory=list)
    error_paths: list[str] = field(default_factory=list)


def scan_folder(folder_path: str, db_path: Optional[str] = None) -> ScanResult:
    """
    Scansiona ricorsivamente folder_path.
    Inserisce nel DB i nuovi file; skippa quelli già indicizzati
    con stesso path + size + exif_date.
    Se un file è cambiato (stesso path, diversa size o exif_date),
    aggiorna i campi tecnici del record esistente preservando i dati utente.
    Ritorna un ScanResult con i contatori.
    """
    result = ScanResult()

    # Indice veloce dei file già presenti: file_path → (file_size, exif_date, photo_id, is_trash)
    existing = {
        row["file_path"]: (row["file_size"], row["exif_date"], row["id"], row["is_trash"])
        for row in get_photos(db_path, folder_path=folder_path, limit=100000)
    }

    for dirpath, _, filenames in os.walk(folder_path, followlinks=True):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTS or ext in config.EXCLUDED_EXTS:
                continue

            abs_path = os.path.join(dirpath, fname)
            try:
                current_size = os.path.getsize(abs_path)
                meta = read_exif(abs_path)
                current_date = meta.get("exif_date")

                # Deduplicazione
                if abs_path in existing:
                    prev_size, prev_date, photo_id, is_trash = existing[abs_path]
                    # Se era in trash, ripristinala come attiva
                    if is_trash:
                        update_photo(db_path, photo_id, is_trash=0)
                        result.new += 1
                        result.new_photo_ids.append(photo_id)
                        continue
                    if prev_size == current_size and prev_date == current_date:
                        result.skipped += 1
                        continue
                    # File cambiato: aggiorna solo i campi tecnici preservando i dati utente
                    update_photo(
                        db_path,
                        photo_id,
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
                    continue

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

            except Exception as exc:
                logger.warning("Errore scansione %s: %s", abs_path, exc, exc_info=True)
                result.errors += 1
                result.error_paths.append(abs_path)

    return result
