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

# URL pubblico da cui l'applicazione e' raggiunta dall'esterno. Dietro un proxy
# (cloudflared) la richiesta arriva al container come http://localhost:8081:
# l'URL dedotto dalla richiesta non coinciderebbe con quello registrato su
# Google, e il login fallirebbe. Vuoto = usa l'URL della richiesta (sviluppo).
PUBLIC_BASE_URL: str = os.environ.get("PUBLIC_BASE_URL", "")

# ── Path dati ─────────────────────────────────────────────────────
APP_DATA_PATH: str = os.environ.get("APP_DATA_PATH", "/mnt/nas/photo_ai_data")

# Root da cui parte il folder browser nell'UI
PHOTOS_PATH: str = os.environ.get("PHOTOS_PATH", "/mnt/nas")

# DB locale sulla VM (SSD virtuale) — usato durante l'esecuzione
LOCAL_DB: str = os.environ.get("LOCAL_DB", "/opt/photo_ai/data/photo_ai.db")

# DB remoto sul NAS — sorgente al boot, destinazione dei backup
REMOTE_DB: str = f"{APP_DATA_PATH}/photo_ai.db"

# Cartella dove vengono caricati i JSON di Google Takeout
TAKEOUT_JSON_PATH: str = os.environ.get("TAKEOUT_JSON_PATH", f"{APP_DATA_PATH}/takeout_json")

# ── Secrets / credenziali (nessun default: devono venire dall'env) ─
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Gemini a pagamento — stessa libreria/modello, chiave con limiti più alti
GEMINI_PAID_API_KEY: str = os.environ.get("GEMINI_PAID_API_KEY", "")
GEMINI_PAID_RPM_LIMIT: int = int(os.environ.get("GEMINI_PAID_RPM_LIMIT", 30))

GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# ── DeepSeek (motore di analisi con visione) ──────────────────────
DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
# DeepSeek ridimensiona comunque le immagini lato server: inviarne di più grandi
# è banda sprecata.
DEEPSEEK_MAX_SIDE_PX: int = int(os.environ.get("DEEPSEEK_MAX_SIDE_PX", 1024))
# deepseek-flash e' un modello di ragionamento: con "enabled" spende migliaia di
# token nella catena di pensiero prima di rispondere (misurati ~6000 per foto,
# contro ~330 di risposta utile), e se il budget si esaurisce prima restituisce
# un contenuto vuoto. "disabled" e' il default perche' per descrivere una foto
# il ragionamento non aggiunge nulla e costa 19 volte tanto.
DEEPSEEK_THINKING: str = os.environ.get("DEEPSEEK_THINKING", "disabled")
DEEPSEEK_MAX_TOKENS: int = int(os.environ.get("DEEPSEEK_MAX_TOKENS", 2000))

# ── Embedding (Ollama / bge-m3) ───────────────────────────────────
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://172.24.24.91:11434")
OLLAMA_EMBED_MODEL: str = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")

# ── Ricerca semantica ─────────────────────────────────────────────
# Soglia assoluta minima: esclude i risultati palesemente estranei.
SEARCH_SIMILARITY_FLOOR: float = float(os.environ.get("SEARCH_SIMILARITY_FLOOR", 0.40))
# Taglio relativo: tiene solo i risultati vicini al migliore della query.
# bge-m3 comprime le similarità in una fascia stretta e il valore assoluto
# dipende dalla formulazione, mentre l'ordinamento interno è affidabile.
SEARCH_RELATIVE_CUTOFF: float = float(os.environ.get("SEARCH_RELATIVE_CUTOFF", 0.90))

# Estensioni da escludere dalla scansione (es. ".cr3,.nef")
EXCLUDED_EXTS: set = {
    e.strip().lower()
    for e in os.environ.get("EXCLUDED_EXTS", "").split(",")
    if e.strip()
}
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

# Lato massimo per Groq (free tier: 500k token/giorno — immagini piccole risparmiano quota)
GROQ_MAX_SIDE_PX: int = int(os.environ.get("GROQ_MAX_SIDE_PX", 768))

# Qualità JPEG di partenza per le immagini inviate all'AI
JPEG_QUALITY: int = int(os.environ.get("JPEG_QUALITY", 85))

# Soglia in KB oltre la quale la qualità viene abbassata automaticamente
TARGET_MAX_KB: int = int(os.environ.get("TARGET_MAX_KB", 800))

# ── Thumbnail UI (§13) ────────────────────────────────────────────
# Lato lungo della thumbnail mostrata nella griglia / lightbox
THUMBNAIL_SIZE: int = int(os.environ.get("THUMBNAIL_SIZE", 400))

# Qualità JPEG della thumbnail UI
THUMBNAIL_QUALITY: int = int(os.environ.get("THUMBNAIL_QUALITY", 82))

# Quante miniature si generano contemporaneamente. Ogni decodifica tiene in
# memoria l'immagine a piena risoluzione — circa 82 MB per uno scan da 24 MP —
# e una griglia da 100 foto le chiede tutte insieme. Senza questo tetto il pool
# di thread di uvicorn ne avvia decine e il container viene ucciso dall'OOM
# killer. Il picco di memoria e' all'incirca questo numero per la foto piu'
# grande della libreria.
THUMBNAIL_MAX_CONCURRENT: int = int(os.environ.get("THUMBNAIL_MAX_CONCURRENT", 4))

# ── Rate limit AI (§6.5) ──────────────────────────────────────────
# Request al minuto verso Gemini gratuito (margine di sicurezza su 15 RPM)
ANALYSIS_RPM_LIMIT: int = int(os.environ.get("ANALYSIS_RPM_LIMIT", 12))

# ── Backup DB (§15) ───────────────────────────────────────────────
# Intervallo in minuti tra i backup automatici del DB sul NAS
BACKUP_INTERVAL_MIN: int = int(os.environ.get("BACKUP_INTERVAL_MIN", 15))

# Numero massimo di backup datati da conservare
BACKUP_RETENTION: int = int(os.environ.get("BACKUP_RETENTION", 10))

# ── Controllo di coerenza geografica ────────────────────────────────────
# Taratura misurata su 1155 foto georeferenziate: 56 segnalazioni (4,8%)
# raggruppate in 47 casi. Fra ±2h e ±24h il numero non cambia quasi —
# il segnale è netto, non un effetto della soglia.
GEO_MAX_GAP_ORE: float = float(os.environ.get("GEO_MAX_GAP_ORE", "2"))
GEO_ACCORDO_KM: float = float(os.environ.get("GEO_ACCORDO_KM", "50"))
GEO_FUORI_SCALA_KM: float = float(os.environ.get("GEO_FUORI_SCALA_KM", "150"))
GEO_RAGGIO_GRUPPO_KM: float = float(os.environ.get("GEO_RAGGIO_GRUPPO_KM", "25"))
GEO_FINESTRA_GRUPPO_ORE: float = float(os.environ.get("GEO_FINESTRA_GRUPPO_ORE", "3"))

# ── Analisi a gruppi ────────────────────────────────────────────────────
# Taratura misurata su 5585 foto con 374 ancore GPS reali: la catena da 15
# minuti produce gruppi la cui dispersione geografica sta entro 1 km nel 100%
# dei casi verificabili. A 10 minuti la dispersione e' identica ma le chiamate
# aumentano di un terzo; a 30 peggiora.
GROUP_ABILITATO: bool = os.environ.get("GROUP_ABILITATO", "1") == "1"
GROUP_GAP_MINUTI: float = float(os.environ.get("GROUP_GAP_MINUTI", "15"))

# Dodici foto per blocco: e' la dimensione a cui le descrizioni restano lunghe
# (617 caratteri mediani misurati). A sedici si accorciano su un gruppo su tre.
GROUP_BLOCCO_FOTO: int = int(os.environ.get("GROUP_BLOCCO_FOTO", "12"))

# Il passo che identifica il luogo campiona otto foto a 320 px: a quella
# risoluzione il modello ha riconosciuto tutti i luoghi di prova con 1700
# token, contro 3750 a risoluzione piena e nessun miglioramento.
GROUP_CAMPIONE_LUOGO: int = int(os.environ.get("GROUP_CAMPIONE_LUOGO", "8"))
GROUP_LUOGO_MAX_SIDE_PX: int = int(os.environ.get("GROUP_LUOGO_MAX_SIDE_PX", "320"))

# Richiesta esplicita di lunghezza: senza, il modello che descrive dodici foto
# insieme si accontenta di 246 caratteri.
GROUP_DESCRIZIONE_MIN_CARATTERI: int = int(
    os.environ.get("GROUP_DESCRIZIONE_MIN_CARATTERI", "350"))
