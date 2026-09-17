"""Test per api/search.py."""
import json
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_analyzed_photo(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo, update_photo
    init_db(db)
    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (100, 80)).save(photo_path, "JPEG")
    pid = insert_photo(db, file_path=photo_path, folder_path=str(tmp_path),
                       filename="test.jpg", format="jpg", file_size=1000,
                       width=100, height=80)
    update_photo(db, pid, overall_score=8.0,
                 embedding=json.dumps([1.0, 0.0, 0.0]),
                 analyzed_at="2023-06-01T10:00:00")
    from main import app
    from auth.session import create_session_token
    token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token}), pid


class FakeEmbedder:
    @property
    def dimension(self):
        return 3

    async def embed(self, text: str) -> list:
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts: list) -> list:
        return [[1.0, 0.0, 0.0] for _ in texts]


def _fake_embedder_factory():
    return lambda: FakeEmbedder()


class TestSearchPhotos:
    def test_returns_200(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        resp = c.post("/api/search", json={"query": "paesaggi"})
        assert resp.status_code == 200

    def test_returns_list(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        data = c.post("/api/search", json={"query": "paesaggi"}).json()
        assert isinstance(data, list)

    def test_result_has_similarity(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        data = c.post("/api/search", json={"query": "paesaggi"}).json()
        assert len(data) == 1
        assert "similarity" in data[0]

    def test_empty_query_returns_400(self, client_with_analyzed_photo, monkeypatch):
        c, _ = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        resp = c.post("/api/search", json={"query": "   "})
        assert resp.status_code == 400

    def test_with_orientation_filter(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        data = c.post("/api/search",
                      json={"query": "paesaggi", "orientation": "horizontal"}).json()
        assert len(data) == 1

    def test_vertical_filter_excludes_photo(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        # Photo is 100x80 (horizontal); vertical filter should return 0
        data = c.post("/api/search",
                      json={"query": "paesaggi", "orientation": "vertical"}).json()
        assert len(data) == 0


class TestReembedUsesEmbedder:
    def test_reembed_writes_new_vectors(self, client_with_analyzed_photo, monkeypatch):
        import api.search as m
        import config as cfg
        from database.photos import get_photo_by_id, update_photo
        c, pid = client_with_analyzed_photo
        # La foto della fixture non ha testo: senza descrizione il re-embed
        # la salta, perché non c'è nulla da vettorizzare.
        update_photo(cfg.LOCAL_DB, pid, description="Un tramonto sul mare",
                     subject="tramonto", atmosphere="serena",
                     embedding=json.dumps([9.9, 9.9, 9.9]))

        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        resp = c.post("/api/search/reembed")
        assert resp.status_code == 200

        photo = get_photo_by_id(cfg.LOCAL_DB, pid)
        assert json.loads(photo["embedding"]) == [1.0, 0.0, 0.0]

    def test_reembed_skips_photos_without_text(self, client_with_analyzed_photo, monkeypatch):
        import api.search as m
        import config as cfg
        from database.photos import get_photo_by_id, update_photo
        c, pid = client_with_analyzed_photo  # fixture: nessuna descrizione
        # Sentinella diversa da quella che ritorna FakeEmbedder, così
        # "saltata" e "rivettorizzata" sono distinguibili.
        update_photo(cfg.LOCAL_DB, pid, embedding=json.dumps([7.7, 7.7, 7.7]))

        monkeypatch.setattr(m, "get_embedder", _fake_embedder_factory())
        c.post("/api/search/reembed")

        photo = get_photo_by_id(cfg.LOCAL_DB, pid)
        assert json.loads(photo["embedding"]) == [7.7, 7.7, 7.7]

    def test_reembed_leaves_embeddings_when_batch_count_mismatches(
        self, client_with_analyzed_photo, monkeypatch
    ):
        import api.search as m
        import config as cfg
        from database.photos import get_photo_by_id, insert_photo, update_photo

        class ShortBatchEmbedder:
            @property
            def dimension(self):
                return 3

            async def embed(self, text: str) -> list:
                return [1.0, 0.0, 0.0]

            async def embed_batch(self, texts: list) -> list:
                # Risposta ben formata ma con meno vettori dei testi inviati:
                # solo il primo, invece di uno per ogni testo del lotto.
                return [[1.0, 0.0, 0.0]] if texts else []

        c, pid = client_with_analyzed_photo
        # Sentinella diversa da quella che ritornerebbe l'embedder, così
        # "lasciata intatta" e "rivettorizzata" sono distinguibili.
        update_photo(cfg.LOCAL_DB, pid, description="Un tramonto sul mare",
                     subject="tramonto", atmosphere="serena",
                     embedding=json.dumps([5.5, 5.5, 5.5]))

        # Una seconda foto analizzata con testo, per portare il lotto a 2
        # testi mentre l'embedder finto ne ritorna solo 1.
        pid2 = insert_photo(cfg.LOCAL_DB, file_path="/tmp/test2.jpg",
                             folder_path="/tmp", filename="test2.jpg",
                             format="jpg", file_size=1000, width=100, height=80)
        update_photo(cfg.LOCAL_DB, pid2, description="Un bosco d'autunno",
                     subject="bosco", atmosphere="malinconica",
                     analyzed_at="2023-06-01T10:00:00",
                     embedding=json.dumps([6.6, 6.6, 6.6]))

        monkeypatch.setattr(m, "get_embedder", lambda: ShortBatchEmbedder())
        resp = c.post("/api/search/reembed")
        assert resp.status_code == 200

        photo1 = get_photo_by_id(cfg.LOCAL_DB, pid)
        photo2 = get_photo_by_id(cfg.LOCAL_DB, pid2)
        assert json.loads(photo1["embedding"]) == [5.5, 5.5, 5.5]
        assert json.loads(photo2["embedding"]) == [6.6, 6.6, 6.6]

        status = c.get("/api/search/reembed/status").json()
        assert status["running"] is False
        assert status["total"] == 2
        assert status["done"] == 0
        assert status["failed"] == 2
        assert status["error"] is not None

    def test_reembed_all_batches_fail_sets_error_and_does_not_claim_success(
        self, client_with_analyzed_photo, monkeypatch
    ):
        """
        Un embedder che fallisce sempre (es. Ollama irraggiungibile) deve
        far terminare la re-indicizzazione con "error" impostato, non con
        un falso successo: altrimenti l'operatore crede che la migrazione
        sia andata a buon fine mentre nessuna foto è stata rivettorizzata.
        """
        import api.search as m
        import config as cfg
        from database.photos import get_photo_by_id, update_photo

        class AlwaysFailingEmbedder:
            @property
            def dimension(self):
                return 3

            async def embed(self, text: str) -> list:
                return [1.0, 0.0, 0.0]

            async def embed_batch(self, texts: list) -> list:
                raise RuntimeError("Ollama non raggiungibile")

        c, pid = client_with_analyzed_photo
        update_photo(cfg.LOCAL_DB, pid, description="Un tramonto sul mare",
                     subject="tramonto", atmosphere="serena",
                     embedding=json.dumps([5.5, 5.5, 5.5]))

        monkeypatch.setattr(m, "get_embedder", lambda: AlwaysFailingEmbedder())
        resp = c.post("/api/search/reembed")
        assert resp.status_code == 200

        # L'embedding vecchio non deve essere toccato.
        photo = get_photo_by_id(cfg.LOCAL_DB, pid)
        assert json.loads(photo["embedding"]) == [5.5, 5.5, 5.5]

        status = c.get("/api/search/reembed/status").json()
        assert status["running"] is False
        assert status["done"] == 0
        assert status["failed"] == 1
        assert status["error"] is not None
        assert "non re-indicizzate" in status["error"]

    def test_reembed_skips_batch_with_wrong_vector_dimension(
        self, client_with_analyzed_photo, monkeypatch
    ):
        """
        Se l'embedder restituisce vettori di dimensione diversa da quella
        dichiarata (es. OLLAMA_EMBED_MODEL punta a un modello sbagliato),
        il lotto va scartato come fallito — non scritto silenziosamente.
        """
        import api.search as m
        import config as cfg
        from database.photos import get_photo_by_id, update_photo

        class WrongDimensionEmbedder:
            @property
            def dimension(self):
                return 3

            async def embed(self, text: str) -> list:
                return [1.0, 0.0, 0.0]

            async def embed_batch(self, texts: list) -> list:
                # Vettori di dimensione 2 invece dei 3 dichiarati.
                return [[1.0, 0.0] for _ in texts]

        c, pid = client_with_analyzed_photo
        update_photo(cfg.LOCAL_DB, pid, description="Un tramonto sul mare",
                     subject="tramonto", atmosphere="serena",
                     embedding=json.dumps([5.5, 5.5, 5.5]))

        monkeypatch.setattr(m, "get_embedder", lambda: WrongDimensionEmbedder())
        resp = c.post("/api/search/reembed")
        assert resp.status_code == 200

        photo = get_photo_by_id(cfg.LOCAL_DB, pid)
        assert json.loads(photo["embedding"]) == [5.5, 5.5, 5.5]

        status = c.get("/api/search/reembed/status").json()
        assert status["failed"] == 1
        assert status["done"] == 0
        assert status["error"] is not None
