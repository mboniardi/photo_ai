"""Route /api/photos."""
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

from database.photos import get_photos, get_photo_by_id, update_photo, count_photos
from services.image_processor import generate_thumbnail
import config

router = APIRouter(prefix="/api/photos", tags=["photos"])


class PhotoUpdateRequest(BaseModel):
    is_favorite: Optional[int] = None
    is_trash: Optional[int] = None
    user_description: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


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


@router.get("/{photo_id}/thumbnail")
def get_thumbnail(photo_id: int, size: int = 400):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    if not os.path.exists(photo["file_path"]):
        raise HTTPException(status_code=404, detail="File non trovato sul disco")
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
