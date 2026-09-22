"""
Test per services/queue_worker.py.
Usa un AIEngine fake per non chiamare API reali.
"""
import json
import pytest
from PIL import Image
import io
from unittest.mock import AsyncMock

from services.ai.base import AIEngine, PhotoAnalysis


def make_fake_engine() -> AIEngine:
    """Engine mock che ritorna sempre la stessa analisi."""
    class FakeEngine(AIEngine):
        async def analyze(self, image_bytes, location_hint=""):
            return PhotoAnalysis(
                description="Foto di test",
                technical_score=7.0,
                aesthetic_score=8.0,
                subject="oggetto test",
                atmosphere="serena",
                colors=["rosso", "blu"],
                strengths="buona",
                weaknesses=None,
                ai_engine="fake",
            )
    return FakeEngine()


def make_fake_engine_with_location(location_name="Roma, Italia",
                                    latitude=41.9, longitude=12.5) -> AIEngine:
    """Engine mock che ritorna un luogo riconosciuto con coordinate."""
    class FakeLocationEngine(AIEngine):
        async def analyze(self, image_bytes, location_hint=""):
            return PhotoAnalysis(
                description="Foto di test con luogo",
                technical_score=7.0,
                aesthetic_score=8.0,
                subject="oggetto test",
                atmosphere="serena",
                colors=["rosso", "blu"],
                strengths="buona",
                weaknesses=None,
                ai_engine="fake",
                location_name=location_name,
                latitude=latitude,
                longitude=longitude,
            )
    return FakeLocationEngine()


class FakeEmbedder:
    """Embedder finto che registra i testi ricevuti."""
    def __init__(self, dimension=1024):
        self._dimension = dimension
        self.seen = []

    @property
    def dimension(self):
        return self._dimension

    async def embed(self, text):
        self.seen.append(text)
        return [0.5] * self._dimension

    async def embed_batch(self, texts):
        self.seen.extend(texts)
        return [[0.5] * self._dimension for _ in texts]


class FailingEmbedder(FakeEmbedder):
    async def embed(self, text):
        raise RuntimeError("Ollama irraggiungibile")


def make_jpeg_file(tmp_path, name: str = "test.jpg") -> str:
    path = str(tmp_path / name)
    Image.new("RGB", (100, 100), (200, 100, 50)).save(path, "JPEG")
    return path


class TestQueueWorkerProcessNext:
    async def test_processes_pending_item(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo
        from database.queue import add_to_queue, get_queue_item

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        qid = add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None)
        processed = await worker.process_next()

        assert processed is True
        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "done"

    async def test_saves_analysis_to_photo(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["description"] == "Foto di test"
        assert photo["technical_score"] == 7.0
        assert photo["analyzed_at"] is not None

    async def test_saves_embedding(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        add_to_queue(tmp_db, photo_id=pid)
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None, embedder=FakeEmbedder(dimension=768))
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        embedding = json.loads(photo["embedding"])
        assert len(embedding) == 768

    async def test_returns_false_when_queue_empty(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None)
        processed = await worker.process_next()
        assert processed is False

    async def test_marks_error_after_max_attempts(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker, MAX_ATTEMPTS
        from database.photos import insert_photo
        from database.queue import add_to_queue, get_queue_item

        class FailingEngine(AIEngine):
            async def analyze(self, image_bytes, location_hint=""):
                raise RuntimeError("API error")
            async def embed(self, text): return []

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        qid = add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(engine=FailingEngine(), db_path=tmp_db,
                             rpm_limit=None)
        # Chiama MAX_ATTEMPTS volte
        for _ in range(MAX_ATTEMPTS):
            await worker.process_next()

        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "error"
        assert item["attempts"] == MAX_ATTEMPTS


class TestQueueWorkerPauseResume:
    def test_initial_state_not_running(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db)
        assert worker.is_running is False
        assert worker.is_paused is False

    def test_pause_sets_flag(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db)
        worker.pause()
        assert worker.is_paused is True

    def test_resume_clears_flag(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db)
        worker.pause()
        worker.resume()
        assert worker.is_paused is False


class TestQueueWorkerEmbedder:
    async def _queue_one_photo(self, tmp_path, tmp_db):
        from database.photos import insert_photo
        from database.queue import add_to_queue
        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db, file_path=photo_path,
                           folder_path=str(tmp_path), filename="test.jpg",
                           format="jpg", file_size=100, width=100, height=100)
        add_to_queue(tmp_db, photo_id=pid)
        return pid

    async def test_uses_embedder_not_engine(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import get_photo_by_id

        pid = await self._queue_one_photo(tmp_path, tmp_db)
        embedder = FakeEmbedder()
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None, embedder=embedder)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert json.loads(photo["embedding"]) == [0.5] * 1024
        assert len(embedder.seen) == 1
        assert "Foto di test" in embedder.seen[0]

    async def test_analysis_survives_embedder_failure(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import get_photo_by_id
        from database.queue import get_queue_counts

        pid = await self._queue_one_photo(tmp_path, tmp_db)
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None, embedder=FailingEmbedder())
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["description"] == "Foto di test"
        assert json.loads(photo["embedding"]) == []
        assert get_queue_counts(tmp_db)["done"] == 1

    async def test_works_without_embedder(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import get_photo_by_id

        pid = await self._queue_one_photo(tmp_path, tmp_db)
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None, embedder=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["description"] == "Foto di test"
        assert json.loads(photo["embedding"]) == []


class TestQueueWorkerLocationGuard:
    """
    La guardia che decide se l'AI può scrivere la posizione deve basarsi
    sulle COORDINATE (photo["latitude"]), non sul nome del luogo: le
    posizioni affidabili (GPS EXIF, scelta utente, correzione manuale)
    quasi mai hanno un location_name valorizzato, quindi una guardia sul
    nome non le protegge dall'essere sovrascritte da una semplice ipotesi
    dell'AI.
    """

    async def test_corrected_position_without_name_is_not_overwritten(self, tmp_path, tmp_db):
        """
        Foto con location_source='corrected' e coordinate ma senza nome:
        la rianalisi deve solo riempire location_name, senza toccare
        latitude/longitude/location_source anche se l'AI propone un luogo
        con coordinate diverse.
        """
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100,
                           latitude=25.70,
                           longitude=32.64,
                           location_name=None,
                           location_source="corrected")
        add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(
            engine=make_fake_engine_with_location(
                location_name="Torino, Italia", latitude=45.08, longitude=7.77),
            db_path=tmp_db, rpm_limit=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["latitude"] == 25.70
        assert photo["longitude"] == 32.64
        assert photo["location_source"] == "corrected"
        assert photo["location_name"] == "Torino, Italia"

    async def test_photo_without_coordinates_gets_ai_location(self, tmp_path, tmp_db):
        """
        Foto senza coordinate e senza nome: l'AI può scrivere tutto
        (nome, coordinate, location_source='ai') — comportamento invariato.
        """
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(
            engine=make_fake_engine_with_location(
                location_name="Roma, Italia", latitude=41.9, longitude=12.5),
            db_path=tmp_db, rpm_limit=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["location_name"] == "Roma, Italia"
        assert photo["latitude"] == 41.9
        assert photo["longitude"] == 12.5
        assert photo["location_source"] == "ai"

    async def test_photo_with_coordinates_and_name_is_untouched(self, tmp_path, tmp_db):
        """
        Foto con coordinate e nome già presenti: la posizione non deve
        essere toccata in alcun campo.
        """
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100,
                           latitude=45.08,
                           longitude=7.77,
                           location_name="Torino, Italia",
                           location_source="corrected")
        add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(
            engine=make_fake_engine_with_location(
                location_name="Roma, Italia", latitude=41.9, longitude=12.5),
            db_path=tmp_db, rpm_limit=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["location_name"] == "Torino, Italia"
        assert photo["latitude"] == 45.08
        assert photo["longitude"] == 7.77
        assert photo["location_source"] == "corrected"

    async def test_exif_coordinates_survive_reanalysis(self, tmp_path, tmp_db):
        """
        Difetto preesistente identico: foto con GPS EXIF vero (location_source
        'exif') e senza nome non deve essere spostata dall'ipotesi dell'AI.
        """
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100,
                           latitude=48.85,
                           longitude=2.35,
                           location_name=None,
                           location_source="exif")
        add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(
            engine=make_fake_engine_with_location(
                location_name="Roma, Italia", latitude=41.9, longitude=12.5),
            db_path=tmp_db, rpm_limit=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["latitude"] == 48.85
        assert photo["longitude"] == 2.35
        assert photo["location_source"] == "exif"
        assert photo["location_name"] == "Roma, Italia"




class EngineDiGruppoFinto:
    """
    Motore finto che conta le chiamate e sa rompersi su richiesta.

    - `gruppo_rotto`      : ogni blocco solleva (validazione fallita)
    - `blocchi_rotti`     : solo i blocchi con questi indici sollevano
    - `luogo_rotto`       : `identify_location` solleva (errore di rete)
    - `errore_luogo`      : il testo dell'eccezione di `identify_location`
    - `analisi_mancanti`  : quante analisi in meno rendere rispetto alle immagini
    - `dopo_blocco`       : callback eseguita alla fine di ogni `analyze_group`
    """
    supporta_gruppi = True
    max_side_px = 512

    def __init__(self, luogo, lat, lon, gruppo_rotto=False, blocchi_rotti=(),
                 luogo_rotto=False, errore_luogo="DeepSeek irraggiungibile",
                 analisi_mancanti=0, dopo_blocco=None):
        self._luogo, self._lat, self._lon = luogo, lat, lon
        self._rotto = gruppo_rotto
        self._blocchi_rotti = set(blocchi_rotti)
        self._luogo_rotto = luogo_rotto
        self._errore_luogo = errore_luogo
        self._mancanti = analisi_mancanti
        self.dopo_blocco = dopo_blocco
        self.chiamate_gruppo = 0
        self.chiamate_luogo = 0
        self.chiamate_singole = 0
        self.luoghi_visti = []          # (nome, lat, lon) di ogni blocco
        self.dimensioni_campione = []   # quante immagini per ogni identify_location

    async def identify_location(self, immagini):
        self.chiamate_luogo += 1
        self.dimensioni_campione.append(len(immagini))
        if self._luogo_rotto:
            raise RuntimeError(self._errore_luogo)
        return {"luogo_riconosciuto": self._luogo,
                "luogo_lat": self._lat, "luogo_lon": self._lon}

    async def analyze_group(self, immagini, luogo, latitudine=None, longitudine=None):
        indice = self.chiamate_gruppo
        self.chiamate_gruppo += 1
        self.luoghi_visti.append((luogo, latitudine, longitudine))
        if self.dopo_blocco is not None:
            self.dopo_blocco()
        if self._rotto or indice in self._blocchi_rotti:
            raise ValueError("Attese %d voci, ricevute 0" % len(immagini))
        from services.ai.base import PhotoAnalysis
        quante = max(0, len(immagini) - self._mancanti)
        return [PhotoAnalysis(description="descrizione %d" % i, technical_score=7,
                              aesthetic_score=8, subject="s", atmosphere="a",
                              colors=[], strengths="f", weaknesses=None,
                              location_name=luogo, latitude=latitudine,
                              longitude=longitudine, ai_engine="finto")
                for i in range(quante)]

    async def analyze(self, image_bytes, location_hint=""):
        self.chiamate_singole += 1
        from services.ai.base import PhotoAnalysis
        return PhotoAnalysis(description="singola", technical_score=7, aesthetic_score=8,
                             subject="s", atmosphere="a", colors=[], strengths="f",
                             weaknesses=None, ai_engine="finto")


class TestProcessNextGroup:
    """L'orchestrazione: gruppo, luogo, blocchi, ricaduta."""

    def _worker_con(self, tmp_path, monkeypatch, engine, **env):
        import config, importlib
        db = str(tmp_path / "t.db")
        monkeypatch.setenv("LOCAL_DB", db)
        for chiave, valore in env.items():
            monkeypatch.setenv(chiave, str(valore))
        importlib.reload(config)
        from database.models import init_db
        init_db(db)
        from services.queue_worker import QueueWorker
        return QueueWorker(engine=engine, db_path=db), db

    def _foto(self, db, tmp_path, nome, ora, *, lat=None, lon=32.0, src=None,
              nome_luogo="Karnak", priorita=5):
        from PIL import Image
        from database.photos import insert_photo, update_photo
        from database.queue import add_to_queue
        p = str(tmp_path / nome)
        Image.new("RGB", (40, 30)).save(p, "JPEG")
        pid = insert_photo(db, file_path=p, folder_path=str(tmp_path), filename=nome,
                           format="jpg", file_size=10, width=40, height=30)
        campi = {"exif_date": f"2026-04-01T{ora}:00"}
        if lat is not None:
            campi.update(latitude=lat, longitude=lon, location_source=src,
                         location_name=nome_luogo)
        update_photo(db, pid, **campi)
        add_to_queue(db, photo_id=pid, priority=priorita)
        return pid

    # ---------------------------------------------------------------- base

    @pytest.mark.asyncio
    async def test_analizza_il_gruppo_in_una_chiamata(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="Tempio di Karnak", lat=25.7, lon=32.6)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        for i, ora in enumerate(("10:00", "10:05", "10:10")):
            self._foto(db, tmp_path, f"f{i}.jpg", ora)

        assert await w.process_next_group() is True
        assert engine.chiamate_gruppo == 1
        assert engine.chiamate_singole == 0
        from database.queue import get_queue_counts
        assert get_queue_counts(db)["done"] == 3
        assert get_queue_counts(db)["pending"] == 0

    @pytest.mark.asyncio
    async def test_scrive_lo_stesso_luogo_su_tutte(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="Tempio di Karnak", lat=25.7, lon=32.6)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        ids = [self._foto(db, tmp_path, f"g{i}.jpg", o) for i, o in enumerate(("10:00", "10:05"))]
        await w.process_next_group()
        from database.photos import get_photo_by_id
        for pid in ids:
            p = get_photo_by_id(db, pid)
            assert p["location_name"] == "Tempio di Karnak"
            assert p["description"]
            assert p["analyzed_at"] is not None

    @pytest.mark.asyncio
    async def test_uno_stacco_temporale_separa_i_gruppi(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")
        self._foto(db, tmp_path, "c.jpg", "18:00")     # oltre i 15 minuti
        await w.process_next_group()
        from database.queue import get_queue_counts
        assert get_queue_counts(db)["done"] == 2      # solo il primo gruppo
        assert get_queue_counts(db)["pending"] == 1

    @pytest.mark.asyncio
    async def test_un_ancora_affidabile_evita_la_chiamata_sul_luogo(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="NON DEVE SERVIRE", lat=0.0, lon=0.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00", lat=25.7, src="takeout")
        self._foto(db, tmp_path, "b.jpg", "10:05")
        await w.process_next_group()
        assert engine.chiamate_luogo == 0
        from database.photos import get_photos
        nomi = {p["location_name"] for p in get_photos(db, limit=10)}
        assert "NON DEVE SERVIRE" not in nomi

    @pytest.mark.asyncio
    async def test_coda_vuota_ritorna_falso(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, _ = self._worker_con(tmp_path, monkeypatch, engine)
        assert await w.process_next_group() is False

    # ------------------------------------------- C1: niente ciclo infinito

    @pytest.mark.asyncio
    async def test_un_blocco_che_fallisce_ritorna_falso(self, tmp_path, monkeypatch):
        """
        Se non e' stata scritta NESSUNA analisi la funzione deve dire False,
        altrimenti il loop del worker non applica la sua pausa e riforma lo
        stesso gruppo subito, a piena velocita' e a pagamento.
        """
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, gruppo_rotto=True)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")
        assert await w.process_next_group() is False

    @pytest.mark.asyncio
    async def test_un_blocco_che_fallisce_sempre_non_resta_pending_per_sempre(
            self, tmp_path, monkeypatch):
        """
        Il percorso a gruppi deve contare i tentativi come quello a foto
        singola: dopo MAX_ATTEMPTS le foto finiscono in errore o vengono
        analizzate singolarmente, ma non tornano pending all'infinito.
        """
        from services.queue_worker import MAX_ATTEMPTS
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, gruppo_rotto=True)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")

        for _ in range(MAX_ATTEMPTS + 3):
            await w.process_next_group()

        from database.queue import get_queue_counts
        conti = get_queue_counts(db)
        assert conti["pending"] == 0
        assert conti["processing"] == 0
        assert conti["error"] + conti["done"] == 2
        assert engine.chiamate_singole > 0 or conti["error"] == 2

    @pytest.mark.asyncio
    async def test_un_blocco_rotto_non_richiama_il_motore_senza_limite(
            self, tmp_path, monkeypatch):
        """
        Dieci giri del loop non devono valere dieci identify_location e dieci
        analyze_group: e' esattamente la fattura che il ciclo infinito produce.
        """
        from services.queue_worker import MAX_ATTEMPTS
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, gruppo_rotto=True)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")

        for _ in range(10):
            await w.process_next_group()

        assert engine.chiamate_luogo <= MAX_ATTEMPTS
        assert engine.chiamate_gruppo <= MAX_ATTEMPTS

    # -------------------------------------- C2: ancora con coordinate, senza nome

    @pytest.mark.asyncio
    async def test_ancora_senza_nome_chiede_il_nome_ma_tiene_le_coordinate(
            self, tmp_path, monkeypatch):
        """
        Le ancore `exif` non hanno MAI un nome. Prendere la prima ancora e
        basta mandava al modello "il luogo e' gia' noto e certo: None" e
        lasciava tutto il gruppo senza posizione.
        """
        engine = EngineDiGruppoFinto(luogo="Tempio di Karnak", lat=99.0, lon=99.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        a = self._foto(db, tmp_path, "a.jpg", "10:00", lat=25.7, lon=32.6,
                       src="exif", nome_luogo=None)
        b = self._foto(db, tmp_path, "b.jpg", "10:05")

        assert await w.process_next_group() is True

        # Il nome e' stato chiesto al modello...
        assert engine.chiamate_luogo == 1
        nome, lat, lon = engine.luoghi_visti[0]
        assert nome == "Tempio di Karnak"
        assert str(nome) != "None"
        # ...ma le coordinate restano quelle vere dell'ancora.
        assert (lat, lon) == (25.7, 32.6)

        from database.photos import get_photo_by_id
        pa, pb = get_photo_by_id(db, a), get_photo_by_id(db, b)
        assert pa["latitude"] == 25.7 and pa["location_source"] == "exif"
        assert pa["location_name"] == "Tempio di Karnak"
        assert (pb["latitude"], pb["longitude"]) == (25.7, 32.6)
        assert pb["location_name"] == "Tempio di Karnak"

    @pytest.mark.asyncio
    async def test_ancora_con_nome_resta_la_scorciatoia(self, tmp_path, monkeypatch):
        """Fra due ancore si sceglie quella che ha il nome, non la prima."""
        engine = EngineDiGruppoFinto(luogo="NON DEVE SERVIRE", lat=0.0, lon=0.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00", lat=25.7, lon=32.6,
                   src="exif", nome_luogo=None)
        self._foto(db, tmp_path, "b.jpg", "10:05", lat=25.8, lon=32.7,
                   src="takeout", nome_luogo="Luxor")

        await w.process_next_group()
        assert engine.chiamate_luogo == 0
        assert engine.luoghi_visti[0] == ("Luxor", 25.8, 32.7)

    @pytest.mark.asyncio
    async def test_un_ancora_con_mezza_coordinata_non_e_un_ancora(
            self, tmp_path, monkeypatch):
        """Una latitudine da sola non e' una posizione: serve anche la longitudine."""
        engine = EngineDiGruppoFinto(luogo="Tempio di Karnak", lat=25.7, lon=32.6)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        pid = self._foto(db, tmp_path, "a.jpg", "10:00", lat=25.7, lon=None,
                         src="exif", nome_luogo=None)
        self._foto(db, tmp_path, "b.jpg", "10:05")

        await w.process_next_group()
        assert engine.chiamate_luogo == 1
        # Nessuna coordinata da preservare: valgono quelle del modello.
        assert engine.luoghi_visti[0] == ("Tempio di Karnak", 25.7, 32.6)

    # ------------------------------------------- C3: gli errori non uccidono il worker

    @pytest.mark.asyncio
    async def test_un_errore_su_identify_location_non_uccide_il_worker(
            self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, luogo_rotto=True)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")

        assert await w.process_next_group() is False
        from database.queue import get_queue_counts
        assert get_queue_counts(db)["processing"] == 0

    @pytest.mark.asyncio
    async def test_un_429_sul_luogo_mette_in_pausa_la_coda(self, tmp_path, monkeypatch):
        """Senza la pausa transiente un rate limit viene ignorato e l'API martellata."""
        import time
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, luogo_rotto=True,
                                     errore_luogo="429 Too Many Requests, retry in 30s")
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")

        await w.process_next_group()
        assert w._transient_pause_until > time.monotonic()

    @pytest.mark.asyncio
    async def test_un_429_su_un_blocco_mette_in_pausa_la_coda(self, tmp_path, monkeypatch):
        import time

        class EngineCon429(EngineDiGruppoFinto):
            async def analyze_group(self, immagini, luogo, latitudine=None, longitudine=None):
                self.chiamate_gruppo += 1
                raise RuntimeError("429 rate limit, retry in 45s")

        engine = EngineCon429(luogo="X", lat=1.0, lon=2.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")

        await w.process_next_group()
        assert w._transient_pause_until > time.monotonic()

    @pytest.mark.asyncio
    async def test_il_nome_della_foto_corrente_viene_riazzerato(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")
        await w.process_next_group()
        assert w.current_photo_name is None

    # ------------------------------------------------ C4: la ricaduta sblocca il gruppo

    @pytest.mark.asyncio
    async def test_la_ricaduta_analizza_proprio_la_foto_che_ha_bloccato(
            self, tmp_path, monkeypatch):
        """
        Una foto sola in coda non forma un gruppo: la ricaduta deve analizzare
        QUELLA, non "la prossima per priorita'", altrimenti resta in coda a
        riformare lo stesso gruppo bloccante a ogni giro.
        """
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        sola = self._foto(db, tmp_path, "a.jpg", "10:00")

        assert await w.process_next_group() is True
        assert engine.chiamate_singole == 1
        from database.photos import get_photo_by_id
        from database.queue import get_queue_counts
        assert get_photo_by_id(db, sola)["analyzed_at"] is not None
        assert get_queue_counts(db)["done"] == 1

    @pytest.mark.asyncio
    async def test_la_foto_che_blocca_non_resta_indietro(self, tmp_path, monkeypatch):
        """
        La foto isolata e' l'ultima per priorita': con `process_next` la
        ricaduta avrebbe preso un'altra foto e quella isolata sarebbe rimasta
        in coda per sempre. Dopo un giro deve essere fatta.
        """
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        isolata = self._foto(db, tmp_path, "z.jpg", "08:00", priorita=1)
        self._foto(db, tmp_path, "a.jpg", "10:00", priorita=5)
        self._foto(db, tmp_path, "b.jpg", "10:05", priorita=5)

        await w.process_next_group()
        from database.photos import get_photo_by_id
        assert get_photo_by_id(db, isolata)["analyzed_at"] is not None

    # ------------------------------------------------------- I1: campionamento

    def test_il_campione_e_distribuito_e_mai_piu_lungo_del_dovuto(self):
        from services.queue_worker import campiona
        for n in (1, 3, 8, 11, 23, 100):
            gruppo = [{"photo_id": i} for i in range(n)]
            c = campiona(gruppo, 8)
            assert 1 <= len(c) <= 8, f"gruppo di {n}: campione di {len(c)}"
            assert c[0] is gruppo[0]
            if n > 8:
                # non le PRIME otto consecutive: il campione arriva in fondo
                assert c[-1]["photo_id"] >= (n - 1) // 2, f"gruppo di {n}"

    def test_il_campione_di_undici_non_e_consecutivo(self):
        from services.queue_worker import campiona
        gruppo = [{"photo_id": i} for i in range(11)]
        assert [f["photo_id"] for f in campiona(gruppo, 8)] == [0, 2, 4, 6, 8, 10]

    # ------------------------------------------------------------ I2: zip muto

    @pytest.mark.asyncio
    async def test_meno_analisi_che_immagini_e_un_fallimento(self, tmp_path, monkeypatch):
        """
        `zip` troncherebbe in silenzio e le foto in eccesso resterebbero
        'processing' per sempre.
        """
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, analisi_mancanti=1)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")

        assert await w.process_next_group() is False
        from database.queue import get_queue_counts
        conti = get_queue_counts(db)
        assert conti["processing"] == 0
        assert conti["done"] == 0
        assert conti["pending"] == 2

    # ---------------------------------------- I3: niente sovrascritture su snapshot

    @pytest.mark.asyncio
    async def test_una_correzione_manuale_arrivata_durante_il_gruppo_non_si_perde(
            self, tmp_path, monkeypatch):
        """
        Su un gruppo grande passano minuti: se nel frattempo l'utente corregge
        a mano una foto, la riga letta prima del passo 1 e' vecchia e la
        scrittura la sovrascriverebbe con location_source='ai'.
        """
        engine = EngineDiGruppoFinto(luogo="Tempio di Karnak", lat=25.7, lon=32.6)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        a = self._foto(db, tmp_path, "a.jpg", "10:00")
        b = self._foto(db, tmp_path, "b.jpg", "10:05")

        from database.photos import update_photo, get_photo_by_id
        # L'utente corregge mentre il modello sta lavorando.
        engine.dopo_blocco = lambda: update_photo(
            db, a, latitude=45.08, longitude=7.77,
            location_name="Torino", location_source="corrected")

        await w.process_next_group()

        pa = get_photo_by_id(db, a)
        assert (pa["latitude"], pa["longitude"]) == (45.08, 7.77)
        assert pa["location_source"] == "corrected"
        assert pa["location_name"] == "Torino"
        assert get_photo_by_id(db, b)["location_source"] == "ai"

    # ------------------------------------------------------------- I4: priorita'

    @pytest.mark.asyncio
    async def test_il_gruppo_parte_dalla_foto_piu_urgente(self, tmp_path, monkeypatch):
        """
        Chi preme "analizza ora" dal lightbox accoda con priorita' 1 e deve
        passare davanti alle migliaia in attesa con priorita' 5.
        """
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        lento_1 = self._foto(db, tmp_path, "a.jpg", "09:00", priorita=5)
        lento_2 = self._foto(db, tmp_path, "b.jpg", "09:05", priorita=5)
        urgente_1 = self._foto(db, tmp_path, "c.jpg", "18:00", priorita=1)
        urgente_2 = self._foto(db, tmp_path, "d.jpg", "18:05", priorita=1)

        await w.process_next_group()

        from database.photos import get_photo_by_id
        assert get_photo_by_id(db, urgente_1)["analyzed_at"] is not None
        assert get_photo_by_id(db, urgente_2)["analyzed_at"] is not None
        assert get_photo_by_id(db, lento_1)["analyzed_at"] is None
        assert get_photo_by_id(db, lento_2)["analyzed_at"] is None

    # ------------------------------------------------------ Blocchi multipli

    @pytest.mark.asyncio
    async def test_un_gruppo_piu_grande_del_blocco_fa_due_chiamate_stesso_luogo(
            self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="Tempio di Karnak", lat=25.7, lon=32.6)
        w, db = self._worker_con(tmp_path, monkeypatch, engine, GROUP_BLOCCO_FOTO=12)
        for i in range(15):
            self._foto(db, tmp_path, f"f{i:02d}.jpg", f"10:{i:02d}")

        assert await w.process_next_group() is True
        assert engine.chiamate_gruppo == 2
        assert engine.chiamate_luogo == 1
        # entrambi i blocchi con lo stesso luogo: il passo 1 non si ripete
        assert len(set(engine.luoghi_visti)) == 1
        from database.queue import get_queue_counts
        assert get_queue_counts(db)["done"] == 15

    @pytest.mark.asyncio
    async def test_un_blocco_fallito_non_ferma_l_altro(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, blocchi_rotti=(0,))
        w, db = self._worker_con(tmp_path, monkeypatch, engine, GROUP_BLOCCO_FOTO=12)
        for i in range(15):
            self._foto(db, tmp_path, f"f{i:02d}.jpg", f"10:{i:02d}")

        assert await w.process_next_group() is True
        assert engine.chiamate_gruppo == 2
        from database.queue import get_queue_counts
        conti = get_queue_counts(db)
        assert conti["done"] == 3          # il secondo blocco e' passato
        assert conti["pending"] == 12      # il primo riprovera'
        assert conti["processing"] == 0

    # ------------------------------------------------------------- I5: pausa

    @pytest.mark.asyncio
    async def test_la_pausa_interrompe_il_gruppo_fra_un_blocco_e_l_altro(
            self, tmp_path, monkeypatch):
        """
        L'utente preme pausa per smettere di spendere: il worker non puo'
        continuare per altri 23 blocchi.
        """
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, db = self._worker_con(tmp_path, monkeypatch, engine, GROUP_BLOCCO_FOTO=12)
        for i in range(15):
            self._foto(db, tmp_path, f"f{i:02d}.jpg", f"10:{i:02d}")
        engine.dopo_blocco = w.pause

        await w.process_next_group()

        assert engine.chiamate_gruppo == 1
        from database.queue import get_queue_counts
        conti = get_queue_counts(db)
        assert conti["done"] == 12
        assert conti["pending"] == 3
        assert conti["processing"] == 0


class TestProcessPhoto:
    """La via singola mirata, usata dalla ricaduta del percorso a gruppi."""

    async def test_analizza_la_foto_indicata_non_la_prima_in_coda(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue, get_queue_item

        ids = []
        for nome in ("prima.jpg", "seconda.jpg"):
            p = make_jpeg_file(tmp_path, nome)
            ids.append(insert_photo(tmp_db, file_path=p, folder_path=str(tmp_path),
                                    filename=nome, format="jpg", file_size=100,
                                    width=100, height=100))
        qids = [add_to_queue(tmp_db, photo_id=pid) for pid in ids]

        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db, rpm_limit=None)
        assert await worker.process_photo(ids[1], qids[1]) is True

        assert get_photo_by_id(tmp_db, ids[1])["analyzed_at"] is not None
        assert get_photo_by_id(tmp_db, ids[0])["analyzed_at"] is None
        assert get_queue_item(tmp_db, qids[1])["status"] == "done"

    async def test_item_inesistente_ritorna_falso(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db, rpm_limit=None)
        assert await worker.process_photo(999, 999) is False
