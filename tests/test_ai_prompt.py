"""Test per services/ai/prompt.py — prompt e parsing condivisi fra i motori."""
import json
import pytest

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


class TestParseResponse:
    def test_parses_valid_json(self):
        from services.ai.prompt import parse_response
        result = parse_response(VALID_JSON_RESPONSE)
        assert result["descrizione"] == "Un paesaggio montano al tramonto."
        assert result["colori_dominanti"] == ["arancione", "viola", "blu"]

    def test_strips_markdown_fences(self):
        from services.ai.prompt import parse_response
        result = parse_response(f"```json\n{VALID_JSON_RESPONSE}\n```")
        assert result["punteggio_estetico"] == 9

    def test_raises_on_invalid_json(self):
        from services.ai.prompt import parse_response
        with pytest.raises(ValueError):
            parse_response("non è json")

    def test_raises_on_missing_required_field(self):
        from services.ai.prompt import parse_response
        with pytest.raises(ValueError):
            parse_response(json.dumps({"descrizione": "solo questo"}))


class TestBuildPrompt:
    def test_prompt_without_location(self):
        from services.ai.prompt import build_prompt
        prompt = build_prompt(location_hint="")
        assert "luogo_riconosciuto" in prompt
        assert "CONTESTO GEOGRAFICO" not in prompt

    def test_prompt_with_location(self):
        from services.ai.prompt import build_prompt
        prompt = build_prompt(location_hint="Venezia, Italia")
        assert "Venezia, Italia" in prompt
        assert "CONTESTO GEOGRAFICO" in prompt
