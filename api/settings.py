"""Route /api/settings — lettura e aggiornamento impostazioni app."""
from fastapi import APIRouter
from database.settings import get_all_settings, set_setting
import config

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings():
    """Ritorna tutte le impostazioni come dizionario."""
    return get_all_settings(config.LOCAL_DB)


@router.put("")
def put_settings(body: dict):
    """Aggiorna le impostazioni ricevute. Valori come stringhe."""
    for key, value in body.items():
        set_setting(config.LOCAL_DB, key=key, value=str(value))
    return {"ok": True}
