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
