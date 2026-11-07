"""Test per database/doppioni.py: revisione dei doppioni sospetti."""
import pytest

from database import get_db
from database import doppioni
from database.photos import insert_photo, update_photo, get_photo_by_id
from services import derivati


@pytest.fixture
def derivati_tmp(tmp_path, monkeypatch):
    # Lo store dei derivati va isolato: cancella() tocca file veri.
    import config
    monkeypatch.setattr(config, "DERIVATI_PATH", str(tmp_path / "derivati"))


def _foto(db, nome, origine="nas", **extra):
    cartella = "google:/Vacanza" if origine == "google" else "/mnt/nas"
    pid = insert_photo(db, file_path=f"{cartella}/{nome}", folder_path=cartella,
                       filename=nome, format="jpg", file_size=1000,
                       width=100, height=100)
    update_photo(db, pid, origine=origine, **extra)
    return pid


def _sospetto(db, google, nas, motivo="istante", distanza=3):
    with get_db(db) as conn:
        return conn.execute(
            "INSERT INTO doppioni_sospetti (photo_id_google, photo_id_nas, motivo, distanza)"
            " VALUES (?, ?, ?, ?)", (google, nas, motivo, distanza)).lastrowid


def _stato(db, sid):
    with get_db(db) as conn:
        return conn.execute("SELECT stato FROM doppioni_sospetti WHERE id = ?",
                            (sid,)).fetchone()["stato"]


def _in_coda(db, pid):
    with get_db(db) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM analysis_queue WHERE photo_id = ?",
                            (pid,)).fetchone()["n"]


@pytest.fixture
def coppia(tmp_db, derivati_tmp):
    g = _foto(tmp_db, "g.jpg", "google", latitude=45.0, longitude=9.0,
              location_source="takeout")
    n = _foto(tmp_db, "n.jpg", "nas")
    derivati.scrivi(g, "thumb", b"x")
    derivati.scrivi(g, "proxy", b"y")
    return tmp_db, g, n, _sospetto(tmp_db, g, n)


def test_confermare_cancella_la_riga_google_e_i_derivati(coppia):
    db, g, n, sid = coppia
    doppioni.risolvi(db, sid, True)
    assert get_photo_by_id(db, g) is None
    assert derivati.leggi(g, "thumb") is None
    assert derivati.leggi(g, "proxy") is None
    assert get_photo_by_id(db, n) is not None
    assert _stato(db, sid) == "risolto"


def test_confermare_passa_le_coordinate_alla_riga_nas(coppia):
    db, g, n, sid = coppia
    doppioni.risolvi(db, sid, True)
    riga = get_photo_by_id(db, n)
    assert (riga["latitude"], riga["longitude"]) == (45.0, 9.0)
    assert riga["location_source"] == "takeout"


@pytest.mark.parametrize("sorgente", ["exif", "manual", "corrected"])
def test_confermare_non_sovrascrive_una_posizione_protetta(coppia, sorgente):
    db, g, n, sid = coppia
    update_photo(db, n, latitude=10.0, longitude=20.0, location_source=sorgente)
    doppioni.risolvi(db, sid, True)
    riga = get_photo_by_id(db, n)
    assert (riga["latitude"], riga["longitude"]) == (10.0, 20.0)
    assert riga["location_source"] == sorgente
    assert get_photo_by_id(db, g) is None


def test_confermare_senza_coordinate_google_non_tocca_la_riga_nas(tmp_db, derivati_tmp):
    g = _foto(tmp_db, "g.jpg", "google")
    n = _foto(tmp_db, "n.jpg", "nas", latitude=1.0, longitude=2.0, location_source="ai")
    doppioni.risolvi(tmp_db, _sospetto(tmp_db, g, n), True)
    riga = get_photo_by_id(tmp_db, n)
    assert (riga["latitude"], riga["longitude"], riga["location_source"]) == (1.0, 2.0, "ai")


def test_respingere_mette_la_foto_in_coda_ai(coppia):
    db, g, n, sid = coppia
    assert _in_coda(db, g) == 0
    doppioni.risolvi(db, sid, False)
    assert _in_coda(db, g) == 1
    assert _in_coda(db, n) == 0
    assert get_photo_by_id(db, g) is not None
    assert derivati.leggi(g, "thumb") == b"x"
    assert _stato(db, sid) == "respinto"


def test_non_si_risolve_due_volte(coppia):
    db, g, n, sid = coppia
    doppioni.risolvi(db, sid, False)
    with pytest.raises(doppioni.SospettoGiaRisolto):
        doppioni.risolvi(db, sid, True)
    assert get_photo_by_id(db, g) is not None  # la seconda chiamata non ha cancellato
    with pytest.raises(doppioni.SospettoGiaRisolto):
        doppioni.risolvi(db, sid, False)
    assert _in_coda(db, g) == 1


def test_sospetto_inesistente(tmp_db):
    with pytest.raises(doppioni.SospettoNonTrovato):
        doppioni.risolvi(tmp_db, 999, True)


def test_errore_a_meta_non_lascia_il_sospetto_risolto(coppia):
    db, g, n, sid = coppia
    with get_db(db) as conn:  # la riga NAS sparisce: la risoluzione deve fallire intera
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM photos WHERE id = ?", (n,))
    with pytest.raises(LookupError):
        doppioni.risolvi(db, sid, True)
    assert _stato(db, sid) == "pending"
    assert get_photo_by_id(db, g) is not None
    assert derivati.leggi(g, "thumb") == b"x"


def test_confermare_chiude_gli_altri_sospetti_sulla_stessa_foto_google(coppia):
    db, g, n, sid = coppia
    n2 = _foto(db, "n2.jpg", "nas")
    altro = _sospetto(db, g, n2)
    doppioni.risolvi(db, sid, True)
    assert _stato(db, altro) != "pending"


def test_elenca_mostra_solo_i_pendenti(coppia):
    db, g, n, sid = coppia
    g2 = _foto(db, "g2.jpg", "google")
    n2 = _foto(db, "n2.jpg", "nas")
    risolto = _sospetto(db, g2, n2)
    doppioni.risolvi(db, risolto, False)
    elenco = doppioni.elenca_sospetti(db)
    assert [e["id"] for e in elenco] == [sid]
    e = elenco[0]
    assert (e["photo_id_google"], e["photo_id_nas"]) == (g, n)
    assert (e["filename_google"], e["filename_nas"]) == ("g.jpg", "n.jpg")
    assert (e["album_google"], e["album_nas"]) == ("google:/Vacanza", "/mnt/nas")
    assert (e["motivo"], e["distanza"]) == ("istante", 3)
    assert [x["id"] for x in doppioni.elenca_sospetti(db, "respinto")] == [risolto]
