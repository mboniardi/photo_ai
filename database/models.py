"""
Schema SQLite e inizializzazione del database.
Tutte le CREATE TABLE usano IF NOT EXISTS: init_db() è idempotente.
"""
from typing import Optional
from database import get_db


def init_db(db_path: Optional[str] = None) -> None:
    """
    Crea tutte le tabelle se non esistono ancora.
    Abilita WAL mode e foreign keys.
    Sicuro da chiamare più volte (idempotente).
    """
    with get_db(db_path) as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            -- ── Tabella principale foto ──────────────────────────────────
            CREATE TABLE IF NOT EXISTS photos (
              id               INTEGER PRIMARY KEY AUTOINCREMENT,
              file_path        TEXT UNIQUE NOT NULL,
              folder_path      TEXT NOT NULL,
              filename         TEXT NOT NULL,
              format           TEXT,

              -- Metadati EXIF
              exif_date        TEXT,
              width            INTEGER,
              height           INTEGER,
              exif_orientation INTEGER,
              file_size        INTEGER,
              camera_make      TEXT,
              camera_model     TEXT,
              lens_model       TEXT,
              focal_length     REAL,
              aperture         REAL,
              shutter_speed    TEXT,
              iso              INTEGER,

              -- Geolocalizzazione
              latitude         REAL,
              longitude        REAL,
              location_name    TEXT,
              location_source  TEXT,

              -- Analisi AI
              description      TEXT,
              technical_score  REAL,
              aesthetic_score  REAL,
              overall_score    REAL,
              subject          TEXT,
              atmosphere       TEXT,
              colors           TEXT,
              strengths        TEXT,
              weaknesses       TEXT,
              ai_engine        TEXT,
              embedding        TEXT,
              analyzed_at      TEXT,

              -- Flag utente
              is_favorite      INTEGER DEFAULT 0,
              is_trash         INTEGER DEFAULT 0,
              user_description TEXT,

              created_at       TEXT DEFAULT (datetime('now')),
              updated_at       TEXT DEFAULT (datetime('now'))
            );

            -- ── Indici per query frequenti (§10 Performance) ─────────────
            CREATE INDEX IF NOT EXISTS idx_photos_folder
                ON photos(folder_path);
            CREATE INDEX IF NOT EXISTS idx_photos_score
                ON photos(overall_score);
            CREATE INDEX IF NOT EXISTS idx_photos_favorite
                ON photos(is_favorite);
            CREATE INDEX IF NOT EXISTS idx_photos_analyzed
                ON photos(analyzed_at);

            -- ── Cartelle indicizzate ──────────────────────────────────────
            CREATE TABLE IF NOT EXISTS folders (
              id                    INTEGER PRIMARY KEY AUTOINCREMENT,
              folder_path           TEXT UNIQUE NOT NULL,
              display_name          TEXT,
              default_location_name TEXT,
              default_latitude      REAL,
              default_longitude     REAL,
              photo_count           INTEGER DEFAULT 0,
              analyzed_count        INTEGER DEFAULT 0,
              last_scanned          TEXT,
              auto_analyze          INTEGER DEFAULT 0
            );

            -- ── Coda analisi AI ───────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS analysis_queue (
              id           INTEGER PRIMARY KEY AUTOINCREMENT,
              photo_id     INTEGER NOT NULL REFERENCES photos(id),
              priority     INTEGER DEFAULT 5,
              status       TEXT DEFAULT 'pending',
              error_msg    TEXT,
              attempts     INTEGER DEFAULT 0,
              queued_at    TEXT DEFAULT (datetime('now')),
              processed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_queue_status_priority
                ON analysis_queue(status, priority, queued_at);

            -- ── Impostazioni applicazione ─────────────────────────────────
            CREATE TABLE IF NOT EXISTS settings (
              key   TEXT PRIMARY KEY,
              value TEXT
            );
        """)
