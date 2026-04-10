"""
Entry point FastAPI — Photo AI Manager.
Avvia il server con: uvicorn main:app --host 0.0.0.0 --port 8080
"""
import time
from pathlib import Path

from fastapi import FastAPI

import config
from database.models import init_db

START_TIME = time.time()

from api.settings import router as settings_router

app = FastAPI(
    title="Photo AI Manager",
    version=config.APP_VERSION,
    docs_url="/api/docs",
)

app.include_router(settings_router)

# Startup: inizializza il DB locale
@app.on_event("startup")
async def on_startup():
    Path(config.LOCAL_DB).parent.mkdir(parents=True, exist_ok=True)
    init_db(config.LOCAL_DB)


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
