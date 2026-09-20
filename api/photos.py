"""Route /api/photos."""
import os
import threading
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional

from database.photos import (
    get_photos, get_photo_by_id, update_photo, count_photos, purge_trash,
    bulk_set_location, get_photo_ids_for_selection,
)
from services.image_processor import generate_thumbnail
import config

router = APIRouter(prefix="/api/photos", tags=["photos"])

# Tetto alle decodifiche simultanee: protegge la memoria del container quando
# la griglia chiede molte miniature insieme. Le richieste in eccesso aspettano
# il loro turno invece di allocare tutte insieme.
_thumbnail_slots = threading.Semaphore(config.THUMBNAIL_MAX_CONCURRENT)


class PhotoUpdateRequest(BaseModel):
    is_favorite: Optional[int] = None
    is_trash: Optional[int] = None
    user_description: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_source: Optional[str] = None


class BulkLocationRequest(BaseModel):
    photo_ids: list[int] = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: Optional[str] = None
    overwrite: bool = False


@router.get("")
def list_photos(
    folder_path: Optional[str] = None,
    sort_by: str = "overall_score",
    sort_desc: bool = True,
    min_score: Optional[float] = None,
    is_favorite: Optional[bool] = None,
    is_trash: Optional[bool] = None,
    analyzed: Optional[bool] = None,
    format: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    photos = get_photos(
        config.LOCAL_DB,
        folder_path=folder_path,
        sort_by=sort_by,
        sort_desc=sort_desc,
        min_score=min_score,
        is_favorite=is_favorite,
        is_trash=is_trash,
        analyzed_only=analyzed,
        format=format,
        limit=limit,
        offset=offset,
    )
    return [dict(p) for p in photos]


@router.get("/map")
def get_map_photos():
    """Ritorna tutte le foto con coordinate GPS per la vista mappa."""
    from database import get_db
    with get_db(config.LOCAL_DB) as conn:
        rows = conn.execute(
            """SELECT id, latitude AS lat, longitude AS lon,
                      filename, description, overall_score
               FROM photos
               WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                 AND (is_trash = 0 OR is_trash IS NULL)"""
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/ids")
def photo_ids_for_selection(
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
):
    """
    Gli id di tutto cio' che corrisponde ai filtri, per "seleziona tutte".

    La griglia ne carica cento per volta: senza questa rotta, per selezionarne
    settecento bisognerebbe scorrere sette volte.
    """
    return get_photo_ids_for_selection(
        config.LOCAL_DB,
        folder_path=folder_path, is_favorite=is_favorite, is_trash=is_trash,
        analyzed_only=analyzed_only, min_score=min_score, format=format,
        date_from=date_from, date_to=date_to, location=location,
        orientation=orientation,
    )


@router.put("/bulk-location")
def set_location_in_bulk(req: BulkLocationRequest):
    """
    Assegna la stessa posizione a un gruppo di foto, in una sola transazione.

    Serve prima dell'analisi: senza coordinate il modello indovina il luogo, e
    le descrizioni costruite su un luogo sbagliato sono tutte da rifare — a
    pagamento. La posizione scritta qui diventa il contesto che il worker passa
    al modello.

    Dichiarata prima di /{photo_id}: altrimenti "bulk-location" verrebbe letto
    come un identificativo.
    """
    esito = bulk_set_location(
        config.LOCAL_DB,
        photo_ids=req.photo_ids,
        latitude=req.latitude,
        longitude=req.longitude,
        location_name=req.location_name,
        overwrite=req.overwrite,
    )
    return {"ok": True, **esito}


@router.get("/{photo_id}")
def get_photo(photo_id: int):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    return dict(photo)


@router.put("/{photo_id}")
def update_photo_fields(photo_id: int, req: PhotoUpdateRequest):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if fields:
        update_photo(config.LOCAL_DB, photo_id, **fields)
    return {"ok": True}


@router.delete("/trash")
def purge_trash_endpoint():
    """Rimuove definitivamente dal DB tutte le foto marcate is_trash=1."""
    deleted = purge_trash(config.LOCAL_DB)
    return {"ok": True, "deleted": deleted}


@router.get("/{photo_id}/thumbnail")
def get_thumbnail(photo_id: int, size: int = 400):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    if not os.path.exists(photo["file_path"]):
        raise HTTPException(status_code=404, detail="File non trovato sul disco")
    with _thumbnail_slots:
        jpeg_bytes = generate_thumbnail(photo["file_path"], size=size)
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "max-age=86400"},
    )


@router.get("/{photo_id}/image")
def get_original_image(photo_id: int):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    if not os.path.exists(photo["file_path"]):
        raise HTTPException(status_code=404, detail="File non trovato sul disco")
    with open(photo["file_path"], "rb") as f:
        content = f.read()
    ext = os.path.splitext(photo["file_path"])[1].lower()
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return Response(content=content, media_type=media)
