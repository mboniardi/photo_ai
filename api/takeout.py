"""Route /api/takeout — upload e import JSON da Google Takeout."""
import json
import logging
import os
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

import config
from database.photos import get_photo_id_by_path, update_photo
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/takeout", tags=["takeout"])


def _ensure_dir():
    os.makedirs(config.TAKEOUT_JSON_PATH, exist_ok=True)


@router.get("/status")
def takeout_status():
    """Ritorna il numero di JSON presenti nella cartella takeout."""
    if not os.path.isdir(config.TAKEOUT_JSON_PATH):
        return {"json_count": 0, "path": config.TAKEOUT_JSON_PATH}
    files = [f for f in os.listdir(config.TAKEOUT_JSON_PATH) if f.endswith(".json")]
    return {"json_count": len(files), "path": config.TAKEOUT_JSON_PATH}


@router.post("/upload")
async def upload_takeout_jsons(files: List[UploadFile] = File(...)):
    """
    Riceve una lista di file JSON da Google Takeout e li salva sul server.
    Accetta solo file .json; ignora silenziosamente gli altri.
    """
    _ensure_dir()
    saved = 0
    skipped = 0
    for f in files:
        if not f.filename.endswith(".json"):
            skipped += 1
            continue
        # Salva solo il basename (no path traversal)
        dest = os.path.join(config.TAKEOUT_JSON_PATH, os.path.basename(f.filename))
        content = await f.read()
        with open(dest, "wb") as fh:
            fh.write(content)
        saved += 1
    return {"saved": saved, "skipped": skipped}


class ImportRequest(BaseModel):
    force: bool = False


@router.post("/import")
def import_takeout_coords(req: ImportRequest = ImportRequest()):
    """
    Legge i JSON di Takeout salvati e aggiorna latitude/longitude nel DB.
    Con force=True sovrascrive anche le foto che hanno già coordinate.
    Abbina per nome file (title nel JSON).
    """
    if not os.path.isdir(config.TAKEOUT_JSON_PATH):
        raise HTTPException(status_code=404, detail="Nessuna cartella takeout trovata")

    updated = 0
    skipped_no_coords = 0
    skipped_already_has = 0
    not_found = 0
    errors = 0

    # Costruisce indice filename → photo_id dal DB (case-insensitive)
    with get_db(config.LOCAL_DB) as conn:
        rows = conn.execute(
            "SELECT id, filename, latitude FROM photos WHERE is_trash = 0 OR is_trash IS NULL"
        ).fetchall()
    # Indice lowercase per matching case-insensitive
    db_index = {row["filename"].lower(): (row["id"], row["latitude"]) for row in rows}

    for fname in os.listdir(config.TAKEOUT_JSON_PATH):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(config.TAKEOUT_JSON_PATH, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            title = data.get("title", "").strip()
            geo = data.get("geoData") or {}
            lat = geo.get("latitude")
            lon = geo.get("longitude")

            # Coordinate assenti o nulle (0,0 = non georeferenziata in Google Photos)
            if lat is None or lon is None or (lat == 0.0 and lon == 0.0):
                skipped_no_coords += 1
                continue

            title_lower = title.lower()
            if title_lower not in db_index:
                not_found += 1
                logger.debug("Takeout JSON '%s' → title '%s' non trovato nel DB", fname, title)
                continue

            photo_id, existing_lat = db_index[title_lower]
            if existing_lat is not None and not req.force:
                skipped_already_has += 1
                continue

            update_photo(config.LOCAL_DB, photo_id,
                         latitude=lat, longitude=lon,
                         location_source="takeout")
            updated += 1

        except Exception as exc:
            logger.warning("Errore import JSON %s: %s", fname, exc)
            errors += 1

    return {
        "updated": updated,
        "skipped_no_coords": skipped_no_coords,
        "skipped_already_has": skipped_already_has,
        "not_found": not_found,
        "errors": errors,
    }
