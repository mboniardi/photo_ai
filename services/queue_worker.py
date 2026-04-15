"""
Worker asincrono per la coda di analisi AI (§6.5).
- Un solo job alla volta (nessuna concorrenza verso l'AI)
- Rate limiter configurabile (default 12 RPM per Gemini gratuito)
- Retry automatico fino a MAX_ATTEMPTS
- Sopravvive ai riavvii: reset_stale_processing() all'avvio
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

from services.ai.base import AIEngine
from services.image_processor import prepare_for_ai
from database.queue import (
    get_next_pending, update_queue_status,
    increment_attempts, get_queue_item, reset_stale_processing,
)
from database.photos import get_photo_by_id, update_photo
import config

MAX_ATTEMPTS = 3


class QueueWorker:
    """
    Worker che consuma la coda analysis_queue.
    Chiamare start() per avviare il loop asincrono,
    stop() per fermarsi, pause()/resume() per sospendere.
    """

    def __init__(
        self,
        engine: AIEngine,
        db_path: Optional[str] = None,
        rpm_limit: Optional[int] = None,
    ):
        self._engine   = engine
        self._db_path  = db_path
        self._rpm      = rpm_limit  # None = nessun limite (Ollama)
        self.is_running = False
        self.is_paused  = False
        self._task: Optional[asyncio.Task] = None
        self.current_photo_name: Optional[str] = None

    async def start(self) -> None:
        """Avvia il loop del worker in background."""
        self.is_running = True
        reset_stale_processing(self._db_path)
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Ferma il worker."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def pause(self) -> None:
        self.is_paused = True

    def resume(self) -> None:
        self.is_paused = False

    async def process_next(self) -> bool:
        """
        Processa il prossimo item pending dalla coda.
        Ritorna True se ha processato qualcosa, False se la coda era vuota.
        """
        item = get_next_pending(self._db_path)
        if item is None:
            return False

        qid      = item["id"]
        photo_id = item["photo_id"]
        attempts = item["attempts"]

        # Skippa se ha già raggiunto il limite tentativi
        if attempts >= MAX_ATTEMPTS:
            update_queue_status(self._db_path, qid, "error",
                                error_msg="Superato limite tentativi")
            return True

        photo = get_photo_by_id(self._db_path, photo_id)
        if photo is None:
            update_queue_status(self._db_path, qid, "error",
                                error_msg="Foto non trovata nel DB")
            return True

        update_queue_status(self._db_path, qid, "processing")
        self.current_photo_name = photo["filename"]

        try:
            # Prepara immagine per AI
            image_bytes = prepare_for_ai(photo["file_path"])

            # Location hint se disponibile
            location_hint = photo["location_name"] or ""

            # Analisi AI
            analysis = await self._engine.analyze(image_bytes, location_hint)

            # Embedding: testo = descrizione + soggetto + atmosfera + luogo
            # Non bloccante: se il modello embedding non è disponibile
            # la foto viene comunque analizzata con descrizione e punteggi.
            embed_text = " ".join(filter(None, [
                analysis.description,
                analysis.subject,
                analysis.atmosphere,
                analysis.location_name or photo["location_name"],
            ]))
            try:
                embedding = await self._engine.embed(embed_text)
            except Exception as emb_exc:
                logger.warning("Embedding non disponibile per photo_id=%s: %s", photo_id, emb_exc)
                embedding = []

            # Aggiorna la foto nel DB
            update_photo(
                self._db_path,
                photo_id,
                description=analysis.description,
                technical_score=analysis.technical_score,
                aesthetic_score=analysis.aesthetic_score,
                overall_score=analysis.overall_score,
                subject=analysis.subject,
                atmosphere=analysis.atmosphere,
                colors=json.dumps(analysis.colors, ensure_ascii=False),
                strengths=analysis.strengths,
                weaknesses=analysis.weaknesses,
                ai_engine=analysis.ai_engine,
                embedding=json.dumps(embedding),
                analyzed_at=datetime.now().isoformat(timespec="seconds"),
            )

            # Se l'AI ha riconosciuto un luogo e la foto non ne aveva uno
            if analysis.location_name and not photo["location_name"]:
                update_photo(
                    self._db_path,
                    photo_id,
                    location_name=analysis.location_name,
                    latitude=analysis.latitude,
                    longitude=analysis.longitude,
                    location_source="ai",
                )

            update_queue_status(self._db_path, qid, "done")

        except Exception as e:
            logger.warning("Errore analisi photo_id=%s qid=%s: %s", photo_id, qid, e)
            increment_attempts(self._db_path, qid)
            current = get_queue_item(self._db_path, qid)
            if current["attempts"] >= MAX_ATTEMPTS:
                update_queue_status(self._db_path, qid, "error",
                                    error_msg=str(e)[:500])
            else:
                update_queue_status(self._db_path, qid, "pending")
                # Backoff esponenziale su errori temporanei (503, 429)
                err_str = str(e)
                if "503" in err_str or "429" in err_str:
                    delay = 30 * (2 ** (current["attempts"] - 1))  # 30s, 60s
                    logger.info("Backoff %ss per errore temporaneo (qid=%s)", delay, qid)
                    await asyncio.sleep(delay)

        finally:
            self.current_photo_name = None

        return True

    async def _run_loop(self) -> None:
        """Loop principale: consuma la coda rispettando il rate limit."""
        while self.is_running:
            if self.is_paused:
                await asyncio.sleep(2)
                continue

            t_start = time.monotonic()
            processed = await self.process_next()

            if not processed:
                await asyncio.sleep(5)  # coda vuota: riprova tra 5s
                continue

            if self._rpm:
                # Rispetta il rate limit: attendi il tempo residuo nel minuto
                elapsed = time.monotonic() - t_start
                interval = 60.0 / self._rpm
                wait = max(0.0, interval - elapsed)
                if wait > 0:
                    await asyncio.sleep(wait)
