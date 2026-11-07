"""Test per services/takeout_import.py e per la rotta /api/takeout/importa-album."""
import importlib
import os
import random
import shutil
import sqlite3
import types
import zipfile

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import config
from services import derivati, impronta, takeout_archivio
from services import takeout_import
from services.takeout_dedup import Esito
from services.takeout_import import coordinate_vincono, importa_album
from tests.conftest import _scrivi_sidecar


# ── helper ────────────────────────────────────────────────────────

def _immagine(seed: int, exif: dict = None) -> Image.Image:
    """Immagine 64x64 a rumore: seed diversi danno impronte diverse."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (64, 64))
    img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                 for _ in range(64 * 64)])
    return img


def _scrivi_foto(cartella, nome, seed, lat=None, lon=None, camera=None, istante="1700000000"):
    percorso = os.path.join(cartella, nome)
    img = _immagine(seed)
    if camera:
        exif = Image.Exif()
        exif[0x010F], exif[0x0110] = camera
        img.save(percorso, "JPEG", exif=exif)
    else:
        img.save(percorso, "JPEG")
    if lat is not None:
        _scrivi_sidecar(percorso + ".supplemental-metadata.json", nome, lat, lon, istante)
    return percorso


def _data_exif(percorso, istante_locale):
    """Scrive DateTimeOriginal (ora locale della fotocamera) nel JPEG."""
    import piexif
    exif = piexif.dump({"Exif": {
        piexif.ExifIFD.DateTimeOriginal: istante_locale.replace("-", ":").replace("T", " ")}})
    piexif.insert(exif, percorso)


def _zip_di(cartella_album, zip_path):
    """ZIP con la struttura di Takeout: Takeout/Google Foto/<album>/<file>."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for nome in sorted(os.listdir(cartella_album)):
            zf.write(os.path.join(cartella_album, nome),
                     f"Takeout/Google Foto/Vacanza/{nome}")
    return str(zip_path)


@pytest.fixture
def derivati_tmp(tmp_path, monkeypatch):
    """Isola lo store dei derivati: mai scrivere in /opt/photo_ai."""
    monkeypatch.setattr(config, "DERIVATI_PATH", str(tmp_path / "derivati"))
    return str(tmp_path / "derivati")


@pytest.fixture
def album(tmp_path):
    """Cartella in cui il test mette le foto, e funzione che ne fa uno ZIP."""
    cartella = tmp_path / "sorgente"
    cartella.mkdir()

    def zippa():
        return _zip_di(str(cartella), tmp_path / "album.zip")
    return str(cartella), zippa


@pytest.fixture
def spia_scompatta(monkeypatch):
    """Registra le directory di lavoro usate da scompatta."""
    viste = []
    originale = takeout_archivio.scompatta

    def finta(zip_paths, destinazione):
        viste.append(destinazione)
        return originale(zip_paths, destinazione)
    monkeypatch.setattr(takeout_import.takeout_archivio, "scompatta", finta)
    return viste


def _riga(db, photo_id):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
    finally:
        conn.close()


def _righe(db, sql, *args):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _foto_nas(db, seed, **extra):
    """Foto NAS gia' nel catalogo, con l'impronta dell'immagine `seed`."""
    from database.photos import insert_photo, update_photo
    pid = insert_photo(db, file_path=f"/mnt/nas/{seed}.jpg", folder_path="/mnt/nas",
                       filename=f"{seed}.jpg",
                       **{k: v for k, v in extra.items()
                          if k in ("exif_date", "latitude", "longitude",
                                   "location_source", "camera_make", "camera_model")})
    campi = {"phash": impronta.calcola(_immagine(seed))}
    for k in ("description", "overall_score"):
        if k in extra:
            campi[k] = extra[k]
    update_photo(db, pid, **campi)
    return pid


# ── precedenza coordinate ─────────────────────────────────────────

def test_coordinate_vincono():
    for ok in (None, "", "ai", "takeout"):
        assert coordinate_vincono(ok) is True
    for no in ("exif", "manual", "corrected"):
        assert coordinate_vincono(no) is False


# ── foto gia' presenti ────────────────────────────────────────────

def test_foto_gia_presente_riceve_solo_le_coordinate(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1, 45.5, 9.1)
    pid = _foto_nas(tmp_db, 1, description="mare", overall_score=7.5)
    r = importa_album([zippa()], tmp_db)
    riga = _riga(tmp_db, pid)
    assert riga["latitude"] == pytest.approx(45.5)
    assert riga["longitude"] == pytest.approx(9.1)
    assert riga["location_source"] == "takeout"
    assert riga["description"] == "mare"
    assert riga["overall_score"] == pytest.approx(7.5)
    assert riga["origine"] == "nas"
    assert r["arricchite"] == 1 and r["nuove"] == 0
    assert derivati.leggi(pid, "proxy") is None
    assert _righe(tmp_db, "SELECT * FROM analysis_queue") == []
    assert _righe(tmp_db, "SELECT COUNT(*) AS n FROM photos")[0]["n"] == 1


def test_non_sovrascrive_una_posizione_manuale(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1, 45.5, 9.1)
    pid = _foto_nas(tmp_db, 1, latitude=45.0, longitude=7.0, location_source="manual")
    r = importa_album([zippa()], tmp_db)
    riga = _riga(tmp_db, pid)
    assert riga["latitude"] == pytest.approx(45.0)
    assert riga["longitude"] == pytest.approx(7.0)
    assert riga["location_source"] == "manual"
    assert r["arricchite"] == 0


def test_sovrascrive_una_posizione_indovinata_dall_ai(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1, 45.5, 9.1)
    pid = _foto_nas(tmp_db, 1, latitude=10.0, longitude=10.0, location_source="ai")
    r = importa_album([zippa()], tmp_db)
    riga = _riga(tmp_db, pid)
    assert riga["latitude"] == pytest.approx(45.5)
    assert riga["location_source"] == "takeout"
    assert r["arricchite"] == 1


def test_gia_presente_senza_coordinate_nel_json_non_tocca_nulla(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)  # nessun sidecar
    pid = _foto_nas(tmp_db, 1)
    r = importa_album([zippa()], tmp_db)
    assert _riga(tmp_db, pid)["latitude"] is None
    assert r["arricchite"] == 0 and r["gia_presenti"] == 1


def test_il_risultato_distingue_istante_da_phash(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1, 45.5, 9.1)      # abbinata per impronta
    _scrivi_foto(cartella, "b.jpg", 2, 41.9, 12.5, istante="1600000000")     # abbinata per istante
    _foto_nas(tmp_db, 1)
    voci = {v.nome: v for v in takeout_archivio.leggi(_estrai(zippa(), cartella)).voci}
    # NAS con l'istante di b.jpg e un'impronta compatibile (stessa immagine)
    _foto_nas(tmp_db, 2, exif_date=voci["b.jpg"].scattata_il)
    r = importa_album([zippa()], tmp_db)
    assert r["gia_presenti"] == 2
    assert r["gia_presenti_per_istante"] == 1
    assert r["gia_presenti_per_phash"] == 1


def test_abbina_sull_ora_locale_exif_non_sull_utc_di_google(tmp_db, album, derivati_tmp):
    """
    photoTakenTime e' UTC, photos.exif_date e' l'ora locale della fotocamera:
    per un utente italiano sono sempre una o due ore diverse. L'abbinamento
    per istante deve usare l'EXIF del file dell'archivio — lo stesso valore
    che poi viene scritto e indicizzato — altrimenti la regola 1 non scatta
    mai e tutto ricade sull'impronta, che e' il ripiego.
    """
    cartella, zippa = album
    # 1700000000 = 2023-11-14T22:13:20Z; in Italia era gia' il 14 alle 23:13:20
    locale = "2023-11-14T23:13:20"
    percorso = _scrivi_foto(cartella, "a.jpg", 1, 45.5, 9.1, istante="1700000000")
    _data_exif(percorso, locale)
    voce = takeout_archivio.leggi(_estrai(zippa(), cartella)).voci[0]
    assert voce.scattata_il == "2023-11-14T22:13:20"   # UTC, due ore avanti

    # Stessa immagine (quindi anche l'impronta abbinerebbe): e' il motivo
    # riportato a dire quale delle due regole ha deciso.
    pid = _foto_nas(tmp_db, 1, exif_date=locale)
    r = importa_album([zippa()], tmp_db)

    assert r["gia_presenti_per_istante"] == 1, r
    assert r["gia_presenti_per_phash"] == 0
    assert r["nuove"] == 0 and r["incerte"] == 0
    assert _riga(tmp_db, pid)["latitude"] == pytest.approx(45.5)


def _estrai(zip_path, cartella):
    destinazione = cartella + "_x"
    return takeout_archivio.scompatta([zip_path], destinazione)


# ── foto nuove e incerte ──────────────────────────────────────────

def test_foto_nuova_entra_con_origine_google_e_derivati(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1, 45.5, 9.1)
    r = importa_album([zippa()], tmp_db)
    assert r["nuove"] == 1
    riga = _righe(tmp_db, "SELECT * FROM photos")[0]
    assert riga["origine"] == "google"
    assert riga["file_path"] == "google:/Vacanza/a.jpg"
    assert riga["folder_path"] == "google:/Vacanza"
    assert riga["filename"] == "a.jpg"
    # il JPEG ricomprime: l'impronta e' vicina a quella dell'immagine di partenza, non uguale
    assert impronta.distanza(riga["phash"], impronta.calcola(_immagine(1))) <= 4
    assert riga["derivati_at"]
    assert riga["latitude"] == pytest.approx(45.5)
    assert riga["location_source"] == "takeout"
    assert derivati.leggi(riga["id"], "proxy")
    assert derivati.leggi(riga["id"], "thumb")


def test_foto_nuova_finisce_in_coda_ai(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    importa_album([zippa()], tmp_db)
    pid = _righe(tmp_db, "SELECT id FROM photos")[0]["id"]
    coda = _righe(tmp_db, "SELECT photo_id, status FROM analysis_queue")
    assert [(c["photo_id"], c["status"]) for c in coda] == [(pid, "pending")]


def test_foto_incerta_non_finisce_in_coda_ai(tmp_db, album, derivati_tmp, monkeypatch):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    nas = _foto_nas(tmp_db, 99)
    monkeypatch.setattr(takeout_import, "decidi",
                        lambda *a, **k: Esito("incerta", nas, None, 9))
    r = importa_album([zippa()], tmp_db)
    assert r["incerte"] == 1 and r["nuove"] == 0
    assert _righe(tmp_db, "SELECT * FROM analysis_queue") == []
    nuova = _righe(tmp_db, "SELECT id FROM photos WHERE origine = 'google'")[0]["id"]
    assert derivati.leggi(nuova, "proxy")
    dop = _righe(tmp_db, "SELECT * FROM doppioni_sospetti")
    assert len(dop) == 1
    assert (dop[0]["photo_id_google"], dop[0]["photo_id_nas"]) == (nuova, nas)
    assert dop[0]["distanza"] == 9 and dop[0]["stato"] == "pending"


def test_la_fotocamera_dell_archivio_arriva_a_decidi(tmp_db, album, derivati_tmp, monkeypatch):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1, camera=("Canon", "EOS 5D"))
    viste = []

    def spia(voce, impronta_voce, indice, camera_make=None, camera_model=None,
             istante=None):
        viste.append((camera_make, camera_model, impronta_voce, istante))
        return Esito("nuova")
    monkeypatch.setattr(takeout_import, "decidi", spia)
    importa_album([zippa()], tmp_db)
    assert viste[0][:2] == ("Canon", "EOS 5D")
    assert viste[0][2]


def test_nomi_duplicati_nello_stesso_album_danno_due_voci(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "IMG_1234.jpg", 1)
    _scrivi_foto(cartella, "IMG_1234(1).jpg", 2)
    r = importa_album([zippa()], tmp_db)
    assert r["nuove"] == 2 and r["errori"] == 0
    assert _righe(tmp_db, "SELECT COUNT(*) AS n FROM photos")[0]["n"] == 2


def test_la_stessa_foto_in_due_album_entra_una_volta_sola(tmp_db, tmp_path, derivati_tmp):
    # Takeout esporta una copia della foto in ogni album a cui appartiene
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    _scrivi_foto(str(a), "x.jpg", 1, 45.5, 9.1)
    shutil.copy(a / "x.jpg", b / "x.jpg")
    shutil.copy(a / "x.jpg.supplemental-metadata.json", b / "x.jpg.supplemental-metadata.json")
    percorso_zip = str(tmp_path / "due.zip")
    with zipfile.ZipFile(percorso_zip, "w") as zf:
        for album_, cart in (("Uno", a), ("Due", b)):
            for nome in os.listdir(cart):
                zf.write(cart / nome, f"Takeout/Google Foto/{album_}/{nome}")
    r = importa_album([percorso_zip], tmp_db)
    assert r["nuove"] == 1 and r["gia_presenti"] == 1
    assert _righe(tmp_db, "SELECT COUNT(*) AS n FROM photos")[0]["n"] == 1


def test_la_stessa_foto_in_due_album_per_impronta_senza_istante(tmp_db, tmp_path, derivati_tmp):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    _scrivi_foto(str(a), "x.jpg", 1)
    shutil.copy(a / "x.jpg", b / "x.jpg")
    percorso_zip = str(tmp_path / "due.zip")
    with zipfile.ZipFile(percorso_zip, "w") as zf:
        for album_, cart in (("Uno", a), ("Due", b)):
            zf.write(cart / "x.jpg", f"Takeout/Google Foto/{album_}/x.jpg")
    r = importa_album([percorso_zip], tmp_db)
    assert r["nuove"] == 1 and r["gia_presenti_per_phash"] == 1
    assert _righe(tmp_db, "SELECT COUNT(*) AS n FROM photos")[0]["n"] == 1


@pytest.mark.parametrize("sorgente", ["corrected", "exif"])
def test_non_sovrascrive_posizioni_corrette_o_exif(tmp_db, album, derivati_tmp, sorgente):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1, 45.5, 9.1)
    pid = _foto_nas(tmp_db, 1, latitude=45.0, longitude=7.0, location_source=sorgente)
    r = importa_album([zippa()], tmp_db)
    riga = _riga(tmp_db, pid)
    assert riga["latitude"] == pytest.approx(45.0)
    assert riga["longitude"] == pytest.approx(7.0)
    assert riga["location_source"] == sorgente
    assert r["arricchite"] == 0
    # la copia dell'archivio e' stata abbinata, non inserita come nuova
    assert r["gia_presenti"] == 1 and r["nuove"] == 0


@pytest.mark.parametrize("guasto", ["add_to_queue", "_registra_sospetto"])
def test_guasto_dopo_l_insert_non_lascia_righe_orfane(
        tmp_db, album, derivati_tmp, monkeypatch, guasto):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    if guasto == "_registra_sospetto":
        nas = _foto_nas(tmp_db, 99)
        monkeypatch.setattr(takeout_import, "decidi",
                            lambda *a, **k: Esito("incerta", nas, None, 9))

    def rotta(*a, **k):
        raise sqlite3.OperationalError("database locked")
    monkeypatch.setattr(takeout_import, guasto, rotta)
    r = importa_album([zippa()], tmp_db)
    assert r["errori"] == 1 and r["nuove"] == 0 and r["incerte"] == 0
    assert _righe(tmp_db, "SELECT id FROM photos WHERE origine = 'google'") == []
    assert _righe(tmp_db, "SELECT * FROM analysis_queue") == []
    assert _righe(tmp_db, "SELECT * FROM doppioni_sospetti") == []


def test_due_copie_di_un_incerta_hanno_ognuna_la_propria_revisione(tmp_db, tmp_path, derivati_tmp):
    # N (NAS) e' a distanza "incerta" da A; B e' copia di A in un altro album.
    # B non deve fondersi con A: se l'utente risolvesse A come doppione di N e
    # la cancellasse, B sparirebbe senza essere mai stata confrontata con N.
    from database.photos import update_photo
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    _scrivi_foto(str(a), "x.jpg", 1)
    shutil.copy(a / "x.jpg", b / "x.jpg")
    percorso_zip = str(tmp_path / "due.zip")
    with zipfile.ZipFile(percorso_zip, "w") as zf:
        for album_, cart in (("Uno", a), ("Due", b)):
            zf.write(cart / "x.jpg", f"Takeout/Google Foto/{album_}/x.jpg")
    h_archivio = impronta.calcola(Image.open(a / "x.jpg"))
    distanza = config.TAKEOUT_PHASH_CERTO + 1
    assert distanza <= config.TAKEOUT_PHASH_INCERTO
    h_nas = format(int(h_archivio, 16) ^ ((1 << distanza) - 1), "016x")
    nas = _foto_nas(tmp_db, 99)
    update_photo(tmp_db, nas, phash=h_nas)

    r = importa_album([percorso_zip], tmp_db)
    assert r["incerte"] == 2 and r["gia_presenti"] == 0
    dop = _righe(tmp_db, "SELECT photo_id_nas FROM doppioni_sospetti")
    assert [d["photo_id_nas"] for d in dop] == [nas, nas]


# ── errori ────────────────────────────────────────────────────────

def test_un_file_corrotto_viene_contato_e_gli_altri_proseguono(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "buona.jpg", 1)
    with open(os.path.join(cartella, "rotta.jpg"), "wb") as fh:
        fh.write(b"non sono un jpeg")
    r = importa_album([zippa()], tmp_db)
    assert r["errori"] == 1 and r["nuove"] == 1
    # nessuna riga vuota per la foto rotta: l'originale sta per sparire
    nomi = [x["filename"] for x in _righe(tmp_db, "SELECT filename FROM photos")]
    assert nomi == ["buona.jpg"]


def test_derivato_non_generabile_non_lascia_una_riga_vuota(tmp_db, album, derivati_tmp, monkeypatch):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    _scrivi_foto(cartella, "b.jpg", 2)
    originale = takeout_import.image_processor.generate_proxy

    def proxy(path, *a, **k):
        if path.endswith("a.jpg"):
            raise OSError("disco pieno")
        return originale(path, *a, **k)
    monkeypatch.setattr(takeout_import.image_processor, "generate_proxy", proxy)
    r = importa_album([zippa()], tmp_db)
    assert r["errori"] == 1 and r["nuove"] == 1
    assert [x["filename"] for x in _righe(tmp_db, "SELECT filename FROM photos")] == ["b.jpg"]
    assert len(_righe(tmp_db, "SELECT * FROM analysis_queue")) == 1


def test_scrittura_del_derivato_fallita_toglie_la_riga(tmp_db, album, derivati_tmp, monkeypatch):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)

    def rotta(*a, **k):
        raise OSError("scrittura fallita")
    monkeypatch.setattr(takeout_import.derivati, "scrivi", rotta)
    r = importa_album([zippa()], tmp_db)
    assert r["errori"] == 1 and r["nuove"] == 0
    assert _righe(tmp_db, "SELECT * FROM photos") == []
    assert _righe(tmp_db, "SELECT * FROM analysis_queue") == []


# ── ripulitura, ZIP, spazio ───────────────────────────────────────

def test_la_directory_di_lavoro_viene_rimossa_e_gli_zip_restano(
        tmp_db, album, derivati_tmp, spia_scompatta):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    percorso_zip = zippa()
    r = importa_album([percorso_zip], tmp_db)
    assert len(spia_scompatta) == 1
    assert not os.path.exists(spia_scompatta[0])
    assert os.path.exists(percorso_zip)
    assert r["zip_da_rimuovere"] == [percorso_zip]


def test_rifiuta_se_lo_spazio_non_basta(tmp_db, album, derivati_tmp, monkeypatch, spia_scompatta):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    _scrivi_foto(cartella, "b.jpg", 2)
    monkeypatch.setattr(takeout_import.shutil, "disk_usage",
                        lambda p: types.SimpleNamespace(total=10**12, used=10**12 - 1000, free=1000))
    with pytest.raises(HTTPException) as exc:
        importa_album([zippa()], tmp_db)
    assert exc.value.status_code == 507
    assert _righe(tmp_db, "SELECT * FROM photos") == []
    assert not os.path.exists(derivati_tmp)
    assert not os.path.exists(spia_scompatta[0])


def test_lo_spazio_si_misura_sulla_cartella_dei_derivati(
        tmp_db, album, derivati_tmp, monkeypatch):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    viste = []
    reale = takeout_import.shutil.disk_usage

    def spia(p):
        viste.append(p)
        return reale(p)
    monkeypatch.setattr(takeout_import.shutil, "disk_usage", spia)
    importa_album([zippa()], tmp_db)
    assert len(viste) == 1
    # la cartella puo' non esistere ancora: si misura il primo antenato esistente
    assert os.path.exists(viste[0]) and derivati_tmp.startswith(viste[0])


# ── passata di impronte ───────────────────────────────────────────

def _foto_senza_impronta(db, nome="vecchia.jpg", exif_date=None):
    """Foto NAS mai passata dal calcolo delle impronte: phash NULL."""
    from database.photos import insert_photo
    return insert_photo(db, file_path=f"/mnt/nas/{nome}", folder_path="/mnt/nas",
                        filename=nome, exif_date=exif_date)


def test_rifiuta_l_import_se_la_passata_di_impronte_non_e_finita(
        tmp_db, album, derivati_tmp, spia_scompatta):
    """
    Senza impronta la salvaguardia di decidi() non puo' scattare: un
    abbinamento per solo istante fonde a scatola chiusa e perde la foto
    dell'archivio. E' l'unica configurazione che perde una foto.
    """
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    _foto_senza_impronta(tmp_db)
    with pytest.raises(HTTPException) as exc:
        importa_album([zippa()], tmp_db)
    assert exc.value.status_code == 409
    assert "impronte" in exc.value.detail
    assert _righe(tmp_db, "SELECT id FROM photos WHERE origine = 'google'") == []
    assert spia_scompatta == []      # non si scompatta nemmeno


def test_con_forza_importa_lo_stesso_e_dice_quante_ne_mancano(
        tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    _foto_senza_impronta(tmp_db)
    r = importa_album([zippa()], tmp_db, forza=True)
    assert r["senza_impronta"] == 1
    assert r["nuove"] == 1


def test_il_risultato_riporta_le_foto_senza_impronta(tmp_db, album, derivati_tmp):
    cartella, zippa = album
    _scrivi_foto(cartella, "a.jpg", 1)
    _foto_nas(tmp_db, 5)
    r = importa_album([zippa()], tmp_db)
    assert r["senza_impronta"] == 0


# ── rotta ─────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "api.db")
    monkeypatch.setenv("LOCAL_DB", db)
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DERIVATI_PATH", str(tmp_path / "derivati_api"))
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    # Altri test (test_main) lasciano una whitelist sull'app: qui non serve.
    monkeypatch.setattr(app.state, "whitelist", None, raising=False)
    from auth.session import create_session_token
    token = create_session_token({"email": "test@test.com", "name": "Test", "picture": ""}, "test-secret")
    monkeypatch.setattr(config, "PHOTOS_PATH", str(tmp_path / "nas"))
    monkeypatch.setattr(config, "APP_DATA_PATH", str(tmp_path / "appdata"))
    os.makedirs(tmp_path / "nas")
    return TestClient(app, cookies={"photo_ai_session": token}), db


def test_rotta_importa_un_album(client, tmp_path):
    c, db = client
    sorgente = tmp_path / "src"
    sorgente.mkdir()
    _scrivi_foto(str(sorgente), "a.jpg", 1, 45.5, 9.1)
    percorso_zip = _zip_di(str(sorgente), tmp_path / "nas" / "album.zip")
    resp = c.post("/api/takeout/importa-album", json={"zip_paths": [percorso_zip]})
    assert resp.status_code == 200, resp.text
    dati = resp.json()
    assert dati["nuove"] == 1
    pid = _righe(db, "SELECT id FROM photos")[0]["id"]
    assert os.path.exists(os.path.join(str(tmp_path / "derivati_api"), f"{pid % 100:02d}"))


def test_rotta_rifiuta_percorsi_fuori_dalle_radici(client, tmp_path):
    c, _ = client
    fuori = tmp_path / "altrove.zip"
    fuori.write_bytes(b"x")
    resp = c.post("/api/takeout/importa-album", json={"zip_paths": [str(fuori)]})
    assert resp.status_code == 400


def test_rotta_rifiuta_traversal_e_inesistenti(client, tmp_path):
    c, _ = client
    (tmp_path / "segreto.zip").write_bytes(b"x")
    nas = str(tmp_path / "nas")
    assert c.post("/api/takeout/importa-album",
                  json={"zip_paths": [nas + "/../segreto.zip"]}).status_code == 400
    assert c.post("/api/takeout/importa-album",
                  json={"zip_paths": [nas + "/non_esiste.zip"]}).status_code == 400


def test_rotta_rifiuta_lista_vuota(client):
    c, _ = client
    assert c.post("/api/takeout/importa-album", json={"zip_paths": []}).status_code == 422



def test_la_rotta_rifiuta_se_mancano_le_impronte(client, tmp_path):
    c, db = client
    _foto_senza_impronta(db)
    sorgente = tmp_path / "src2"
    sorgente.mkdir()
    _scrivi_foto(str(sorgente), "a.jpg", 1)
    percorso_zip = _zip_di(str(sorgente), tmp_path / "nas" / "b.zip")
    resp = c.post("/api/takeout/importa-album", json={"zip_paths": [percorso_zip]})
    assert resp.status_code == 409, resp.text
    assert "impronte" in resp.json()["detail"]

    resp = c.post("/api/takeout/importa-album",
                  json={"zip_paths": [percorso_zip], "forza": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["senza_impronta"] == 1
    assert resp.json()["nuove"] == 1
