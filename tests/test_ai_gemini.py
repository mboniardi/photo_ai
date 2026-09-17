"""
Test per services/ai/gemini.py.
I test di integrazione reale sono skippati se GEMINI_API_KEY non è impostata.
I test di parsing usano mock.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGeminiEngineInterface:
    def test_implements_aiengine(self):
        from services.ai.gemini import GeminiEngine
        from services.ai.base import AIEngine
        assert issubclass(GeminiEngine, AIEngine)

    def test_requires_api_key(self):
        from services.ai.gemini import GeminiEngine
        with pytest.raises(ValueError, match="API key"):
            GeminiEngine(api_key="")
