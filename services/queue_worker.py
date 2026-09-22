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
import math
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


def campiona(gruppo: list, quanti: int) -> list:
    """
    Al piu' `quanti` elementi, DISTRIBUITI lungo tutto il gruppo.

    Il passo va calcolato per eccesso. Con un passo per difetto un gruppo di
    11 foto — la dimensione mediana reale — dava passo 1 e quindi le PRIME
    otto consecutive, cioe' pochi minuti di scatti quasi identici; e su cento
    foto l'ultimo 15% non veniva mai campionato.
    """
    if not gruppo or quanti < 1:
        return []
    passo = math.ceil(len(gruppo) / quanti)
    return gruppo[::passo][:quanti]


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

    def _pausa_se_transiente(self, error_str: str, dove: str = "") -> None:
        """
        Pausa transiente su errori temporanei API (429/503), indipendentemente
        dal numero di tentativi — altrimenti il worker martella l'API con ogni
        foto (o ogni gruppo) successivo in coda.
        """
        if "503" not in error_str and "429" not in error_str:
            return
        delay = 120  # default
        # Formato Groq: "try again in 2m23.7696s"
        m_min = re.search(r'(\d+)m(\d+(?:\.\d+)?)s', error_str)
        # Formato Gemini: "retry after 30s" o "retry in 30s"
        m_sec = re.search(r'retry[^\d]*(\d+(?:\.\d+)?)\s*s', error_str, re.IGNORECASE)
        if m_min:
            delay = max(120, int(m_min.group(1)) * 60 + float(m_min.group(2)) + 5)
        elif m_sec:
            delay = max(120, float(m_sec.group(1)) + 5)
        logger.info("Errore temporaneo API — pausa coda %.0fs (%s)", delay, dove or "coda")
        self._transient_pause_until = time.monotonic() + delay

    async def process_next(self) -> bool:
        """
        Processa il prossimo item pending dalla coda.
        Ritorna True se ha processato qualcosa, False se la coda era vuota.
        """
        item = get_next_pending(self._db_path)
        if item is None:
            return False
        return await self._analizza_singola(item["photo_id"], item["id"], item["attempts"])

    async def process_photo(self, photo_id: int, queue_id: int) -> bool:
        """
        Analizza UNA foto precisa per la via singola.

        Serve alla ricaduta del percorso a gruppi: `process_next` prende la
        prossima foto per priorita', che quasi mai e' quella che ha bloccato
        il gruppo — quella resterebbe in coda a riformare lo stesso gruppo
        bloccante a ogni iterazione, senza mai essere analizzata.
        """
        item = get_queue_item(self._db_path, queue_id)
        if item is None or item["status"] not in ("pending", "processing"):
            return False
        return await self._analizza_singola(photo_id, queue_id, item["attempts"])

    async def _analizza_singola(self, photo_id: int, qid: int, attempts: int) -> bool:
        """Il corpo della via a foto singola, condiviso da process_next e process_photo."""
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

            self._pausa_se_transiente(error_str, "qid=%s" % qid)

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

    @staticmethod
    def _ancore(gruppo: list) -> list:
        """
        Le foto del gruppo con una posizione di cui fidarsi (GPS o scelta
        dell'utente). Servono ENTRAMBE le coordinate: una latitudine da sola
        non e' una posizione.
        """
        return [f for f in gruppo
                if (f["location_source"] or "") in ORIGINI_AFFIDABILI
                and f["latitude"] is not None and f["longitude"] is not None]

    def _luogo_dalle_ancore(self, gruppo: list):
        """
        Se nel gruppo c'e' gia' una posizione affidabile CON il suo nome, il
        luogo si conosce e non ha senso chiederlo al modello.

        Il nome va cercato fra TUTTE le ancore, non preso dalla prima: le
        ancore `exif` non hanno mai un nome (105 su 105 sui dati reali) e le
        `takeout` non ce l'hanno in 412 casi su 651. Prendendo la prima e
        basta, due terzi dei gruppi ancorati mandavano al modello "il luogo e'
        gia' noto e certo: None" e restavano senza posizione.
        """
        for f in self._ancore(gruppo):
            if (f["location_name"] or "").strip():
                return f["location_name"], f["latitude"], f["longitude"]
        return None

    async def _luogo_dal_modello(self, gruppo: list):
        """Nome e coordinate proposti dal modello su un campione del gruppo."""
        immagini = []
        for f in campiona(gruppo, config.GROUP_CAMPIONE_LUOGO):
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

    async def _determina_luogo(self, gruppo: list):
        """
        Il luogo comune al gruppo, in tre casi:
        - ancora CON nome: si usa quella, nessuna chiamata al modello;
        - ancora SENZA nome: si chiede il nome al modello, ma si tengono le
          coordinate dell'ancora, che sono vere;
        - nessuna ancora: nome e coordinate vengono dal modello.
        """
        con_nome = self._luogo_dalle_ancore(gruppo)
        if con_nome:
            return con_nome

        dal_modello = await self._luogo_dal_modello(gruppo)
        ancore = self._ancore(gruppo)
        if ancore and dal_modello:
            # Del modello si prende solo il NOME: le coordinate proposte sono
            # un'ipotesi, quelle dell'ancora no.
            return dal_modello[0], ancore[0]["latitude"], ancore[0]["longitude"]
        return dal_modello

    @staticmethod
    def _piu_urgente(righe: list) -> dict:
        """
        La foto da cui far partire il gruppo: la piu' urgente in coda, non la
        cronologicamente prima. Chi preme "analizza ora" dal lightbox, o
        accetta una correzione da Check location, accoda con priorita' 1 e
        deve passare davanti alle migliaia in attesa con priorita' 5.
        A parita' di priorita' vince la piu' vecchia in coda.
        """
        return min(righe, key=lambda f: (f.get("priority") or 5,
                                         f.get("queued_at") or "",
                                         f["queue_id"]))

    def _deve_fermarsi(self) -> bool:
        """
        Fra un blocco e l'altro: la pausa dell'utente deve valere subito, non a
        fine gruppo. Un gruppo di 279 foto sono 24 blocchi e diversi minuti di
        spesa dopo il clic su "pausa".

        `is_running` conta solo se il worker e' stato davvero avviato: chi
        chiama `process_next_group()` a mano lo trova a False.
        """
        if self.is_paused:
            return True
        return self._task is not None and not self.is_running

    def _fallisci(self, righe: list, messaggio: str) -> None:
        """
        Un passo del percorso a gruppi non e' riuscito: conta il tentativo su
        ogni foto coinvolta, esattamente come fa la via a foto singola.

        Senza contatore lo stesso gruppo si riforma identico a ogni giro e il
        worker richiama il modello all'infinito, a piena velocita' e a
        pagamento. Chi ha esaurito i tentativi va in errore, non torna pending.
        """
        for f in righe:
            qid = f["queue_id"]
            increment_attempts(self._db_path, qid)
            item = get_queue_item(self._db_path, qid)
            if item is not None and item["attempts"] >= MAX_ATTEMPTS:
                update_queue_status(self._db_path, qid, "error",
                                    error_msg=messaggio[:500])
            else:
                update_queue_status(self._db_path, qid, "pending")

    async def _ricaduta(self, riga: dict, motivo: str) -> bool:
        """La ricaduta a foto singola deve toccare PROPRIO la foto che ha bloccato."""
        logger.info("Ricaduta a foto singola (%s): photo_id=%s", motivo, riga["photo_id"])
        return await self.process_photo(riga["photo_id"], riga["queue_id"])

    async def process_next_group(self) -> bool:
        """
        Processa il prossimo GRUPPO di foto in coda.

        Ritorna True solo se ha scritto almeno un'analisi: se non ha scritto
        nulla deve dire False, cosi' il loop del worker applica la sua pausa
        invece di riformare subito lo stesso gruppo.

        Nessun errore puo' uscire da qui: un 429 non gestito ucciderebbe il
        task del worker lasciando `is_running` a True, con l'interfaccia che
        dice "in esecuzione" e la coda ferma per sempre.
        """
        try:
            return await self._processa_gruppo()
        except Exception as exc:
            logger.exception("Percorso a gruppi interrotto da un errore: %s", exc)
            self._pausa_se_transiente(str(exc), "percorso a gruppi")
            return False
        finally:
            self.current_photo_name = None

    async def _processa_gruppo(self) -> bool:
        """
        Il corpo del percorso a gruppi: gruppo, luogo, blocchi, scrittura.

        Il luogo si determina una volta per tutta la catena; le descrizioni si
        scrivono a blocchi. Se il motore non sa lavorare a gruppi, o se il
        luogo non si riesce a stabilire, si ricade sulla via singola per la
        foto che ha bloccato: costa tempo, mai dati sbagliati.
        """
        if not (config.GROUP_ABILITATO and getattr(self._engine, "supporta_gruppi", False)):
            return await self.process_next()

        righe = [dict(r) for r in get_pending_photos_for_grouping(self._db_path)]
        if not righe:
            return False
        # sqlite3.Row non supporta .get(): prepara() lo richiede.
        foto = prepara(righe)
        if not foto:
            return await self._ricaduta(self._piu_urgente(righe),
                                        "nessun istante di scatto")

        partenza = self._piu_urgente(foto)
        gruppo = gruppo_di(foto, partenza["photo_id"], config.GROUP_GAP_MINUTI)
        if len(gruppo) < 2:
            return await self._ricaduta(partenza, "foto isolata, nessun gruppo")

        try:
            luogo = await self._determina_luogo(gruppo)
        except Exception as exc:
            # Il passo 1 e' fuori dai blocchi: se salta, salta tutto il gruppo.
            logger.warning("Luogo non determinabile per un gruppo di %d foto: %s",
                           len(gruppo), exc)
            self._pausa_se_transiente(str(exc), "passo 1 del gruppo")
            self._fallisci(gruppo, "Luogo del gruppo non determinato: %s" % exc)
            return False
        if luogo is None:
            return await self._ricaduta(
                partenza, "luogo non determinato per un gruppo di %d foto" % len(gruppo))
        nome_luogo, lat, lon = luogo

        scritte = 0
        for inizio in range(0, len(gruppo), config.GROUP_BLOCCO_FOTO):
            if self._deve_fermarsi():
                logger.info("Worker in pausa: interrompo il gruppo, %d foto tornano in attesa",
                            len(gruppo) - inizio)
                for f in gruppo[inizio:]:
                    update_queue_status(self._db_path, f["queue_id"], "pending")
                break

            blocco = gruppo[inizio: inizio + config.GROUP_BLOCCO_FOTO]
            for f in blocco:
                update_queue_status(self._db_path, f["queue_id"], "processing")
            self.current_photo_name = "%d foto · %s" % (len(blocco), nome_luogo)
            try:
                immagini = [prepare_for_ai(f["file_path"],
                                           max_side_px=self._engine.max_side_px)
                            for f in blocco]
                analisi = await self._engine.analyze_group(immagini, nome_luogo, lat, lon)
                if len(analisi) != len(blocco):
                    # zip() troncherebbe in silenzio e le foto in eccesso
                    # resterebbero 'processing' per sempre.
                    raise ValueError("Il motore ha reso %d analisi per %d foto"
                                     % (len(analisi), len(blocco)))
            except Exception as exc:
                # Il blocco non ha superato la validazione, o una foto era
                # illeggibile: conta il tentativo e riprova per la via singola.
                logger.warning("Blocco di %d foto scartato (%s)", len(blocco), exc)
                self._pausa_se_transiente(str(exc), "blocco di %d foto" % len(blocco))
                self._fallisci(blocco, str(exc))
                continue

            for f, a in zip(blocco, analisi):
                await self._scrivi_analisi(f["photo_id"], f["queue_id"], a, f)
                scritte += 1

        return scritte > 0

    async def _scrivi_analisi(self, photo_id: int, queue_id: int, analysis, riga: dict) -> None:
        """Scrive un'analisi e chiude il suo item di coda. Usato dal percorso a gruppi."""
        embedding = []
        if self._embedder is not None:
            testo = " ".join(filter(None, [analysis.description, analysis.subject,
                                           analysis.atmosphere,
                                           analysis.location_name or riga["location_name"]]))
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
        #
        # La guardia va applicata alla riga RILETTA adesso, non allo snapshot
        # preso prima del passo 1: su un gruppo grande passano minuti, e in
        # quel tempo l'utente puo' aver corretto a mano la posizione di una di
        # queste foto — scriverci sopra con location_source='ai' la perderebbe.
        attuale = get_photo_by_id(self._db_path, photo_id) or riga
        if attuale["latitude"] is None:
            if analysis.location_name:
                update_photo(self._db_path, photo_id,
                             location_name=analysis.location_name,
                             latitude=analysis.latitude,
                             longitude=analysis.longitude,
                             location_source="ai")
        elif analysis.location_name and not attuale["location_name"]:
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
