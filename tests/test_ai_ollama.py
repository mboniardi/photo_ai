"""
Test per services/ai/ollama.py.
Ollama è locale: mock del client ollama.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

VALID_JSON = json.dumps({
    "descrizione": "Un gatto su un divano.",
    "punteggio_tecnico": 6,
    "punteggio_estetico": 7,
    "soggetto": "gatto su divano",
    "atmosfera": "serena",
    "colori_dominanti": ["grigio", "beige"],
    "punti_di_forza": "Buona composizione.",
    "punti_di_debolezza": None,
    "luogo_riconosciuto": None,
    "luogo_lat": None,
    "luogo_lon": None,
})


class TestOllamaEngineInterface:
    def test_implements_aiengine(self):
        from services.ai.ollama import OllamaEngine
        from services.ai.base import AIEngine
        assert issubclass(OllamaEngine, AIEngine)

    def test_instantiates_with_defaults(self):
        from services.ai.ollama import OllamaEngine
        engine = OllamaEngine()
        assert engine is not None

    def test_custom_models(self):
        from services.ai.ollama import OllamaEngine
        engine = OllamaEngine(
            vision_model="moondream",
            embed_model="nomic-embed-text",
            base_url="http://localhost:11434",
        )
        assert engine._vision_model == "moondream"


class TestOllamaAnalyze:
    async def test_returns_photo_analysis(self, monkeypatch):
        from services.ai.ollama import OllamaEngine
        from services.ai.base import PhotoAnalysis

        async def mock_chat(**kwargs):
            return {"message": {"content": VALID_JSON}}

        engine = OllamaEngine()
        monkeypatch.setattr(engine._client, "chat", mock_chat)
        result = await engine.analyze(b"fake_jpeg_bytes")
        assert isinstance(result, PhotoAnalysis)
        assert result.technical_score == 6
        assert result.ai_engine == "ollama"


class TestOllamaEmbed:
    async def test_returns_list_of_floats(self, monkeypatch):
        from services.ai.ollama import OllamaEngine

        async def mock_embeddings(**kwargs):
            return {"embedding": [0.1, 0.2, 0.3]}

        engine = OllamaEngine()
        monkeypatch.setattr(engine._client, "embeddings", mock_embeddings)
        result = await engine.embed("testo di prova")
        assert isinstance(result, list)
        assert result[0] == pytest.approx(0.1)
