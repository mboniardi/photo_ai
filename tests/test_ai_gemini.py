"""
Test per services/ai/gemini.py.
I test di integrazione reale sono skippati se GEMINI_API_KEY non è impostata.
I test di parsing usano mock.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


VALID_JSON_RESPONSE = json.dumps({
    "descrizione": "Un paesaggio montano al tramonto.",
    "punteggio_tecnico": 8,
    "punteggio_estetico": 9,
    "soggetto": "montagna al tramonto",
    "atmosfera": "romantica",
    "colori_dominanti": ["arancione", "viola", "blu"],
    "punti_di_forza": "Ottima luce dorata.",
    "punti_di_debolezza": None,
    "luogo_riconosciuto": None,
    "luogo_lat": None,
    "luogo_lon": None,
})


class TestParseAiResponse:
    def test_parses_valid_json(self):
        from services.ai.gemini import _parse_response
        result = _parse_response(VALID_JSON_RESPONSE)
        assert result["descrizione"] == "Un paesaggio montano al tramonto."
        assert result["punteggio_tecnico"] == 8
        assert result["colori_dominanti"] == ["arancione", "viola", "blu"]

    def test_strips_markdown_fences(self):
        from services.ai.gemini import _parse_response
        wrapped = f"```json\n{VALID_JSON_RESPONSE}\n```"
        result = _parse_response(wrapped)
        assert result["punteggio_estetico"] == 9

    def test_raises_on_invalid_json(self):
        from services.ai.gemini import _parse_response
        with pytest.raises(ValueError):
            _parse_response("non è json")

    def test_raises_on_missing_required_field(self):
        from services.ai.gemini import _parse_response
        incomplete = json.dumps({"descrizione": "solo questo"})
        with pytest.raises(ValueError):
            _parse_response(incomplete)


class TestBuildPrompt:
    def test_prompt_without_location(self):
        from services.ai.gemini import _build_prompt
        prompt = _build_prompt(location_hint="")
        assert "JSON" in prompt
        assert "luogo_riconosciuto" in prompt
        assert "[SE DISPONIBILE" not in prompt

    def test_prompt_with_location(self):
        from services.ai.gemini import _build_prompt
        prompt = _build_prompt(location_hint="Venezia, Italia")
        assert "Venezia, Italia" in prompt


class TestGeminiEngineInterface:
    def test_implements_aiengine(self):
        from services.ai.gemini import GeminiEngine
        from services.ai.base import AIEngine
        assert issubclass(GeminiEngine, AIEngine)

    def test_requires_api_key(self):
        from services.ai.gemini import GeminiEngine
        with pytest.raises(ValueError, match="API key"):
            GeminiEngine(api_key="")
