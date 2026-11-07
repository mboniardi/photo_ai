"""Test della passata di impronte sulla libreria esistente."""
import os

import pytest
from PIL import Image

from database import get_db
from database.photos import insert_photo, foto_senza_impronta, update_photo
from services.impronta_batch import calcola_mancanti


def _inserisci(db, cartella, nome, contenuto=None, colore=(100, 150, 200)):
    """Inserisce una foto; senza `contenuto` scrive un JPEG vero."""
    percorso = str(cartella / nome)
    if contenuto is None:
        Image.new("RGB", (640, 480), colore).save(percorso, "JPEG")
    else:
        with open(percorso, "wb") as f:
            f.write(contenuto)
    return insert_photo(db, file_path=percorso, folder_path=str(cartella),
                        filename=nome, format="jpg")


def _phash(db, pid):
    with get_db(db) as conn:
        return conn.execute("SELECT phash FROM photos WHERE id = ?",
                            (pid,)).fetchone()["phash"]


def test_calcola_le_impronte_mancanti(tmp_db, tmp_path):
    a = _inserisci(tmp_db, tmp_path, "a.jpg")
    b = _inserisci(tmp_db, tmp_path, "b.jpg", colore=(10, 20, 30))
    r = calcola_mancanti(tmp_db)
    assert r == {"elaborate": 2, "errori": 0, "rimaste": 0}
    for pid in (a, b):
        assert len(_phash(tmp_db, pid)) == 16


def test_un_file_illeggibile_viene_contato_e_non_blocca_gli_altri(tmp_db, tmp_path):
    _inserisci(tmp_db, tmp_path, "zero.jpg", contenuto=b"")
    _inserisci(tmp_db, tmp_path, "ok.jpg")
    r = calcola_mancanti(tmp_db)
    assert r["errori"] == 1 and r["elaborate"] == 1


def test_file_mancante_su_disco_e_un_errore(tmp_db, tmp_path):
    pid = _inserisci(tmp_db, tmp_path, "sparita.jpg")
    os.remove(tmp_path / "sparita.jpg")
    r = calcola_mancanti(tmp_db)
    assert r["errori"] == 1 and r["elaborate"] == 0
    assert _phash(tmp_db, pid) is None


def test_non_ricalcola_chi_ce_l_ha_gia(tmp_db, tmp_path):
    _inserisci(tmp_db, tmp_path, "a.jpg")
    calcola_mancanti(tmp_db)
    assert calcola_mancanti(tmp_db)["elaborate"] == 0


def test_rispetta_il_limite_e_riporta_le_rimaste(tmp_db, tmp_path):
    for i in range(3):
        _inserisci(tmp_db, tmp_path, f"{i}.jpg")
    r = calcola_mancanti(tmp_db, limite=2)
    assert r["elaborate"] == 2 and r["rimaste"] == 1


def test_i_file_rotti_non_sono_ripresi_in_loop_nel_lotto(tmp_db, tmp_path):
    # Un file rotto resta con phash NULL: "rimaste" lo conta, ma il lotto
    # non deve ripescarlo all'infinito.
    _inserisci(tmp_db, tmp_path, "zero.jpg", contenuto=b"")
    r = calcola_mancanti(tmp_db)
    assert r == {"elaborate": 0, "errori": 1, "rimaste": 1}


def test_foto_senza_impronta_esclude_cestino_e_gia_calcolate(tmp_db, tmp_path):
    a = _inserisci(tmp_db, tmp_path, "a.jpg")
    cestino = _inserisci(tmp_db, tmp_path, "c.jpg")
    fatta = _inserisci(tmp_db, tmp_path, "f.jpg")
    update_photo(tmp_db, cestino, is_trash=1)
    update_photo(tmp_db, fatta, phash="0" * 16)
    assert [r["id"] for r in foto_senza_impronta(tmp_db)] == [a]


def test_non_scrive_derivati(tmp_db, tmp_path, monkeypatch):
    import config
    store = tmp_path / "derivati"
    monkeypatch.setattr(config, "DERIVATI_PATH", str(store))
    _inserisci(tmp_db, tmp_path, "a.jpg")
    calcola_mancanti(tmp_db)
    assert not store.exists()


def test_su_jpeg_decodifica_a_risoluzione_ridotta(tmp_db, tmp_path):
    # draft() prima del load(): il decoder scala invece di decodificare tutto.
    from unittest.mock import patch
    from PIL import JpegImagePlugin
    _inserisci(tmp_db, tmp_path, "grande.jpg")
    viste = []
    originale = JpegImagePlugin.JpegImageFile.draft

    def spia(self, mode, size):
        # Al momento del draft l'immagine non deve essere ancora decodificata.
        viste.append((mode, size, self._im is None))
        return originale(self, mode, size)

    with patch.object(JpegImagePlugin.JpegImageFile, "draft", spia):
        calcola_mancanti(tmp_db)
    assert viste == [("L", (256, 256), True)]


def test_formato_senza_draft_non_si_rompe(tmp_db, tmp_path):
    # PNG (come HEIC e RAW) non supporta draft: si decodifica normalmente.
    percorso = str(tmp_path / "p.png")
    Image.new("RGB", (64, 64), (1, 2, 3)).save(percorso, "PNG")
    pid = insert_photo(tmp_db, file_path=percorso, folder_path=str(tmp_path),
                       filename="p.png", format="png")
    assert calcola_mancanti(tmp_db)["elaborate"] == 1
    assert len(_phash(tmp_db, pid)) == 16


@pytest.fixture
def client(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB", tmp_db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DERIVATI_PATH", str(tmp_path / "derivati"))
    import config, importlib
    importlib.reload(config)
    from fastapi.testclient import TestClient
    from main import app
    from auth.session import create_session_token
    token = create_session_token({"email": "t@t.com", "name": "T", "picture": ""},
                                 "test-secret")
    return TestClient(app, cookies={"photo_ai_session": token})


def test_rotta_impronte(client, tmp_db, tmp_path):
    _inserisci(tmp_db, tmp_path, "a.jpg")
    resp = client.post("/api/photos/impronte", json={"limite": 10})
    assert resp.status_code == 200
    assert resp.json() == {"elaborate": 1, "errori": 0, "rimaste": 0}


def test_rotta_impronte_rifiuta_limite_non_valido(client):
    assert client.post("/api/photos/impronte", json={"limite": 0}).status_code == 422
