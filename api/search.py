"""Route /api/search — ricerca semantica via query expansion."""
import json
import logging
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

import config
from database.settings import get_setting
from services.search import text_search, is_quality_query, extract_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

# Stato re-indicizzazione (non più usato per embedding, mantenuto per compatibilità UI)
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


async def _expand_query(query: str) -> list[str]:
    """
    Usa Gemini per espandere la query in parole chiave italiane
    che potrebbero apparire nelle descrizioni delle foto.
    Ritorna una lista di parole chiave (minuscolo).
    """
    from services.ai.gemini import GeminiEngine

    engine_name = get_setting(config.LOCAL_DB, "ai_engine") or "gemini"
    if engine_name == "gemini_paid":
        api_key = (get_setting(config.LOCAL_DB, "gemini_paid_api_key") or config.GEMINI_PAID_API_KEY
                   or get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY)
    else:
        api_key = (get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY
                   or get_setting(config.LOCAL_DB, "gemini_paid_api_key") or config.GEMINI_PAID_API_KEY)

    if not api_key:
        # Nessuna chiave: usa le parole della query direttamente
        return [w.strip().lower() for w in query.split() if len(w.strip()) > 2]

    try:
        from google import genai
        import asyncio
        client = genai.Client(api_key=api_key)
        prompt = (
            f'Sei un assistente per la ricerca in una libreria fotografica. '
            f'Espandi questa query di ricerca in una lista di parole chiave italiane '
            f'(o inglesi se il termine è più comune in inglese) che potrebbero apparire '
            f'nelle descrizioni di foto. Restituisci SOLO una lista JSON di stringhe, '
            f'nessun altro testo. Massimo 15 parole chiave.\n'
            f'Query: "{query}"'
        )
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt],
            )
        )
        text = response.text.strip()
        # Rimuovi eventuali code fence
        import re
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
        keywords = json.loads(text.strip())
        if isinstance(keywords, list):
            result = [str(k).lower().strip() for k in keywords if k]
            logger.info("Query expansion '%s' → %s", query, result)
            return result
    except Exception as exc:
        logger.warning("Query expansion fallita (%s), uso parole della query", exc)

    return [w.strip().lower() for w in query.split() if len(w.strip()) > 2]


@router.post("")
async def search_photos(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query non può essere vuota")

    keywords = await _expand_query(req.query)
    if not keywords:
        return []

    is_quality = is_quality_query(req.query)
    limit = req.limit if req.limit is not None else extract_limit(req.query)
    is_trash = req.is_trash if req.is_trash is not None else False

    return text_search(
        config.LOCAL_DB,
        keywords=keywords,
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
    """No-op: embedding non più necessario con ricerca a query expansion."""
    return {"ok": True, "message": "La ricerca usa query expansion — nessuna indicizzazione necessaria."}
