"""Route /api/queue — gestione coda analisi AI."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from database.queue import (
    add_to_queue, get_queue_counts, remove_queue_item,
    get_next_pending,
)
from database.photos import get_photos, count_photos
import config

router = APIRouter(prefix="/api/queue", tags=["queue"])

# Riferimento globale al worker (impostato da main.py al startup)
_worker = None


def set_worker(worker) -> None:
    global _worker
    _worker = worker


class AddRequest(BaseModel):
    photo_ids: list
    priority: int = 5


class FolderQueueRequest(BaseModel):
    folder_path: str
    priority: int = 5


class DeleteRequest(BaseModel):
    folder_path: str


@router.get("/status")
def queue_status():
    counts = get_queue_counts(config.LOCAL_DB)
    return {
        **counts,
        "is_running": _worker.is_running if _worker else False,
        "is_paused":  _worker.is_paused  if _worker else False,
        "current_photo": _worker.current_photo_name if _worker else None,
    }


@router.post("/add")
def add_photos_to_queue(req: AddRequest):
    added = 0
    for pid in req.photo_ids:
        add_to_queue(config.LOCAL_DB, photo_id=pid, priority=req.priority)
        added += 1
    return {"added": added}


@router.post("/add-folder")
def add_folder_to_queue(req: FolderQueueRequest):
    photos = get_photos(
        config.LOCAL_DB,
        folder_path=req.folder_path,
        analyzed_only=False,
        limit=100000,
    )
    added = 0
    for photo in photos:
        if photo["analyzed_at"] is None:
            add_to_queue(config.LOCAL_DB,
                         photo_id=photo["id"],
                         priority=req.priority)
            added += 1
    return {"added": added}


@router.post("/pause")
def pause_queue():
    if _worker:
        _worker.pause()
    return {"ok": True}


@router.post("/resume")
def resume_queue():
    if _worker:
        _worker.resume()
    return {"ok": True}


@router.delete("/{queue_id}")
def delete_queue_item(queue_id: int):
    remove_queue_item(config.LOCAL_DB, queue_id)
    return {"ok": True}
