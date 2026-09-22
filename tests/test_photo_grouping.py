"""Test per services/photo_grouping.py — logica pura, nessun database."""
import os
from datetime import datetime

import pytest

from services.photo_grouping import (
    ORIGINI_AFFIDABILI, istante_scatto, prepara, incatena, gruppo_di,
)


def riga(pid, data=None, cartella="/a", percorso=None, src="ai", lat=None):
    return {"photo_id": pid, "exif_date": data, "folder_path": cartella,
            "file_path": percorso or f"/a/{pid}.jpg",
            "location_source": src, "latitude": lat, "longitude": 1.0 if lat else None}


class TestIstanteScatto:
    def test_usa_exif_quando_c_e(self):
        assert istante_scatto(riga(1, "2026-04-01T10:00:00")) == datetime(2026, 4, 1, 10, 0)

    def test_ripiega_sulla_data_del_file(self, tmp_path):
        p = tmp_path / "x.jpg"
        p.write_bytes(b"x")
        os.utime(p, (1_000_000_000, 1_000_000_000))
        t = istante_scatto(riga(1, None, percorso=str(p)))
        assert t == datetime.fromtimestamp(1_000_000_000)

    def test_none_se_non_c_e_ne_l_uno_ne_l_altro(self):
        assert istante_scatto(riga(1, None, percorso="/non/esiste.jpg")) is None

    def test_exif_illeggibile_ripiega_sul_file(self, tmp_path):
        p = tmp_path / "y.jpg"
        p.write_bytes(b"y")
        os.utime(p, (1_000_000_000, 1_000_000_000))
        assert istante_scatto(riga(1, "non una data", percorso=str(p))) is not None


class TestPrepara:
    def test_ordina_cronologicamente(self):
        out = prepara([riga(2, "2026-04-01T12:00:00"), riga(1, "2026-04-01T09:00:00")])
        assert [f["photo_id"] for f in out] == [1, 2]

    def test_scarta_chi_non_ha_nessuna_data(self):
        out = prepara([riga(1, None, percorso="/non/esiste.jpg"),
                       riga(2, "2026-04-01T09:00:00")])
        assert [f["photo_id"] for f in out] == [2]


class TestIncatena:
    def _f(self, pid, minuti, cartella="/a"):
        t = datetime(2026, 4, 1, 10, 0)
        t = t.replace(minute=0) if minuti is None else t
        from datetime import timedelta
        return dict(riga(pid, cartella=cartella), t=datetime(2026, 4, 1, 10, 0) + timedelta(minutes=minuti))

    def test_foto_vicine_stanno_insieme(self):
        g = incatena([self._f(1, 0), self._f(2, 5), self._f(3, 12)])
        assert len(g) == 1 and [f["photo_id"] for f in g[0]] == [1, 2, 3]

    def test_uno_stacco_apre_un_gruppo_nuovo(self):
        g = incatena([self._f(1, 0), self._f(2, 5), self._f(3, 40)])
        assert [[f["photo_id"] for f in x] for x in g] == [[1, 2], [3]]

    def test_la_catena_non_ha_tetto_di_durata(self):
        """Cento foto a cinque minuti l'una dall'altra sono un gruppo solo,
        anche se durano ore: e' lo stesso posto."""
        foto = [self._f(i, i * 5) for i in range(100)]
        g = incatena(foto)
        assert len(g) == 1 and len(g[0]) == 100

    def test_la_catena_non_attraversa_una_cartella(self):
        g = incatena([self._f(1, 0), self._f(2, 5, cartella="/b")])
        assert [[f["photo_id"] for f in x] for x in g] == [[1], [2]]

    def test_il_gap_e_fra_consecutive_non_dalla_prima(self):
        g = incatena([self._f(1, 0), self._f(2, 14), self._f(3, 28)])
        assert len(g) == 1

    def test_gap_configurabile(self):
        foto = [self._f(1, 0), self._f(2, 12)]
        assert len(incatena(foto, gap_minuti=10)) == 2
        assert len(incatena(foto, gap_minuti=15)) == 1

    def test_lista_vuota(self):
        assert incatena([]) == []


class TestGruppoDi:
    def _f(self, pid, minuti):
        from datetime import timedelta
        return dict(riga(pid), t=datetime(2026, 4, 1, 10, 0) + timedelta(minutes=minuti))

    def test_ritorna_la_catena_che_contiene_la_foto(self):
        foto = [self._f(1, 0), self._f(2, 5), self._f(3, 40), self._f(4, 45)]
        assert [f["photo_id"] for f in gruppo_di(foto, 3)] == [3, 4]

    def test_foto_assente_ritorna_lista_vuota(self):
        assert gruppo_di([self._f(1, 0)], 999) == []


def test_origini_affidabili():
    assert set(ORIGINI_AFFIDABILI) == {"exif", "takeout", "manual", "corrected"}
