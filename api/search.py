"""Route /api/search — ricerca semantica."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import config
from database.settings import get_setting
from services.search import semantic_search, is_quality_query, extract_limit

router = APIRouter(prefix="/api/search", tags=["search"])


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


async def _get_engine():
    from services.ai.gemini import GeminiEngine
    from services.ai.ollama import OllamaEngine

    engine_name = get_setting(config.LOCAL_DB, "ai_engine") or "gemini"
    if engine_name == "ollama":
        base_url = get_setting(config.LOCAL_DB, "ollama_base_url") or "http://localhost:11434"
        vision = get_setting(config.LOCAL_DB, "ollama_vision_model") or "llava"
        embed = get_setting(config.LOCAL_DB, "ollama_embed_model") or "nomic-embed-text"
        return OllamaEngine(vision_model=vision, embed_model=embed, base_url=base_url)
    api_key = get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API key non configurata")
    return GeminiEngine(api_key=api_key)


@router.post("")
async def search_photos(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query non può essere vuota")

    engine = await _get_engine()
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
