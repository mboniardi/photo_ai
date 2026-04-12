"""
Configurazione centralizzata dell'applicazione.
Tutti i valori leggono prima da variabili d'ambiente,
poi usano il default indicato nella specifica.
"""
import os

# ── Versione ──────────────────────────────────────────────────────
APP_VERSION = "0.1.0"

# ── Rete ──────────────────────────────────────────────────────────
APP_PORT: int = int(os.environ.get("APP_PORT", 8080))

# ── Path dati ─────────────────────────────────────────────────────
APP_DATA_PATH: str = os.environ.get("APP_DATA_PATH", "/mnt/nas/photo_ai_data")

# Root da cui parte il folder browser nell'UI
PHOTOS_PATH: str = os.environ.get("PHOTOS_PATH", "/mnt/nas")

# DB locale sulla VM (SSD virtuale) — usato durante l'esecuzione
LOCAL_DB: str = os.environ.get("LOCAL_DB", "/opt/photo_ai/data/photo_ai.db")

# DB remoto sul NAS — sorgente al boot, destinazione dei backup
REMOTE_DB: str = f"{APP_DATA_PATH}/photo_ai.db"

# ── Secrets / credenziali (nessun default: devono venire dall'env) ─
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GOOGLE_CLIENT_ID: str = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.environ.get("GOOGLE_CLIENT_SECRET", "")
SECRET_KEY: str = os.environ.get("SECRET_KEY", "")

# Path whitelist email (§14)
AUTHORIZED_EMAILS_PATH: str = os.environ.get(
    "AUTHORIZED_EMAILS_PATH",
    f"{APP_DATA_PATH}/authorized_emails.txt",
)

# ── Ottimizzazione immagini per AI (§13) ──────────────────────────
# Lato massimo (px) a cui viene ridimensionata l'immagine prima di inviarla all'AI
MAX_SIDE_PX: int = int(os.environ.get("MAX_SIDE_PX", 1280))

# Qualità JPEG di partenza per le immagini inviate all'AI
JPEG_QUALITY: int = int(os.environ.get("JPEG_QUALITY", 85))

# Soglia in KB oltre la quale la qualità viene abbassata automaticamente
TARGET_MAX_KB: int = int(os.environ.get("TARGET_MAX_KB", 800))

# ── Thumbnail UI (§13) ────────────────────────────────────────────
# Lato lungo della thumbnail mostrata nella griglia / lightbox
THUMBNAIL_SIZE: int = int(os.environ.get("THUMBNAIL_SIZE", 400))

# Qualità JPEG della thumbnail UI
THUMBNAIL_QUALITY: int = int(os.environ.get("THUMBNAIL_QUALITY", 82))

# ── Rate limit AI (§6.5) ──────────────────────────────────────────
# Request al minuto verso Gemini gratuito (margine di sicurezza su 15 RPM)
ANALYSIS_RPM_LIMIT: int = int(os.environ.get("ANALYSIS_RPM_LIMIT", 12))

# ── Backup DB (§15) ───────────────────────────────────────────────
# Intervallo in minuti tra i backup automatici del DB sul NAS
BACKUP_INTERVAL_MIN: int = int(os.environ.get("BACKUP_INTERVAL_MIN", 15))

# Numero massimo di backup datati da conservare
BACKUP_RETENTION: int = int(os.environ.get("BACKUP_RETENTION", 10))
