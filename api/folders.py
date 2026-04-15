"""Route /api/folders."""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from database.folders import (
    get_all_folders, insert_folder, get_folder_by_path,
    update_folder, update_folder_counts, delete_folder,
)
from database.photos import count_photos, get_photos
from database.queue import add_to_queue
from services.scanner import scan_folder
import config

router = APIRouter(prefix="/api/folders", tags=["folders"])


class ScanRequest(BaseModel):
    folder_path: str
    display_name: Optional[str] = None
    default_location_name: Optional[str] = None
    default_latitude: Optional[float] = None
    default_longitude: Optional[float] = None
    auto_analyze: int = 0


class FolderUpdateRequest(BaseModel):
    folder_path: str
    display_name: Optional[str] = None
    default_location_name: Optional[str] = None
    default_latitude: Optional[float] = None
    default_longitude: Optional[float] = None
    auto_analyze: Optional[int] = None


class FolderDeleteRequest(BaseModel):
    folder_path: str


@router.get("")
def list_folders():
    return [dict(f) for f in get_all_folders(config.LOCAL_DB)]


@router.post("/scan")
def scan_and_add_folder(req: ScanRequest):
    if not os.path.isdir(req.folder_path):
        raise HTTPException(status_code=400,
                            detail=f"Path non trovato: {req.folder_path}")
    # Crea la cartella nel DB se non esiste
    if get_folder_by_path(config.LOCAL_DB, req.folder_path) is None:
        insert_folder(
            config.LOCAL_DB,
            folder_path=req.folder_path,
            display_name=req.display_name,
            default_location_name=req.default_location_name,
            default_latitude=req.default_latitude,
            default_longitude=req.default_longitude,
            auto_analyze=req.auto_analyze,
        )
    result = scan_folder(req.folder_path, db_path=config.LOCAL_DB)
    total    = count_photos(config.LOCAL_DB, folder_path=req.folder_path, is_trash=False)
    analyzed = count_photos(config.LOCAL_DB, folder_path=req.folder_path,
                            analyzed_only=True, is_trash=False)
    update_folder_counts(config.LOCAL_DB, req.folder_path,
                         photo_count=total, analyzed_count=analyzed)
    queued = 0
    if req.auto_analyze:
        unanalyzed = get_photos(config.LOCAL_DB, folder_path=req.folder_path,
                                analyzed_only=False, limit=10000)
        for photo in unanalyzed:
            add_to_queue(config.LOCAL_DB, photo_id=photo["id"], priority=5)
        queued = len(unanalyzed)
    return {"new": result.new, "skipped": result.skipped, "errors": result.errors,
            "queued": queued}


@router.post("/rescan")
def rescan_folder(req: FolderDeleteRequest):
    if not os.path.isdir(req.folder_path):
        raise HTTPException(status_code=400,
                            detail=f"Path non trovato: {req.folder_path}")
    result = scan_folder(req.folder_path, db_path=config.LOCAL_DB)
    total    = count_photos(config.LOCAL_DB, folder_path=req.folder_path, is_trash=False)
    analyzed = count_photos(config.LOCAL_DB, folder_path=req.folder_path,
                            analyzed_only=True, is_trash=False)
    update_folder_counts(config.LOCAL_DB, req.folder_path,
                         photo_count=total, analyzed_count=analyzed)
    return {"new": result.new, "skipped": result.skipped, "errors": result.errors}


@router.put("/meta")
def update_folder_meta(req: FolderUpdateRequest):
    fields = {k: v for k, v in req.model_dump().items()
              if k != "folder_path" and v is not None}
    update_folder(config.LOCAL_DB, req.folder_path, **fields)
    return {"ok": True}


@router.delete("")
def remove_folder(req: FolderDeleteRequest):
    delete_folder(config.LOCAL_DB, req.folder_path)
    return {"ok": True}
