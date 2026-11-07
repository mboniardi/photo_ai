"""Test del riconoscimento dei doppioni fra archivio Takeout e catalogo.

L'errore grave e' fondere due foto diverse (se ne perde una); il doppione non
riconosciuto costa solo una voce in piu'. Questi test difendono il primo caso.
"""
import sqlite3

from services import impronta
from services.takeout_archivio import Voce
from services.takeout_dedup import Esito, costruisci_indice, decidi
from tests.test_impronta import _foto_sintetica

ISTANTE = "2023-07-15T14:32:00"


def _inserisci(db_path, nome, exif_date=None, phash=None,
               make="Canon", model="EOS", is_trash=0):
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO photos (file_path, folder_path, filename, exif_date, "
        "camera_make, camera_model, phash, is_trash) VALUES (?,?,?,?,?,?,?,?)",
        (f"/nas/{nome}", "/nas", nome, exif_date, make, model, phash, is_trash))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def _voce(scattata_il=None):
    return Voce(percorso_file="/tmp/x.jpg", nome="x.jpg", album="Vacanza",
                scattata_il=scattata_il, latitudine=45.0, longitudine=9.0)


def test_istante_uguale_e_gia_presente(tmp_db):
    pid = _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE)
    esito = decidi(_voce(ISTANTE), None, costruisci_indice(tmp_db))
    assert isinstance(esito, Esito)
    assert (esito.decisione, esito.photo_id, esito.motivo) == ("gia_presente", pid, "istante")


def test_corrispondenza_multipla_per_istante_resta_certa(tmp_db):
    primo = _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE)
    _inserisci(tmp_db, "b.jpg", exif_date=ISTANTE)  # raffica
    esito = decidi(_voce(ISTANTE), None, costruisci_indice(tmp_db))
    assert esito.decisione == "gia_presente"
    assert esito.motivo == "istante"
    assert esito.photo_id == primo


def test_senza_exif_date_non_abbina_per_null(tmp_db):
    # Scansioni di diapositive: nessun istante di scatto, tutte exif_date NULL.
    _inserisci(tmp_db, "s1.jpg", exif_date=None)
    _inserisci(tmp_db, "s2.jpg", exif_date=None)
    esito = decidi(_voce(None), None, costruisci_indice(tmp_db))
    assert esito.decisione == "nuova"


def test_indice_esclude_le_righe_con_exif_date_nullo(tmp_db):
    _inserisci(tmp_db, "s1.jpg", exif_date=None)
    _inserisci(tmp_db, "s2.jpg", exif_date=None)
    indice = costruisci_indice(tmp_db)
    assert not any(k[0] is None for k in indice.per_istante)
    assert indice.per_istante == {}


def test_istante_senza_corrispondenza_non_abbina(tmp_db):
    _inserisci(tmp_db, "a.jpg", exif_date="2020-01-01T00:00:00")
    esito = decidi(_voce(ISTANTE), None, costruisci_indice(tmp_db))
    assert esito.decisione == "nuova"


def test_foto_nel_cestino_non_assorbe_la_voce(tmp_db):
    _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE, is_trash=1)
    esito = decidi(_voce(ISTANTE), None, costruisci_indice(tmp_db))
    assert esito.decisione == "nuova"


def test_impronta_vicina_e_gia_presente(tmp_db):
    foto = _foto_sintetica(600, 400, seme=3)
    h = impronta.calcola(foto)
    pid = _inserisci(tmp_db, "a.jpg", phash=h)
    esito = decidi(_voce(None), h, costruisci_indice(tmp_db))
    assert (esito.decisione, esito.photo_id, esito.motivo, esito.distanza) == (
        "gia_presente", pid, "phash", 0)


def test_impronta_a_meta_strada_e_incerta(tmp_db):
    h = "0000000000000000"
    pid = _inserisci(tmp_db, "a.jpg", phash=h)
    voce_h = f"{(1 << 9) - 1:016x}"  # 9 bit di differenza
    esito = decidi(_voce(None), voce_h, costruisci_indice(tmp_db))
    assert (esito.decisione, esito.photo_id, esito.distanza) == ("incerta", pid, 9)


def test_nessuna_corrispondenza_e_nuova(tmp_db):
    _inserisci(tmp_db, "a.jpg", phash="0000000000000000")
    esito = decidi(_voce(None), "ffffffffffffffff", costruisci_indice(tmp_db))
    assert esito.decisione == "nuova"
    assert esito.photo_id is None


def test_senza_impronta_e_senza_istante_e_nuova(tmp_db):
    _inserisci(tmp_db, "a.jpg", phash="0000000000000000")
    assert decidi(_voce(None), None, costruisci_indice(tmp_db)).decisione == "nuova"


def test_catalogo_senza_phash_non_rompe(tmp_db):
    _inserisci(tmp_db, "a.jpg", phash=None)
    assert decidi(_voce(None), "0000000000000000",
                  costruisci_indice(tmp_db)).decisione == "nuova"


def test_foto_solo_simile_non_e_gia_presente(tmp_db):
    """Il caso che costerebbe una foto: stessa scena, inquadratura spostata.

    Dalla stessa foto sintetica si ritaglia via una fascia di 40 px a sinistra
    (circa 3% della larghezza): non e' la stessa foto, ma la distanza cade
    nella fascia incerta, molto sotto i 20 bit di due immagini a caso.
    """
    originale = _foto_sintetica(1200, 800, seme=0)
    simile = originale.crop((40, 0, 1200, 800))
    h_nas = impronta.calcola(originale)
    h_voce = impronta.calcola(simile)
    d = impronta.distanza(h_nas, h_voce)
    # Precondizione: il caso costruito sta davvero nella fascia incerta.
    import config
    assert config.TAKEOUT_PHASH_CERTO < d <= config.TAKEOUT_PHASH_INCERTO

    pid = _inserisci(tmp_db, "a.jpg", phash=h_nas)
    esito = decidi(_voce(None), h_voce, costruisci_indice(tmp_db))
    assert esito.decisione == "incerta"
    assert esito.decisione != "gia_presente"
    assert (esito.photo_id, esito.distanza) == (pid, d)


def test_stesso_istante_due_fotocamere_sceglie_quella_giusta(tmp_db):
    """Due corpi macchina nello stesso secondo: con la fotocamera nota la
    voce va alla riga giusta, non alla prima per istante."""
    _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE, model="EOS 5D")
    giusta = _inserisci(tmp_db, "b.jpg", exif_date=ISTANTE, model="EOS R6")
    esito = decidi(_voce(ISTANTE), None, costruisci_indice(tmp_db),
                   camera_make="Canon", camera_model="EOS R6")
    assert (esito.decisione, esito.photo_id, esito.motivo) == ("gia_presente", giusta, "istante")


def test_fotocamera_diversa_non_abbina_per_istante(tmp_db):
    """Stesso istante ma fotocamera che non compare: non e' un doppione per
    istante, si ricade sull'impronta."""
    _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE, model="EOS 5D")
    _inserisci(tmp_db, "b.jpg", exif_date=ISTANTE, model="EOS R6")
    indice = costruisci_indice(tmp_db)
    esito = decidi(_voce(ISTANTE), None, indice,
                   camera_make="Nikon", camera_model="D850")
    assert esito.decisione == "nuova"
    # E se l'impronta e' vicina, decide l'impronta.
    pid = _inserisci(tmp_db, "c.jpg", phash="0000000000000000")
    esito = decidi(_voce(ISTANTE), "0000000000000000", costruisci_indice(tmp_db),
                   camera_make="Nikon", camera_model="D850")
    assert (esito.decisione, esito.photo_id, esito.motivo) == ("gia_presente", pid, "phash")


def test_fotocamera_parziale_ricade_sul_solo_istante(tmp_db):
    pid = _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE)
    esito = decidi(_voce(ISTANTE), None, costruisci_indice(tmp_db),
                   camera_make="Canon", camera_model=None)
    assert (esito.decisione, esito.photo_id) == ("gia_presente", pid)


def test_istante_uguale_ma_impronta_lontana_e_incerta(tmp_db):
    """Stesso istante e stessa fotocamera, ma le immagini non c'entrano: una
    foto di un altro contributore nello stesso secondo. Non si butta via."""
    pid = _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE, phash="0000000000000000")
    esito = decidi(_voce(ISTANTE), "ffffffffffffffff", costruisci_indice(tmp_db),
                   camera_make="Canon", camera_model="EOS")
    assert esito.decisione == "incerta"
    assert (esito.photo_id, esito.motivo, esito.distanza) == (
        pid, "istante_ma_impronta_lontana", 64)


def test_istante_con_impronta_dentro_la_fascia_resta_gia_presente(tmp_db):
    """Una raffica: fotogrammi della stessa scena, impronte entro INCERTO."""
    pid = _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE, phash="0000000000000000")
    esito = decidi(_voce(ISTANTE), f"{(1 << 12) - 1:016x}", costruisci_indice(tmp_db))
    assert (esito.decisione, esito.photo_id, esito.motivo) == ("gia_presente", pid, "istante")


def test_istante_senza_impronta_su_un_lato_resta_gia_presente(tmp_db):
    pid = _inserisci(tmp_db, "a.jpg", exif_date=ISTANTE, phash=None)
    esito = decidi(_voce(ISTANTE), "ffffffffffffffff", costruisci_indice(tmp_db))
    assert (esito.decisione, esito.photo_id) == ("gia_presente", pid)
    _inserisci(tmp_db, "b.jpg", exif_date="2020-01-01T00:00:00", phash="0000000000000000")
    esito = decidi(_voce("2020-01-01T00:00:00"), None, costruisci_indice(tmp_db))
    assert esito.decisione == "gia_presente"


def test_confine_certo_si_fonde_e_certo_piu_uno_e_incerta(tmp_db):
    import config
    c = config.TAKEOUT_PHASH_CERTO
    pid = _inserisci(tmp_db, "a.jpg", phash="0000000000000000")
    indice = costruisci_indice(tmp_db)
    esito = decidi(_voce(None), f"{(1 << c) - 1:016x}", indice)
    assert (esito.decisione, esito.photo_id, esito.motivo, esito.distanza) == (
        "gia_presente", pid, "phash", c)
    esito = decidi(_voce(None), f"{(1 << (c + 1)) - 1:016x}", indice)
    assert (esito.decisione, esito.photo_id, esito.distanza) == ("incerta", pid, c + 1)


def test_phash_stringa_vuota_e_escluso_dall_indice(tmp_db):
    _inserisci(tmp_db, "a.jpg", phash="")
    indice = costruisci_indice(tmp_db)
    assert indice.impronte == []
    assert decidi(_voce(None), "0000000000000000", indice).decisione == "nuova"
