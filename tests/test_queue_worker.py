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
    """Motore finto che conta le chiamate e sa rompersi su richiesta."""
    supporta_gruppi = True
    max_side_px = 512

    def __init__(self, luogo, lat, lon, gruppo_rotto=False):
        self._luogo, self._lat, self._lon = luogo, lat, lon
        self._rotto = gruppo_rotto
        self.chiamate_gruppo = 0
        self.chiamate_luogo = 0
        self.chiamate_singole = 0

    async def identify_location(self, immagini):
        self.chiamate_luogo += 1
        return {"luogo_riconosciuto": self._luogo,
                "luogo_lat": self._lat, "luogo_lon": self._lon}

    async def analyze_group(self, immagini, luogo, latitudine=None, longitudine=None):
        self.chiamate_gruppo += 1
        if self._rotto:
            raise ValueError("Attese %d voci, ricevute 0" % len(immagini))
        from services.ai.base import PhotoAnalysis
        return [PhotoAnalysis(description="descrizione %d" % i, technical_score=7,
                              aesthetic_score=8, subject="s", atmosphere="a",
                              colors=[], strengths="f", weaknesses=None,
                              location_name=luogo, latitude=latitudine,
                              longitude=longitudine, ai_engine="finto")
                for i in range(len(immagini))]

    async def analyze(self, image_bytes, location_hint=""):
        self.chiamate_singole += 1
        from services.ai.base import PhotoAnalysis
        return PhotoAnalysis(description="singola", technical_score=7, aesthetic_score=8,
                             subject="s", atmosphere="a", colors=[], strengths="f",
                             weaknesses=None, ai_engine="finto")


class TestProcessNextGroup:
    """L'orchestrazione: gruppo, luogo, blocchi, ricaduta."""

    def _worker_con(self, tmp_path, monkeypatch, engine):
        import config, importlib
        db = str(tmp_path / "t.db")
        monkeypatch.setenv("LOCAL_DB", db)
        importlib.reload(config)
        from database.models import init_db
        init_db(db)
        from services.queue_worker import QueueWorker
        return QueueWorker(engine=engine, db_path=db), db

    def _foto(self, db, tmp_path, nome, ora, *, lat=None, src=None):
        from PIL import Image
        from database.photos import insert_photo, update_photo
        from database.queue import add_to_queue
        p = str(tmp_path / nome)
        Image.new("RGB", (40, 30)).save(p, "JPEG")
        pid = insert_photo(db, file_path=p, folder_path=str(tmp_path), filename=nome,
                           format="jpg", file_size=10, width=40, height=30)
        campi = {"exif_date": f"2026-04-01T{ora}:00"}
        if lat is not None:
            campi.update(latitude=lat, longitude=32.0, location_source=src,
                         location_name="Karnak")
        update_photo(db, pid, **campi)
        add_to_queue(db, photo_id=pid)
        return pid

    @pytest.mark.asyncio
    async def test_analizza_il_gruppo_in_una_chiamata(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="Tempio di Karnak", lat=25.7, lon=32.6)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        for i, ora in enumerate(("10:00", "10:05", "10:10")):
            self._foto(db, tmp_path, f"f{i}.jpg", ora)

        assert await w.process_next_group() is True
        assert engine.chiamate_gruppo == 1
        assert engine.chiamate_singole == 0
        from database.photos import get_photo_by_id
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
        from database.photos import get_photo_by_id, get_photos
        nomi = {p["location_name"] for p in get_photos(db, limit=10)}
        assert "NON DEVE SERVIRE" not in nomi

    @pytest.mark.asyncio
    async def test_se_il_blocco_non_valida_si_ricade_sulle_singole(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0, gruppo_rotto=True)
        w, db = self._worker_con(tmp_path, monkeypatch, engine)
        self._foto(db, tmp_path, "a.jpg", "10:00")
        self._foto(db, tmp_path, "b.jpg", "10:05")
        await w.process_next_group()
        from database.queue import get_queue_counts
        # le foto tornano disponibili per la via singola, non finiscono in errore
        assert get_queue_counts(db)["pending"] == 2
        assert get_queue_counts(db)["error"] == 0

    @pytest.mark.asyncio
    async def test_coda_vuota_ritorna_falso(self, tmp_path, monkeypatch):
        engine = EngineDiGruppoFinto(luogo="X", lat=1.0, lon=2.0)
        w, _ = self._worker_con(tmp_path, monkeypatch, engine)
        assert await w.process_next_group() is False
