"""Route /api/settings — lettura e aggiornamento impostazioni app."""
import logging
from fastapi import APIRouter, HTTPException
from database.settings import get_all_settings, get_setting, set_setting
import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

ALLOWED_KEYS = {
    "ai_engine",
    "gemini_api_key",
    "ollama_base_url",
    "ollama_vision_model",
    "ollama_embed_model",
    "analysis_rpm_limit",
    "backup_interval_min",
    "backup_retention",
    "nas_folder",
}


@router.get("")
def get_settings():
    """Ritorna tutte le impostazioni come dizionario."""
    return get_all_settings(config.LOCAL_DB)


@router.post("/test-ai")
def test_ai_connection():
    """Verifica la connessione al backend AI configurato."""
    engine_name = get_setting(config.LOCAL_DB, "ai_engine") or "gemini"
    try:
        if engine_name == "gemini":
            import google.generativeai as genai
            api_key = get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY
            if not api_key:
                raise ValueError("GEMINI_API_KEY non configurata")
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            model.generate_content("ping")
            return {"ok": True, "message": f"Gemini ({engine_name}) connesso correttamente"}
        else:
            import httpx
            base_url = get_setting(config.LOCAL_DB, "ollama_base_url") or "http://localhost:11434"
            r = httpx.get(f"{base_url}/api/tags", timeout=5)
            r.raise_for_status()
            return {"ok": True, "message": f"Ollama raggiungibile su {base_url}"}
    except Exception as exc:
        logger.error("test-ai failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc))


@router.put("")
def put_settings(body: dict):
    """Aggiorna le impostazioni ricevute. Solo chiavi consentite."""
    unknown = set(body) - ALLOWED_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Chiavi non consentite: {sorted(unknown)}")
    for key, value in body.items():
        set_setting(config.LOCAL_DB, key=key, value=str(value))
    return {"ok": True}
