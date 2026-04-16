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
    "gemini_paid_api_key",
    "groq_api_key",
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
        if engine_name in ("gemini", "gemini_paid"):
            from google import genai
            if engine_name == "gemini_paid":
                api_key = get_setting(config.LOCAL_DB, "gemini_paid_api_key") or config.GEMINI_PAID_API_KEY
                label = "Gemini paid"
            else:
                api_key = get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY
                label = "Gemini free"
            if not api_key:
                raise ValueError(f"{label.upper().replace(' ','_')}_API_KEY non configurata")
            client = genai.Client(api_key=api_key)
            client.models.generate_content(model=config.GEMINI_MODEL, contents=["ping"])
            return {"ok": True, "message": f"{label} ({config.GEMINI_MODEL}) connesso correttamente"}
        elif engine_name == "groq":
            from groq import Groq
            api_key = get_setting(config.LOCAL_DB, "groq_api_key") or config.GROQ_API_KEY
            if not api_key:
                raise ValueError("GROQ_API_KEY non configurata")
            client = Groq(api_key=api_key)
            client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return {"ok": True, "message": f"Groq ({config.GROQ_MODEL}) connesso correttamente"}
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
async def put_settings(body: dict):
    """Aggiorna le impostazioni ricevute. Solo chiavi consentite."""
    unknown = set(body) - ALLOWED_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail=f"Chiavi non consentite: {sorted(unknown)}")
    for key, value in body.items():
        set_setting(config.LOCAL_DB, key=key, value=str(value))

    # Se cambia il motore AI o la sua chiave, ricrea e riavvia il worker
    engine_keys = {"ai_engine", "gemini_api_key", "gemini_paid_api_key", "groq_api_key",
                   "ollama_base_url", "ollama_vision_model", "ollama_embed_model"}
    if body.keys() & engine_keys:
        await _restart_worker()

    return {"ok": True}


async def _restart_worker():
    """Ferma il worker corrente e ne avvia uno nuovo con le impostazioni aggiornate."""
    from api.queue import get_worker, set_worker
    from services.queue_worker import QueueWorker

    old_worker = get_worker()
    if old_worker:
        await old_worker.stop()

    engine_name = get_setting(config.LOCAL_DB, "ai_engine") or "gemini"
    try:
        if engine_name in ("gemini", "gemini_paid"):
            from services.ai.gemini import GeminiEngine
            if engine_name == "gemini_paid":
                api_key = get_setting(config.LOCAL_DB, "gemini_paid_api_key") or config.GEMINI_PAID_API_KEY
            else:
                api_key = get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY
            engine = GeminiEngine(api_key=api_key)
        elif engine_name == "groq":
            from services.ai.groq_engine import GroqEngine
            api_key = get_setting(config.LOCAL_DB, "groq_api_key") or config.GROQ_API_KEY
            engine = GroqEngine(api_key=api_key)
        else:
            from services.ai.ollama import OllamaEngine
            base_url = get_setting(config.LOCAL_DB, "ollama_base_url") or "http://localhost:11434"
            vision_model = get_setting(config.LOCAL_DB, "ollama_vision_model") or "llava"
            embed_model  = get_setting(config.LOCAL_DB, "ollama_embed_model") or "nomic-embed-text"
            engine = OllamaEngine(base_url=base_url, vision_model=vision_model, embed_model=embed_model)

        rpm = int(get_setting(config.LOCAL_DB, "analysis_rpm_limit") or config.ANALYSIS_RPM_LIMIT)
        worker = QueueWorker(engine=engine, db_path=config.LOCAL_DB, rpm_limit=rpm)
        await worker.start()
        set_worker(worker)
        logger.info("Worker riavviato con engine=%s", engine_name)
    except Exception as exc:
        logger.error("Impossibile riavviare il worker: %s", exc)
