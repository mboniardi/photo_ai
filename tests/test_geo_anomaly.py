"""Test per services/geo_anomaly.py — logica pura, nessun database."""
from datetime import datetime

from services.geo_anomaly import ORIGINI_AFFIDABILI, haversine_km, prepara


class TestHaversine:
    def test_stesso_punto_distanza_zero(self):
        assert haversine_km(45.0, 9.0, 45.0, 9.0) == 0.0

    def test_milano_roma_circa_477_km(self):
        d = haversine_km(45.4642, 9.1900, 41.9028, 12.4964)
        assert 470 < d < 485

    def test_e_simmetrica(self):
        a = haversine_km(24.0, 32.0, 30.0, 31.0)
        b = haversine_km(30.0, 31.0, 24.0, 32.0)
        assert abs(a - b) < 1e-9


class TestPrepara:
    def _riga(self, pid, data, lat=25.0, lon=32.0, src="ai"):
        return {"id": pid, "filename": f"{pid}.jpg", "exif_date": data,
                "latitude": lat, "longitude": lon,
                "location_name": "x", "location_source": src}

    def test_ordina_per_data_di_scatto(self):
        righe = [self._riga(2, "2026-04-01T12:00:00"),
                 self._riga(1, "2026-04-01T09:00:00")]
        out = prepara(righe)
        assert [f["id"] for f in out] == [1, 2]

    def test_aggiunge_il_datetime(self):
        out = prepara([self._riga(1, "2026-04-01T09:00:00")])
        assert out[0]["t"] == datetime(2026, 4, 1, 9, 0, 0)

    def test_scarta_le_date_illeggibili(self):
        out = prepara([self._riga(1, "non una data"),
                       self._riga(2, "2026-04-01T09:00:00")])
        assert [f["id"] for f in out] == [2]

    def test_scarta_chi_non_ha_coordinate(self):
        out = prepara([self._riga(1, "2026-04-01T09:00:00", lat=None),
                       self._riga(2, "2026-04-01T10:00:00", lon=None),
                       self._riga(3, "2026-04-01T11:00:00")])
        assert [f["id"] for f in out] == [3]

    def test_le_origini_affidabili_includono_corrected(self):
        # una foto corretta a mano diventa ancora per le vicine
        assert set(ORIGINI_AFFIDABILI) == {"exif", "takeout", "manual", "corrected"}
