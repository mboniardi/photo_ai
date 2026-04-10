"""
Test per services/geocoder.py.
Nominatim è un servizio esterno: lo mocker con pytest monkeypatch su httpx.
"""
import pytest
import httpx


class TestReverseGeocode:
    async def test_returns_city_country(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(self, url, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self):
                    return {
                        "address": {
                            "city": "Roma",
                            "country": "Italia",
                        }
                    }
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(41.9028, 12.4964)
        assert result == "Roma, Italia"

    async def test_returns_none_on_http_error(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(self, url, **kwargs):
            raise httpx.RequestError("timeout", request=None)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(0.0, 0.0)
        assert result is None

    async def test_returns_none_when_no_city(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(self, url, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self):
                    return {"address": {}}  # nessuna città
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(0.0, 0.0)
        assert result is None

    async def test_uses_correct_nominatim_url(self, monkeypatch):
        from services.geocoder import reverse_geocode
        captured = {}

        async def mock_get(self, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params", {})
            class FakeResp:
                status_code = 200
                def json(self): return {"address": {"city": "X", "country": "Y"}}
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        await reverse_geocode(45.0, 9.0)
        assert "nominatim.openstreetmap.org" in captured["url"]
        assert captured["params"]["lat"] == 45.0
        assert captured["params"]["lon"] == 9.0

    async def test_falls_back_to_town(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(self, url, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self):
                    return {"address": {"town": "Spoleto", "country": "Italia"}}
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(42.7, 12.7)
        assert result == "Spoleto, Italia"

    async def test_returns_country_only_when_no_city(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(self, url, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self):
                    return {"address": {"country": "Oceano Atlantico"}}
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(0.0, -30.0)
        assert result == "Oceano Atlantico"

    async def test_returns_none_on_http_status_error(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(self, url, **kwargs):
            class FakeResp:
                status_code = 429
                def raise_for_status(self):
                    request = httpx.Request("GET", "https://nominatim.openstreetmap.org/reverse")
                    response = httpx.Response(429, request=request)
                    raise httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)
                def json(self): return {}
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(0.0, 0.0)
        assert result is None
