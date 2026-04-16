"""Route /api/search — ricerca semantica."""
import json
import logging
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

import config
from database.settings import get_setting
from services.search import semantic_search, is_quality_query, extract_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

# Stato re-indicizzazione (modulo-level, condiviso tra richieste)
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


async def _get_embed_engine():
    """
    Usa Gemini (text-embedding-004) per gli embedding — gratuito, sempre disponibile.
    Fallback a Ollama se Gemini non è configurato.
    """
    from services.ai.gemini import GeminiEngine

    engine_name = get_setting(config.LOCAL_DB, "ai_engine") or "gemini"
    if engine_name == "gemini_paid":
        api_key = (get_setting(config.LOCAL_DB, "gemini_paid_api_key") or config.GEMINI_PAID_API_KEY
                   or get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY)
    else:
        api_key = (get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY
                   or get_setting(config.LOCAL_DB, "gemini_paid_api_key") or config.GEMINI_PAID_API_KEY)

    if api_key:
        return GeminiEngine(api_key=api_key)

    # Fallback: Ollama locale
    from services.ai.ollama import OllamaEngine
    base_url    = get_setting(config.LOCAL_DB, "ollama_base_url")  or "http://localhost:11434"
    embed_model = get_setting(config.LOCAL_DB, "ollama_embed_model") or "nomic-embed-text"
    return OllamaEngine(base_url=base_url, embed_model=embed_model)


@router.post("")
async def search_photos(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query non può essere vuota")

    engine = await _get_embed_engine()
    from services.ai.gemini import GeminiEngine
    if isinstance(engine, GeminiEngine):
        query_embedding = await engine.embed(req.query, task_type="RETRIEVAL_QUERY")
    else:
        query_embedding = await engine.embed(req.query)

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
    """Stato della ri-indicizzazione in corso."""
    return _reembed_state


@router.post("/reembed")
async def reembed_all(background_tasks: BackgroundTasks):
    """
    Ri-genera gli embedding di tutte le foto analizzate usando Ollama.
    Operazione una-tantum; necessaria quando si passa a un nuovo modello embedding.
    """
    global _reembed_state
    if _reembed_state["running"]:
        raise HTTPException(status_code=409, detail="Re-indicizzazione già in corso")

    engine = await _get_embed_engine()
    background_tasks.add_task(_do_reembed, engine)
    return {"ok": True, "message": "Re-indicizzazione avviata in background"}


async def _do_reembed(engine) -> None:
    """Task in background: ri-embeds tutte le foto analizzate."""
    global _reembed_state
    import sqlite3
    from database.photos import update_photo

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

        for row in rows:
            embed_text = " ".join(filter(None, [
                row["description"],
                row["subject"],
                row["atmosphere"],
                row["location_name"],
            ]))
            if not embed_text.strip():
                _reembed_state["done"] += 1
                continue
            try:
                embedding = await engine.embed(embed_text)
                update_photo(config.LOCAL_DB, row["id"], embedding=json.dumps(embedding))
            except Exception as exc:
                logger.warning("reembed fallito per photo_id=%s: %s", row["id"], exc)
            _reembed_state["done"] += 1
            # Cede il controllo per non bloccare altri handler
            await asyncio.sleep(0)

    except Exception as exc:
        logger.error("reembed globale fallito: %s", exc)
        _reembed_state["error"] = str(exc)
    finally:
        _reembed_state["running"] = False
