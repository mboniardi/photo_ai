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


import json

from services.ai.prompt import (
    build_location_prompt, parse_location_response,
    build_group_prompt, parse_group_response,
)


class TestPromptLuogo:
    def test_dichiara_quante_foto_e_lo_stesso_luogo(self):
        p = build_location_prompt(8)
        assert "8" in p
        assert "stesso luogo" in p.lower()

    def test_chiede_solo_il_luogo(self):
        p = build_location_prompt(5)
        assert "luogo_riconosciuto" in p and "luogo_lat" in p and "luogo_lon" in p
        assert "descrizione" not in p.lower()


class TestParseLuogo:
    def test_estrae_il_luogo(self):
        d = parse_location_response('{"luogo_riconosciuto": "Karnak", "luogo_lat": 25.7, "luogo_lon": 32.6}')
        assert d["luogo_riconosciuto"] == "Karnak"
        assert d["luogo_lat"] == 25.7 and d["luogo_lon"] == 32.6

    def test_tollera_i_delimitatori_markdown(self):
        d = parse_location_response('```json\n{"luogo_riconosciuto": "Giza", "luogo_lat": 30.0, "luogo_lon": 31.1}\n```')
        assert d["luogo_riconosciuto"] == "Giza"

    def test_luogo_non_riconosciuto(self):
        d = parse_location_response('{"luogo_riconosciuto": null, "luogo_lat": null, "luogo_lon": null}')
        assert d["luogo_riconosciuto"] is None

    def test_json_invalido_solleva(self):
        with pytest.raises(ValueError):
            parse_location_response("non sono json")


class TestPromptGruppo:
    def test_dichiara_il_luogo_come_gia_noto(self):
        p = build_group_prompt(12, "Tempio di Karnak, Luxor")
        assert "Tempio di Karnak, Luxor" in p
        assert "12" in p

    def test_impone_la_lunghezza_minima(self):
        p = build_group_prompt(12, "Karnak", min_caratteri=350)
        assert "350" in p

    def test_chiede_descrizioni_diverse_fra_loro(self):
        p = build_group_prompt(4, "Karnak")
        assert "divers" in p.lower()


def _voce(n, descr=None):
    return {"n": n, "descrizione": descr or ("descrizione numero %d, abbastanza lunga" % n),
            "punteggio_tecnico": 7, "punteggio_estetico": 8, "soggetto": "s",
            "atmosfera": "serena", "colori_dominanti": ["a"], "punti_di_forza": "f",
            "punti_di_debolezza": None}


class TestParseGruppo:
    def test_accetta_una_risposta_completa(self):
        testo = json.dumps({"foto": [_voce(1), _voce(2), _voce(3)]})
        voci = parse_group_response(testo, 3)
        assert [v["n"] for v in voci] == [1, 2, 3]

    def test_riordina_per_indice(self):
        testo = json.dumps({"foto": [_voce(3), _voce(1), _voce(2)]})
        assert [v["n"] for v in parse_group_response(testo, 3)] == [1, 2, 3]

    def test_rifiuta_se_mancano_voci(self):
        testo = json.dumps({"foto": [_voce(1), _voce(2)]})
        with pytest.raises(ValueError, match="voci"):
            parse_group_response(testo, 3)

    def test_rifiuta_se_ce_ne_sono_troppe(self):
        testo = json.dumps({"foto": [_voce(1), _voce(2), _voce(3), _voce(4)]})
        with pytest.raises(ValueError, match="voci"):
            parse_group_response(testo, 3)

    def test_rifiuta_indici_incompleti(self):
        """Due voci con lo stesso indice: non si sa a quale foto appartengano."""
        testo = json.dumps({"foto": [_voce(1), _voce(1), _voce(3)]})
        with pytest.raises(ValueError, match="indic"):
            parse_group_response(testo, 3)

    def test_rifiuta_descrizioni_identiche(self):
        """Se il modello ripete la stessa descrizione, non ha guardato le foto."""
        testo = json.dumps({"foto": [_voce(1, "uguale"), _voce(2, "uguale"), _voce(3, "diversa")]})
        with pytest.raises(ValueError, match="distint"):
            parse_group_response(testo, 3)

    def test_rifiuta_json_invalido(self):
        with pytest.raises(ValueError):
            parse_group_response("{rotto", 3)

    def test_rifiuta_una_voce_senza_descrizione(self):
        v = _voce(2); v["descrizione"] = ""
        testo = json.dumps({"foto": [_voce(1), v, _voce(3)]})
        with pytest.raises(ValueError):
            parse_group_response(testo, 3)
