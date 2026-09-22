"""Test per services/ai/deepseek.py — HTTP simulato, nessuna chiamata reale."""
import json
import httpx
import pytest

VALID_JSON_RESPONSE = json.dumps({
    "descrizione": "Il Colosseo all'ora blu.",
    "punteggio_tecnico": 8,
    "punteggio_estetico": 9,
    "soggetto": "anfiteatro romano",
    "atmosfera": "drammatica",
    "colori_dominanti": ["ambra", "blu"],
    "punti_di_forza": "Ottima luce.",
    "punti_di_debolezza": None,
    "luogo_riconosciuto": "Colosseo, Roma",
    "luogo_lat": 41.8902,
    "luogo_lon": 12.4922,
})


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
    def __init__(self, response, recorder):
        self._response = response
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self._recorder["url"] = url
        self._recorder["headers"] = headers
        self._recorder["json"] = json
        return self._response


def _patch_httpx(monkeypatch, content=VALID_JSON_RESPONSE, status_code=200):
    recorder = {}
    payload = {"choices": [{"message": {"content": content}}]}
    response = _FakeResponse(payload, status_code)
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda *a, **kw: _FakeClient(response, recorder))
    return recorder


class TestDeepSeekEngineInterface:
    def test_implements_aiengine(self):
        from services.ai.deepseek import DeepSeekEngine
        from services.ai.base import AIEngine
        assert issubclass(DeepSeekEngine, AIEngine)

    def test_requires_api_key(self):
        from services.ai.deepseek import DeepSeekEngine
        with pytest.raises(ValueError, match="API key"):
            DeepSeekEngine(api_key="")

    def test_max_side_px_from_config(self):
        import config
        from services.ai.deepseek import DeepSeekEngine
        assert DeepSeekEngine(api_key="k").max_side_px == config.DEEPSEEK_MAX_SIDE_PX


class TestAnalyze:
    async def test_returns_photo_analysis(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        _patch_httpx(monkeypatch)
        result = await DeepSeekEngine(api_key="k").analyze(b"fakejpeg")
        assert result.description == "Il Colosseo all'ora blu."
        assert result.technical_score == 8
        assert result.location_name == "Colosseo, Roma"
        assert result.overall_score == round(0.35 * 8 + 0.65 * 9, 1)

    async def test_records_engine_name(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        _patch_httpx(monkeypatch)
        result = await DeepSeekEngine(api_key="k", model="deepseek-flash").analyze(b"x")
        assert result.ai_engine == "deepseek/deepseek-flash"

    async def test_sends_image_as_base64_data_url(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        rec = _patch_httpx(monkeypatch)
        await DeepSeekEngine(api_key="segreto").analyze(b"fakejpeg")
        assert rec["url"] == "https://api.deepseek.com/chat/completions"
        assert rec["headers"]["Authorization"] == "Bearer segreto"
        content = rec["json"]["messages"][0]["content"]
        assert content[0]["type"] == "text"
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    async def test_location_hint_reaches_the_prompt(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        rec = _patch_httpx(monkeypatch)
        await DeepSeekEngine(api_key="k").analyze(b"x", location_hint="Roma, Italia")
        assert "Roma, Italia" in rec["json"]["messages"][0]["content"][0]["text"]

    async def test_raises_on_invalid_json_from_model(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        _patch_httpx(monkeypatch, content="non è json")
        with pytest.raises(ValueError):
            await DeepSeekEngine(api_key="k").analyze(b"x")

    async def test_raises_on_http_error(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        _patch_httpx(monkeypatch, status_code=401)
        with pytest.raises(httpx.HTTPError):
            await DeepSeekEngine(api_key="k").analyze(b"x")


class TestThinkingAndTokenBudget:
    """deepseek-flash e' un modello di ragionamento: senza disattivarlo consuma
    l'intero budget di token nella catena di pensiero e restituisce content vuoto."""

    async def test_disables_thinking_by_default(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        rec = _patch_httpx(monkeypatch)
        await DeepSeekEngine(api_key="k").analyze(b"x")
        assert rec["json"]["thinking"] == {"type": "disabled"}

    async def test_token_budget_comes_from_config(self, monkeypatch):
        import config
        from services.ai.deepseek import DeepSeekEngine
        monkeypatch.setattr(config, "DEEPSEEK_MAX_TOKENS", 4321)
        rec = _patch_httpx(monkeypatch)
        await DeepSeekEngine(api_key="k").analyze(b"x")
        assert rec["json"]["max_tokens"] == 4321

    async def test_thinking_mode_is_configurable(self, monkeypatch):
        import config
        from services.ai.deepseek import DeepSeekEngine
        monkeypatch.setattr(config, "DEEPSEEK_THINKING", "enabled")
        rec = _patch_httpx(monkeypatch)
        await DeepSeekEngine(api_key="k").analyze(b"x")
        assert rec["json"]["thinking"] == {"type": "enabled"}


class TestSupportaGruppi:
    def test_deepseek_dichiara_di_supportarli(self):
        from services.ai.deepseek import DeepSeekEngine
        assert DeepSeekEngine(api_key="k").supporta_gruppi is True

    def test_la_base_no(self):
        from services.ai.base import AIEngine
        assert AIEngine.supporta_gruppi is False


def _risposta_gruppo(contenuto: str):
    return {"choices": [{"message": {"content": contenuto}}],
            "usage": {"total_tokens": 100}}


class TestIdentifyLocation:
    @pytest.mark.asyncio
    async def test_ritorna_il_luogo(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        catturato = {}

        async def finto_post(self, url, **kw):
            catturato["json"] = kw["json"]
            return httpx.Response(200, json=_risposta_gruppo(
                '{"luogo_riconosciuto": "Karnak", "luogo_lat": 25.7, "luogo_lon": 32.6}'),
                request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "post", finto_post)
        d = await DeepSeekEngine(api_key="k").identify_location([b"a", b"b", b"c"])
        assert d["luogo_riconosciuto"] == "Karnak"
        assert d["luogo_lat"] == 25.7

    @pytest.mark.asyncio
    async def test_manda_tutte_le_immagini_in_una_sola_chiamata(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        catturato = {}

        async def finto_post(self, url, **kw):
            catturato["json"] = kw["json"]
            return httpx.Response(200, json=_risposta_gruppo(
                '{"luogo_riconosciuto": null, "luogo_lat": null, "luogo_lon": null}'),
                request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "post", finto_post)
        await DeepSeekEngine(api_key="k").identify_location([b"a", b"b", b"c"])
        parti = catturato["json"]["messages"][0]["content"]
        assert sum(1 for p in parti if p["type"] == "image_url") == 3
        assert sum(1 for p in parti if p["type"] == "text") == 1

    @pytest.mark.asyncio
    async def test_lista_vuota_non_chiama_l_api(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine

        async def esplodi(self, url, **kw):
            raise AssertionError("non doveva chiamare l'API")
        monkeypatch.setattr(httpx.AsyncClient, "post", esplodi)
        d = await DeepSeekEngine(api_key="k").identify_location([])
        assert d["luogo_riconosciuto"] is None


class TestAnalyzeGroup:
    def _voci(self, n):
        return {"foto": [{"n": i + 1, "descrizione": "descrizione lunga numero %d" % i,
                          "punteggio_tecnico": 7, "punteggio_estetico": 8,
                          "soggetto": "s%d" % i, "atmosfera": "serena",
                          "colori_dominanti": ["blu"], "punti_di_forza": "f",
                          "punti_di_debolezza": None} for i in range(n)]}

    @pytest.mark.asyncio
    async def test_ritorna_un_analisi_per_foto(self, monkeypatch):
        from services.ai.base import PhotoAnalysis
        from services.ai.deepseek import DeepSeekEngine

        async def finto_post(self, url, **kw):
            return httpx.Response(200, json=_risposta_gruppo(json.dumps(self_voci)),
                                  request=httpx.Request("POST", url))
        self_voci = self._voci(3)
        monkeypatch.setattr(httpx.AsyncClient, "post", finto_post)
        out = await DeepSeekEngine(api_key="k").analyze_group([b"a", b"b", b"c"], "Karnak")
        assert len(out) == 3
        assert all(isinstance(x, PhotoAnalysis) for x in out)

    @pytest.mark.asyncio
    async def test_applica_il_luogo_a_tutte(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        self_voci = self._voci(2)

        async def finto_post(self, url, **kw):
            return httpx.Response(200, json=_risposta_gruppo(json.dumps(self_voci)),
                                  request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "post", finto_post)
        out = await DeepSeekEngine(api_key="k").analyze_group(
            [b"a", b"b"], "Karnak", latitudine=25.7, longitudine=32.6)
        assert all(x.location_name == "Karnak" for x in out)
        assert all(x.latitude == 25.7 and x.longitude == 32.6 for x in out)

    @pytest.mark.asyncio
    async def test_una_risposta_incompleta_solleva(self, monkeypatch):
        from services.ai.deepseek import DeepSeekEngine
        self_voci = self._voci(2)          # due voci per tre immagini

        async def finto_post(self, url, **kw):
            return httpx.Response(200, json=_risposta_gruppo(json.dumps(self_voci)),
                                  request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx.AsyncClient, "post", finto_post)
        with pytest.raises(ValueError):
            await DeepSeekEngine(api_key="k").analyze_group([b"a", b"b", b"c"], "Karnak")
