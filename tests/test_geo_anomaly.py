"""Test per services/geo_anomaly.py — logica pura, nessun database."""
from datetime import datetime

from services.geo_anomaly import (
    ORIGINI_AFFIDABILI,
    Anomalia,
    Gruppo,
    haversine_km,
    prepara,
    raggruppa,
    rileva,
)


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


class TestRileva:
    """Tre foto: due in Egitto e una, in mezzo, dall'altra parte del mondo."""

    def _f(self, pid, ora, lat, lon, src="ai", nome="x"):
        return {"id": pid, "filename": f"{pid}.jpg",
                "exif_date": f"2026-04-01T{ora}:00", "latitude": lat,
                "longitude": lon, "location_name": nome, "location_source": src,
                "t": datetime.fromisoformat(f"2026-04-01T{ora}:00")}

    def test_segnala_la_foto_fuori_scala(self):
        foto = [self._f(1, "10:00", 25.70, 32.64),        # Luxor
                self._f(2, "10:05", 45.07, 7.68),          # Torino
                self._f(3, "10:10", 25.71, 32.65)]         # Luxor
        a = rileva(foto)
        assert len(a) == 1
        assert a[0].foto["id"] == 2
        assert a[0].distanza_km > 2000

    def test_propone_la_precedente(self):
        foto = [self._f(1, "10:00", 25.70, 32.64, nome="Luxor"),
                self._f(2, "10:05", 45.07, 7.68),
                self._f(3, "10:10", 25.71, 32.65, nome="Karnak")]
        a = rileva(foto)
        assert a[0].proposta["id"] == 1

    def test_preferisce_il_gps_vero_alla_precedente(self):
        # la successiva ha coordinate da Takeout: vale piu' di un'ipotesi
        foto = [self._f(1, "10:00", 25.70, 32.64, src="ai"),
                self._f(2, "10:05", 45.07, 7.68),
                self._f(3, "10:10", 25.71, 32.65, src="takeout")]
        a = rileva(foto)
        assert a[0].proposta["id"] == 3

    def test_non_segnala_se_prima_e_dopo_non_concordano(self):
        # giornata di spostamento: nessuno puo' fare da riferimento
        foto = [self._f(1, "10:00", 25.70, 32.64),
                self._f(2, "10:05", 30.00, 31.20),
                self._f(3, "10:10", 45.07, 7.68)]
        assert rileva(foto) == []

    def test_non_segnala_se_i_vicini_sono_lontani_nel_tempo(self):
        foto = [self._f(1, "02:00", 25.70, 32.64),
                self._f(2, "10:05", 45.07, 7.68),
                self._f(3, "18:00", 25.71, 32.65)]
        assert rileva(foto, max_gap_ore=2.0) == []

    def test_non_discute_una_foto_con_gps_vero(self):
        foto = [self._f(1, "10:00", 25.70, 32.64),
                self._f(2, "10:05", 45.07, 7.68, src="takeout"),
                self._f(3, "10:10", 25.71, 32.65)]
        assert rileva(foto) == []

    def test_uno_scarto_piccolo_non_e_anomalia(self):
        foto = [self._f(1, "10:00", 25.70, 32.64),
                self._f(2, "10:05", 25.90, 32.70),   # ~23 km
                self._f(3, "10:10", 25.71, 32.65)]
        assert rileva(foto) == []

    def test_gli_estremi_non_hanno_due_vicini(self):
        foto = [self._f(1, "10:00", 45.07, 7.68),
                self._f(2, "10:05", 25.70, 32.64),
                self._f(3, "10:10", 25.71, 32.65)]
        a = rileva(foto)
        assert [x.foto["id"] for x in a] == []


class TestRaggruppa:
    def _anom(self, pid, ora, lat=45.07, lon=7.68, plat=25.70, plon=32.64, nome="Torino"):
        t = datetime.fromisoformat(f"2026-04-01T{ora}:00")
        return Anomalia(
            foto={"id": pid, "t": t, "latitude": lat, "longitude": lon,
                  "location_name": nome, "location_source": "ai"},
            proposta={"id": 900, "t": t, "latitude": plat, "longitude": plon,
                      "location_name": "Luxor", "location_source": "takeout"},
            distanza_km=2600.0)

    def test_foto_vicine_nel_tempo_e_nello_spazio_sono_un_caso_solo(self):
        g = raggruppa([self._anom(1, "10:00"), self._anom(2, "10:05"),
                       self._anom(3, "10:09")])
        assert len(g) == 1
        assert [f["id"] for f in g[0].foto] == [1, 2, 3]

    def test_nomi_diversi_non_spezzano_il_gruppo(self):
        # l'AI scrive lo stesso posto ogni volta in modo diverso
        g = raggruppa([self._anom(1, "10:00", nome="Tempio di Hathor, Dendera"),
                       self._anom(2, "10:05", nome="Tempio di Dendera")])
        assert len(g) == 1

    def test_luoghi_lontani_restano_casi_distinti(self):
        g = raggruppa([self._anom(1, "10:00", lat=45.07, lon=7.68),
                       self._anom(2, "10:05", lat=59.90, lon=10.68)])
        assert len(g) == 2

    def test_uno_stacco_temporale_apre_un_nuovo_caso(self):
        g = raggruppa([self._anom(1, "10:00"), self._anom(2, "17:00")],
                      finestra_ore=3.0)
        assert len(g) == 2

    def test_la_distanza_del_gruppo_e_la_massima(self):
        a1, a2 = self._anom(1, "10:00"), self._anom(2, "10:05")
        a1.distanza_km = 3000.0
        g = raggruppa([a1, a2])
        assert g[0].distanza_km == 3000.0

    def test_lista_vuota(self):
        assert raggruppa([]) == []
