"""
Entry point FastAPI — Photo AI Manager.
Avvia il server con:
  uvicorn main:app --host 0.0.0.0 --port 8080
"""
import logging
import signal
import time
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from database.models import init_db
from services.db_sync import load_db_from_nas, backup_db_to_nas, prune_old_backups
from api.settings import router as settings_router
from api.folders  import router as folders_router
from api.photos   import router as photos_router
from api.queue    import router as queue_router, set_worker
from api.search   import router as search_router
from api.export   import router as export_router

START_TIME = time.time()

app = FastAPI(
    title="Photo AI Manager",
    version=config.APP_VERSION,
    docs_url="/api/docs",
)

# ── Router API ────────────────────────────────────────────────────
app.include_router(settings_router)
app.include_router(folders_router)
app.include_router(photos_router)
app.include_router(queue_router)
app.include_router(search_router)
app.include_router(export_router)


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

    # 5. Avvia backup periodico con APScheduler
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

    # 6. Backup al SIGTERM
    def _on_sigterm(signum, frame):
        backup_db_to_nas()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _on_sigterm)


@app.on_event("shutdown")
async def on_shutdown():
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown(wait=False)
    backup_db_to_nas()
