"""Route /api/settings — lettura e aggiornamento impostazioni app."""
from fastapi import APIRouter, HTTPException
from database.settings import get_all_settings, set_setting
import config

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


@router.put("")
def put_settings(body: dict):
    """Aggiorna le impostazioni ricevute. Solo chiavi consentite."""
    unknown = set(body) - ALLOWED_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Chiavi non consentite: {sorted(unknown)}")
    for key, value in body.items():
        set_setting(config.LOCAL_DB, key=key, value=str(value))
    return {"ok": True}
