"""
Entry point FastAPI — Photo AI Manager.
Avvia il server con:
  uvicorn main:app --host 0.0.0.0 --port 8080
"""
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import config
from auth.session import require_auth
from auth.google_oauth import router as auth_router, init_oauth
from database.models import init_db
from services.db_sync import load_db_from_nas, backup_db_to_nas, prune_old_backups
from api.settings import router as settings_router
from api.folders  import router as folders_router
from api.photos   import router as photos_router
from api.queue    import router as queue_router, set_worker
from api.search   import router as search_router
from api.export   import router as export_router
from api.browse   import router as browse_router

START_TIME = time.time()

app = FastAPI(
    title="Photo AI Manager",
    version=config.APP_VERSION,
    docs_url="/api/docs",
)

app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)

# ── Auth Router (public — no require_auth) ────────────────────────
app.include_router(auth_router)

# ── Router API ────────────────────────────────────────────────────
app.include_router(settings_router, dependencies=[Depends(require_auth)])
app.include_router(folders_router,  dependencies=[Depends(require_auth)])
app.include_router(photos_router,   dependencies=[Depends(require_auth)])
app.include_router(queue_router,    dependencies=[Depends(require_auth)])
app.include_router(search_router,   dependencies=[Depends(require_auth)])
app.include_router(export_router,   dependencies=[Depends(require_auth)])
app.include_router(browse_router,   dependencies=[Depends(require_auth)])


# ── Health ────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    """Readiness check usato dallo script di deploy (§16)."""
    db_ok  = Path(config.LOCAL_DB).exists()
    nas_ok = Path(config.APP_DATA_PATH).exists()
    return {
        "status":   "ok" if (db_ok and nas_ok) else "degraded",
        "db":       "ok" if db_ok  else "missing",
        "nas":      "ok" if nas_ok else "not_mounted",
        "version":  config.APP_VERSION,
        "uptime_s": int(time.time() - START_TIME),
    }


# ── Static files (SPA Vue 3 — Fase 5) ────────────────────────────
# IMPORTANT: Mount at the end so it doesn't shadow /health or /api/* routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# ── Lifecycle ─────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    # 0. Fail fast if SECRET_KEY is not configured
    if not config.SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY non configurata. Imposta la variabile d'ambiente SECRET_KEY."
        )

    # 0b. Initialize OAuth with current config values
    init_oauth()

    # 1. Prepara directory locale
    Path(config.LOCAL_DB).parent.mkdir(parents=True, exist_ok=True)

    # 2. Carica DB dal NAS (se disponibile)
    loaded = load_db_from_nas()
    if loaded:
        print(f"DB caricato dal NAS: {config.REMOTE_DB}")
    else:
        print("DB non trovato sul NAS — avvio con database vuoto")

    # 3. Inizializza schema (idempotente)
    init_db(config.LOCAL_DB)

    # 4. Reset item bloccati in 'processing' (riavvio imprevisto)
    from database.queue import reset_stale_processing
    reset_stale_processing(config.LOCAL_DB)

    # 5. Carica whitelist email autorizzate
    from auth.whitelist import load_whitelist
    app.state.whitelist = load_whitelist(config.AUTHORIZED_EMAILS_PATH)
    print(f"Whitelist caricata: {len(app.state.whitelist)} email autorizzate")

    # 6. Avvia backup periodico con APScheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from services.db_sync import backup_db_to_nas as _backup
    import os
    backup_dir = os.path.join(os.path.dirname(config.REMOTE_DB), "photo_ai.db.backup")

    def _backup_and_prune():
        backup_db_to_nas()
        prune_old_backups(backup_dir, keep=config.BACKUP_RETENTION)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _backup_and_prune,
        "interval",
        minutes=config.BACKUP_INTERVAL_MIN,
        id="db_backup",
    )
    try:
        scheduler.start()
        app.state.scheduler = scheduler
    except Exception as exc:
        logger.warning("APScheduler non avviato: %s", exc)

    # 7. Avvia il QueueWorker AI
    from services.queue_worker import QueueWorker
    from database.settings import get_setting

    engine_name = get_setting(config.LOCAL_DB, "ai_engine") or "gemini"
    try:
        if engine_name == "gemini":
            from services.ai.gemini import GeminiEngine
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
            embed_model  = get_setting(config.LOCAL_DB, "ollama_embed_model")  or "nomic-embed-text"
            engine = OllamaEngine(base_url=base_url, vision_model=vision_model, embed_model=embed_model)

        rpm = int(get_setting(config.LOCAL_DB, "analysis_rpm_limit") or config.ANALYSIS_RPM_LIMIT)
        worker = QueueWorker(engine=engine, db_path=config.LOCAL_DB, rpm_limit=rpm)
        await worker.start()
        set_worker(worker)
        app.state.worker = worker
        print(f"QueueWorker avviato (engine={engine_name}, rpm={rpm})")
    except Exception as exc:
        logger.warning("QueueWorker non avviato: %s", exc)

    # 8. SIGTERM handled by uvicorn — on_shutdown below does the backup


@app.on_event("shutdown")
async def on_shutdown():
    if hasattr(app.state, "worker"):
        await app.state.worker.stop()
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown(wait=False)
    try:
        backup_db_to_nas()
    except Exception as exc:
        logger.warning("Backup DB al shutdown fallito: %s", exc)
