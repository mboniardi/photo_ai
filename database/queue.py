"""
CRUD per la tabella analysis_queue.
"""
from typing import Optional
from database import get_db


def add_to_queue(
    db_path: Optional[str] = None,
    *,
    photo_id: int,
    priority: int = 5,
) -> int:
    """Aggiunge una foto alla coda. Se già presente (pending/processing), non duplica. Ritorna l'id dell'item."""
    with get_db(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM analysis_queue WHERE photo_id = ? AND status IN ('pending', 'processing')",
            (photo_id,),
        ).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            """
            INSERT INTO analysis_queue (photo_id, priority, status)
            VALUES (?, ?, 'pending')
            """,
            (photo_id, priority),
        )
        return cur.lastrowid


def get_queue_item(db_path: Optional[str], queue_id: int):
    """Ritorna un item della coda per id."""
    with get_db(db_path) as conn:
        return conn.execute(
            "SELECT * FROM analysis_queue WHERE id = ?", (queue_id,)
        ).fetchone()


def get_next_pending(db_path: Optional[str] = None):
    """
    Ritorna il prossimo item in attesa (priorità più bassa = più urgente),
    a parità di priorità FIFO su queued_at.
    Ritorna None se la coda è vuota.
    """
    with get_db(db_path) as conn:
        return conn.execute(
            """
            SELECT * FROM analysis_queue
            WHERE status = 'pending'
            ORDER BY priority ASC, queued_at ASC
            LIMIT 1
            """
        ).fetchone()


def update_queue_status(
    db_path: Optional[str],
    queue_id: int,
    status: str,
    error_msg: Optional[str] = None,
) -> None:
    """Aggiorna lo stato di un item; imposta processed_at se done/error."""
    with get_db(db_path) as conn:
        conn.execute(
            """
            UPDATE analysis_queue
            SET status = ?,
                error_msg = ?,
                processed_at = CASE
                    WHEN ? IN ('done', 'error') THEN datetime('now')
                    ELSE processed_at
                END
            WHERE id = ?
            """,
            (status, error_msg, status, queue_id),
        )


def increment_attempts(db_path: Optional[str], queue_id: int) -> None:
    """Incrementa il contatore dei tentativi per un item."""
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE analysis_queue SET attempts = attempts + 1 WHERE id = ?",
            (queue_id,),
        )


def reset_stale_processing(db_path: Optional[str] = None) -> None:
    """
    Rimette a 'pending' tutti gli item rimasti 'processing'.
    Chiamato all'avvio del server per riprendere dopo un riavvio imprevisto.
    """
    with get_db(db_path) as conn:
        conn.execute(
            "UPDATE analysis_queue SET status = 'pending' WHERE status = 'processing'"
        )


def get_queue_counts(db_path: Optional[str] = None) -> dict:
    """Ritorna un dict con il conteggio per ogni stato."""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM analysis_queue GROUP BY status"
        ).fetchall()
    counts = {"pending": 0, "processing": 0, "done": 0, "error": 0}
    for row in rows:
        counts[row["status"]] = row["cnt"]
    return counts


def clear_queue(db_path: Optional[str] = None) -> int:
    """Rimuove tutti gli item dalla coda (pending ed error). Lascia intatti quelli in processing. Ritorna il numero rimosso."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM analysis_queue WHERE status IN ('pending', 'error')"
        )
        return cur.rowcount


def retry_errors(db_path: Optional[str] = None) -> int:
    """Rimette a 'pending' tutti gli item in errore, azzerando i tentativi. Ritorna il numero di item."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            "UPDATE analysis_queue SET status='pending', attempts=0, error_msg=NULL WHERE status='error'"
        )
        return cur.rowcount


def remove_queue_item(db_path: Optional[str], queue_id: int) -> None:
    """Rimuove un item dalla coda (solo se pending)."""
    with get_db(db_path) as conn:
        conn.execute(
            "DELETE FROM analysis_queue WHERE id = ? AND status = 'pending'",
            (queue_id,),
        )


def add_unanalyzed_to_queue(db_path: Optional[str] = None,
                            *,
                            photo_ids: list,
                            priority: int = 5) -> int:
    """
    Accoda solo le foto che non hanno ancora un'analisi. Ritorna quante.

    Il filtro vive qui, e non nel chiamante, perche' l'analisi AI si paga a
    foto: `api/folders.py` accodava l'intera cartella, rifacendo — e
    rifatturando — descrizioni gia' esistenti. Vale anche per gli id che
    arrivano da una scansione, che includono le foto ripescate dal cestino:
    quelle una descrizione possono gia' averla.
    """
    if not photo_ids:
        return 0
    segnaposto = ",".join("?" * len(photo_ids))
    with get_db(db_path) as conn:
        da_fare = [
            r["id"] for r in conn.execute(
                f"""SELECT id FROM photos
                    WHERE id IN ({segnaposto}) AND analyzed_at IS NULL
                      AND (is_trash = 0 OR is_trash IS NULL)""",
                list(photo_ids),
            )
        ]
    for pid in da_fare:
        add_to_queue(db_path, photo_id=pid, priority=priority)
    return len(da_fare)


def get_pending_photos_for_grouping(db_path: Optional[str] = None) -> list:
    """
    Le foto in attesa, con quel poco che serve per raggrupparle: quando sono
    state scattate, dove stanno su disco, e se hanno gia' una posizione.

    La coda resta per foto: il raggruppamento avviene qui, al prelievo, cosi'
    pausa, ripresa e conteggi continuano a funzionare come prima.

    L'ordine e' cronologico perche' serve a incatenare gli scatti, ma le righe
    portano anche `priority` e `queued_at`: senza, il worker non saprebbe da
    quale foto far partire il gruppo e la priorita' della coda smetterebbe di
    contare (chi preme "analizza ora" accoda con priorita' 1).
    """
    with get_db(db_path) as conn:
        return conn.execute(
            """
            SELECT q.id AS queue_id, q.priority, q.queued_at,
                   p.id AS photo_id, p.exif_date, p.file_path,
                   p.folder_path, p.latitude, p.longitude, p.location_name,
                   p.location_source
            FROM analysis_queue q
            JOIN photos p ON p.id = q.photo_id
            WHERE q.status = 'pending'
              AND (p.is_trash = 0 OR p.is_trash IS NULL)
            ORDER BY p.exif_date, p.id
            """
        ).fetchall()
