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
