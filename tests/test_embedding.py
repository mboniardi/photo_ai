"""Test per services/embedding.py — embedder Ollama con HTTP simulato."""
import httpx
import pytest


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError(f"HTTP {self.status_code}")


class _FakeClient:
    """Sostituisce httpx.AsyncClient e registra la richiesta inviata."""

    def __init__(self, response, recorder):
        self._response = response
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        self._recorder["url"] = url
        self._recorder["json"] = json
        return self._response


def _patch_httpx(monkeypatch, payload, status_code=200):
    recorder = {}
    response = _FakeResponse(payload, status_code)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda *a, **kw: _FakeClient(response, recorder),
    )
    return recorder


class TestOllamaEmbedderInterface:
    def test_implements_embedder(self):
        from services.embedding import Embedder, OllamaEmbedder
        assert issubclass(OllamaEmbedder, Embedder)

    def test_dimension_is_1024(self):
        from services.embedding import OllamaEmbedder
        assert OllamaEmbedder().dimension == 1024

    def test_strips_trailing_slash_from_base_url(self):
        from services.embedding import OllamaEmbedder
        e = OllamaEmbedder(base_url="http://host:11434/")
        assert e._base_url == "http://host:11434"


class TestEmbed:
    async def test_returns_single_vector(self, monkeypatch):
        from services.embedding import OllamaEmbedder
        _patch_httpx(monkeypatch, {"embeddings": [[0.1, 0.2, 0.3]]})
        result = await OllamaEmbedder().embed("tramonto sul mare")
        assert result == [0.1, 0.2, 0.3]

    async def test_sends_correct_request(self, monkeypatch):
        from services.embedding import OllamaEmbedder
        rec = _patch_httpx(monkeypatch, {"embeddings": [[0.1]]})
        await OllamaEmbedder(base_url="http://host:11434", model="bge-m3").embed("ciao")
        assert rec["url"] == "http://host:11434/api/embed"
        assert rec["json"] == {"model": "bge-m3", "input": ["ciao"]}

    async def test_raises_on_http_error(self, monkeypatch):
        from services.embedding import OllamaEmbedder
        _patch_httpx(monkeypatch, {}, status_code=500)
        with pytest.raises(httpx.HTTPError):
            await OllamaEmbedder().embed("ciao")


class TestEmbedBatch:
    async def test_returns_one_vector_per_text(self, monkeypatch):
        from services.embedding import OllamaEmbedder
        _patch_httpx(monkeypatch, {"embeddings": [[0.1], [0.2], [0.3]]})
        result = await OllamaEmbedder().embed_batch(["a", "b", "c"])
        assert result == [[0.1], [0.2], [0.3]]

    async def test_sends_all_texts_in_one_call(self, monkeypatch):
        from services.embedding import OllamaEmbedder
        rec = _patch_httpx(monkeypatch, {"embeddings": [[0.1], [0.2]]})
        await OllamaEmbedder().embed_batch(["a", "b"])
        assert rec["json"]["input"] == ["a", "b"]

    async def test_empty_list_makes_no_request(self, monkeypatch):
        from services.embedding import OllamaEmbedder
        rec = _patch_httpx(monkeypatch, {"embeddings": []})
        result = await OllamaEmbedder().embed_batch([])
        assert result == []
        assert rec == {}
