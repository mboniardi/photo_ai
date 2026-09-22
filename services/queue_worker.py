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
import re
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

from services.ai.base import AIEngine
from services.image_processor import prepare_for_ai
from database.queue import (
    get_next_pending, update_queue_status,
    increment_attempts, get_queue_item, reset_stale_processing,
    get_pending_photos_for_grouping,
)
from database.photos import get_photo_by_id, update_photo
from services.photo_grouping import ORIGINI_AFFIDABILI, prepara, gruppo_di
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
        embedder=None,
    ):
        self._engine    = engine
        self._embedder  = embedder
        self._db_path   = db_path
        self._rpm       = rpm_limit  # None = nessun limite
        self.is_running = False
        self.is_paused  = False
        self._task: Optional[asyncio.Task] = None
        self.current_photo_name: Optional[str] = None
        self._transient_pause_until: float = 0.0

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
            # Prepara immagine per AI (risoluzione dipende dall'engine)
            image_bytes = prepare_for_ai(photo["file_path"],
                                         max_side_px=self._engine.max_side_px)

            # Location hint: nome luogo noto + coordinate GPS se disponibili
            parts = []
            if photo["location_name"]:
                parts.append(photo["location_name"])
            if photo["latitude"] and photo["longitude"]:
                parts.append(f"coordinate GPS: {photo['latitude']:.4f}, {photo['longitude']:.4f}")
            location_hint = " — ".join(parts)

            # Analisi AI
            analysis = await self._engine.analyze(image_bytes, location_hint)

            embed_text = " ".join(filter(None, [
                analysis.description,
                analysis.subject,
                analysis.atmosphere,
                analysis.location_name or photo["location_name"],
            ]))
            embedding = []
            if self._embedder is not None:
                try:
                    embedding = await self._embedder.embed(embed_text)
                except Exception as emb_exc:
                    logger.warning(
                        "Embedding non disponibile per photo_id=%s: %s",
                        photo_id, emb_exc,
                    )

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

            # La guardia è sulle COORDINATE, non sul nome: una posizione che
            # viene da un GPS EXIF, da una scelta dell'utente o da una
            # correzione manuale vale più di un'ipotesi dell'AI, ma queste
            # posizioni affidabili quasi mai hanno un location_name
            # valorizzato — una guardia sul nome non le protegge affatto.
            if photo["latitude"] is None:
                # Nessuna coordinata pregressa: l'AI può proporre tutto
                # (nome, coordinate e origine) — comportamento invariato.
                if analysis.location_name:
                    update_photo(
                        self._db_path,
                        photo_id,
                        location_name=analysis.location_name,
                        latitude=analysis.latitude,
                        longitude=analysis.longitude,
                        location_source="ai",
                    )
            elif analysis.location_name and not photo["location_name"]:
                # La foto ha già una posizione affidabile: l'AI non può
                # spostarla né cambiarne l'origine, ma può solo completare
                # il nome del luogo se manca.
                update_photo(
                    self._db_path,
                    photo_id,
                    location_name=analysis.location_name,
                )

            update_queue_status(self._db_path, qid, "done")

        except Exception as e:
            logger.warning("Errore analisi photo_id=%s qid=%s: %s", photo_id, qid, e)
            error_str = str(e)

            # Pausa transiente su errori temporanei API (429/503), indipendentemente
            # dal numero di tentativi — altrimenti il worker martella l'API con
            # ogni foto successiva in coda.
            if "503" in error_str or "429" in error_str:
                delay = 120  # default
                # Formato Groq: "try again in 2m23.7696s"
                m_min = re.search(r'(\d+)m(\d+(?:\.\d+)?)s', error_str)
                # Formato Gemini: "retry after 30s" o "retry in 30s"
                m_sec = re.search(r'retry[^\d]*(\d+(?:\.\d+)?)\s*s', error_str, re.IGNORECASE)
                if m_min:
                    delay = max(120, int(m_min.group(1)) * 60 + float(m_min.group(2)) + 5)
                elif m_sec:
                    delay = max(120, float(m_sec.group(1)) + 5)
                logger.info("Errore temporaneo API — pausa coda %.0fs (qid=%s)", delay, qid)
                self._transient_pause_until = time.monotonic() + delay

            increment_attempts(self._db_path, qid)
            current = get_queue_item(self._db_path, qid)
            if current["attempts"] >= MAX_ATTEMPTS:
                update_queue_status(self._db_path, qid, "error",
                                    error_msg=error_str[:500])
            else:
                update_queue_status(self._db_path, qid, "pending")

        finally:
            self.current_photo_name = None

        return True

    def _luogo_dalle_ancore(self, gruppo: list):
        """
        Se nel gruppo c'e' gia' una posizione affidabile, il luogo si conosce:
        non ha senso chiederlo al modello. Sui dati attuali capita in quasi
        meta' dei gruppi.
        """
        for f in gruppo:
            if (f["location_source"] or "") in ORIGINI_AFFIDABILI and f["latitude"] is not None:
                return f["location_name"], f["latitude"], f["longitude"]
        return None

    async def _determina_luogo(self, gruppo: list):
        """Il luogo comune al gruppo: dalle ancore se ci sono, altrimenti dal modello."""
        dalle_ancore = self._luogo_dalle_ancore(gruppo)
        if dalle_ancore:
            return dalle_ancore

        campione = gruppo[:: max(1, len(gruppo) // config.GROUP_CAMPIONE_LUOGO)]
        campione = campione[: config.GROUP_CAMPIONE_LUOGO]
        immagini = []
        for f in campione:
            try:
                immagini.append(prepare_for_ai(
                    f["file_path"], max_side_px=config.GROUP_LUOGO_MAX_SIDE_PX))
            except Exception as exc:
                logger.warning("Immagine illeggibile nel campione: %s (%s)", f["file_path"], exc)
        if not immagini:
            return None
        d = await self._engine.identify_location(immagini)
        if not d.get("luogo_riconosciuto"):
            return None
        return d["luogo_riconosciuto"], d.get("luogo_lat"), d.get("luogo_lon")

    async def process_next_group(self) -> bool:
        """
        Processa il prossimo GRUPPO di foto in coda.

        Il luogo si determina una volta per tutta la catena; le descrizioni si
        scrivono a blocchi. Se il motore non sa lavorare a gruppi, o se il
        luogo non si riesce a stabilire, o se un blocco non supera la
        validazione, si ricade sulle chiamate singole: costa tempo, mai dati
        sbagliati.
        """
        if not (config.GROUP_ABILITATO and getattr(self._engine, "supporta_gruppi", False)):
            return await self.process_next()

        righe = get_pending_photos_for_grouping(self._db_path)
        if not righe:
            return False
        # sqlite3.Row non supporta .get(): prepara() lo richiede.
        foto = prepara([dict(r) for r in righe])
        if not foto:
            return await self.process_next()

        gruppo = gruppo_di(foto, foto[0]["photo_id"], config.GROUP_GAP_MINUTI)
        if len(gruppo) < 2:
            return await self.process_next()

        luogo = await self._determina_luogo(gruppo)
        if luogo is None:
            logger.info("Luogo non determinato per un gruppo di %d foto: vado a foto singole",
                        len(gruppo))
            return await self.process_next()
        nome_luogo, lat, lon = luogo

        for inizio in range(0, len(gruppo), config.GROUP_BLOCCO_FOTO):
            blocco = gruppo[inizio: inizio + config.GROUP_BLOCCO_FOTO]
            for f in blocco:
                update_queue_status(self._db_path, f["queue_id"], "processing")
            self.current_photo_name = "%d foto · %s" % (len(blocco), nome_luogo)
            try:
                immagini = [prepare_for_ai(f["file_path"],
                                           max_side_px=self._engine.max_side_px)
                            for f in blocco]
                analisi = await self._engine.analyze_group(immagini, nome_luogo, lat, lon)
            except Exception as exc:
                # Il blocco non ha superato la validazione, o una foto era
                # illeggibile: le rimetto in attesa per la via singola.
                logger.warning("Blocco di %d foto scartato (%s): vanno a foto singole",
                               len(blocco), exc)
                for f in blocco:
                    update_queue_status(self._db_path, f["queue_id"], "pending")
                continue

            for f, a in zip(blocco, analisi):
                await self._scrivi_analisi(f["photo_id"], f["queue_id"], a, f)

        return True

    async def _scrivi_analisi(self, photo_id: int, queue_id: int, analysis, riga: dict) -> None:
        """Scrive un'analisi e chiude il suo item di coda. Condiviso dai due percorsi."""
        embedding = []
        if self._embedder is not None:
            testo = " ".join(filter(None, [analysis.description, analysis.subject,
                                           analysis.atmosphere, analysis.location_name]))
            try:
                embedding = await self._embedder.embed(testo)
            except Exception as exc:
                logger.warning("Embedding non disponibile per photo_id=%s: %s", photo_id, exc)

        update_photo(
            self._db_path, photo_id,
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

        # Stessa guardia del percorso a foto singola: una posizione che viene da
        # un GPS o da una scelta dell'utente non si sposta mai.
        if riga["latitude"] is None and analysis.location_name:
            update_photo(self._db_path, photo_id,
                         location_name=analysis.location_name,
                         latitude=analysis.latitude,
                         longitude=analysis.longitude,
                         location_source="ai")
        elif riga["latitude"] is not None and not riga["location_name"] and analysis.location_name:
            update_photo(self._db_path, photo_id, location_name=analysis.location_name)

        update_queue_status(self._db_path, queue_id, "done")

    async def _run_loop(self) -> None:
        """Loop principale: consuma la coda rispettando il rate limit."""
        while self.is_running:
            if self.is_paused:
                await asyncio.sleep(2)
                continue

            if time.monotonic() < self._transient_pause_until:
                await asyncio.sleep(2)
                continue

            t_start = time.monotonic()
            processed = await self.process_next_group()

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
