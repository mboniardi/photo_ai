"""Test dello store dei derivati su disco (thumb + proxy)."""
import pytest

import config
from services import derivati


def test_percorso_distribuisce_su_due_livelli():
    p = derivati.percorso(123456, "thumb")
    assert p.endswith("/123456_thumb.jpg")
    assert "/56/34/" in p          # due livelli dall'id, cifre meno significative


def test_percorso_rifiuta_un_tipo_sconosciuto():
    with pytest.raises(ValueError):
        derivati.percorso(1, "originale")


def test_scrivi_e_rileggi(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DERIVATI_PATH", str(tmp_path))
    derivati.scrivi(7, "proxy", b"xyz")
    assert derivati.leggi(7, "proxy") == b"xyz"


def test_leggi_assente_ritorna_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DERIVATI_PATH", str(tmp_path))
    assert derivati.leggi(999, "thumb") is None


def test_cancella_rimuove_entrambi(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DERIVATI_PATH", str(tmp_path))
    derivati.scrivi(7, "thumb", b"a"); derivati.scrivi(7, "proxy", b"b")
    assert derivati.cancella(7) == 2
    assert derivati.leggi(7, "thumb") is None


def test_scrivi_non_lascia_file_temporanei(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DERIVATI_PATH", str(tmp_path))
    p = derivati.scrivi(7, "thumb", b"a")
    derivati.scrivi(7, "thumb", b"b")   # sovrascrittura
    import os
    assert os.listdir(os.path.dirname(p)) == ["7_thumb.jpg"]
    assert derivati.leggi(7, "thumb") == b"b"


def test_cancella_su_foto_senza_derivati_ritorna_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DERIVATI_PATH", str(tmp_path))
    assert derivati.cancella(12345) == 0
