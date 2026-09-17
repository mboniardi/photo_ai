"""Route /api/search — ricerca semantica con embedding tramite Embedder."""
import json
import logging
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

import config
from services.search import semantic_search, is_quality_query, extract_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

_reembed_state: dict = {"running": False, "done": 0, "total": 0, "error": None}


class SearchRequest(BaseModel):
    query: str
    folder_path: Optional[str] = None
    is_favorite: Optional[bool] = None
    is_trash: Optional[bool] = None
    min_score: Optional[float] = None
    format: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    location: Optional[str] = None
    orientation: Optional[str] = None
    limit: Optional[int] = None


def get_embedder():
    """Fabbrica dell'embedder. Sostituita nei test tramite monkeypatch."""
    from services.embedding import OllamaEmbedder
    return OllamaEmbedder()


@router.post("")
async def search_photos(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query non può essere vuota")

    embedder = get_embedder()
    try:
        query_embedding = await embedder.embed(req.query)
    except Exception as exc:
        logger.error("Embedding della query fallito: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Servizio di embedding non raggiungibile — controlla che Ollama sia attivo",
        )

    if not query_embedding:
        raise HTTPException(status_code=503, detail="Embedding non disponibile")

    is_quality = is_quality_query(req.query)
    limit = req.limit if req.limit is not None else extract_limit(req.query)
    is_trash = req.is_trash if req.is_trash is not None else False

    return semantic_search(
        config.LOCAL_DB,
        query_embedding,
        is_quality=is_quality,
        limit=limit,
        folder_path=req.folder_path,
        is_favorite=req.is_favorite,
        is_trash=is_trash,
        min_score=req.min_score,
        format=req.format,
        date_from=req.date_from,
        date_to=req.date_to,
        location=req.location,
        orientation=req.orientation,
    )


@router.get("/reembed/status")
def reembed_status():
    return _reembed_state


@router.post("/reembed")
async def reembed_all(background_tasks: BackgroundTasks):
    global _reembed_state
    if _reembed_state["running"]:
        raise HTTPException(status_code=409, detail="Re-indicizzazione già in corso")
    embedder = get_embedder()
    background_tasks.add_task(_do_reembed, embedder)
    return {"ok": True, "message": "Re-indicizzazione avviata in background"}


REEMBED_BATCH_SIZE = 32


async def _do_reembed(embedder) -> None:
    global _reembed_state
    import sqlite3

    _reembed_state = {"running": True, "done": 0, "total": 0, "error": None}
    try:
        conn = sqlite3.connect(config.LOCAL_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, description, subject, atmosphere, location_name "
            "FROM photos WHERE analyzed_at IS NOT NULL"
        ).fetchall()
        conn.close()

        _reembed_state["total"] = len(rows)

        batch_ids, batch_texts = [], []
        for row in rows:
            text = " ".join(filter(None, [
                row["description"], row["subject"],
                row["atmosphere"], row["location_name"],
            ])).strip()
            if not text:
                _reembed_state["done"] += 1
                continue
            batch_ids.append(row["id"])
            batch_texts.append(text)

            if len(batch_texts) >= REEMBED_BATCH_SIZE:
                await _flush_batch(embedder, batch_ids, batch_texts)
                batch_ids, batch_texts = [], []

        if batch_texts:
            await _flush_batch(embedder, batch_ids, batch_texts)

    except Exception as exc:
        logger.error("reembed globale fallito: %s", exc)
        _reembed_state["error"] = str(exc)
    finally:
        _reembed_state["running"] = False


async def _flush_batch(embedder, ids: list, texts: list) -> None:
    """Vettorizza un lotto e salva. Un lotto fallito non ferma gli altri."""
    from database.photos import update_photo
    try:
        vectors = await embedder.embed_batch(texts)
    except Exception as exc:
        logger.warning("reembed fallito per il lotto di %d foto: %s", len(ids), exc)
        _reembed_state["done"] += len(ids)
        return
    for photo_id, vector in zip(ids, vectors):
        update_photo(config.LOCAL_DB, photo_id, embedding=json.dumps(vector))
        _reembed_state["done"] += 1
    await asyncio.sleep(0)
