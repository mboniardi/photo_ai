"""
Import di un album Google Takeout nel catalogo.

Mette insieme i moduli precedenti: scompatta gli ZIP, decide per ogni foto se
il catalogo la ha gia', e agisce di conseguenza. Alla fine non resta su disco
nessuna copia a piena risoluzione: la directory di lavoro viene cancellata e
delle foto che esistono solo su Google restano thumb e proxy.
"""
import logging
import os
import shutil
import tempfile
from typing import Optional

from fastapi import HTTPException

import config
from database import get_db
from database.folders import (get_folder_by_path, insert_folder,
                              update_folder_counts)
from database.photos import (conta_foto_senza_impronta, count_photos,
                             delete_photo_by_path,
                             get_photo_by_id, get_photo_id_by_path,
                             insert_photo, update_photo)
from database.queue import add_to_queue
from services import derivati, image_processor, impronta, takeout_archivio
from services.exif_reader import read_exif
from services.scanner import _EXT_TO_FORMAT
from services.takeout_dedup import costruisci_indice, decidi

logger = logging.getLogger(__name__)

# Stima prudente di thumb + proxy per foto, per il controllo dello spazio libero.
BYTE_PER_FOTO = 700 * 1024

# Posizioni che un import puo' sostituire: assenti, indovinate dall'AI o gia'
# arrivate da un precedente Takeout. Le altre (exif, manual, corrected) sono
# dati certi o corretti a mano: un import non li disfa mai.
_SORGENTI_SOSTITUIBILI = {None, "", "ai", "takeout"}


def coordinate_vincono(location_source: Optional[str]) -> bool:
    """True se le coordinate di Takeout possono sostituire quelle presenti."""
    return location_source in _SORGENTI_SOSTITUIBILI


def _controlla_spazio(n_foto: int) -> None:
    percorso = config.DERIVATI_PATH
    while not os.path.exists(percorso) and os.path.dirname(percorso) != percorso:
        percorso = os.path.dirname(percorso)
    libero = shutil.disk_usage(percorso).free
    servono = n_foto * BYTE_PER_FOTO
    if libero < servono:
        raise HTTPException(
            status_code=507,
            detail=f"Spazio insufficiente per i derivati: liberi {libero // 1024} KB, "
                   f"ne servono circa {servono // 1024} KB")


def _arricchisci(db_path: str, photo_id: int, voce) -> bool:
    """Scrive le coordinate della voce sulla riga esistente, se la precedenza
    lo consente. Ritorna True se ha scritto. Non tocca nient'altro."""
    if voce.latitudine is None or voce.longitudine is None:
        return False
    riga = get_photo_by_id(db_path, photo_id)
    if riga is None or not coordinate_vincono(riga["location_source"]):
        return False
    update_photo(db_path, photo_id, latitude=voce.latitudine,
                 longitude=voce.longitudine, location_source="takeout")
    return True


def _nome_album(voce) -> str:
    """L'album e' l'ultima cartella del percorso: "Takeout/Google Foto/Vacanza"
    diventa "Vacanza" (il prefisso cambia con la lingua dell'account)."""
    return os.path.basename(voce.album.rstrip("/\\")) or voce.album


def _assicura_cartella(db_path: str, album: str) -> None:
    """Crea la riga in `folders` per l'album di Google e ne aggiorna i conteggi.

    Senza questa riga l'album non esiste per la barra laterale: GET
    /api/folders seleziona FROM folders, e le foto resterebbero visibili solo
    nella griglia non filtrata. `folder_path` e' "google:/<album>", che non e'
    una directory: scan e rescan lo rifiutano gia' da soli (os.path.isdir).
    """
    percorso = f"google:/{album}"
    if get_folder_by_path(db_path, percorso) is None:
        insert_folder(db_path, folder_path=percorso, display_name=album)
    update_folder_counts(
        db_path, percorso,
        photo_count=count_photos(db_path, folder_path=percorso, is_trash=False),
        analyzed_count=count_photos(db_path, folder_path=percorso,
                                    analyzed_only=True, is_trash=False))


def _inserisci_google(db_path: str, voce, meta: dict, phash: str,
                      thumb: bytes, proxy: bytes) -> int:
    """Inserisce la foto solo-Google con i suoi derivati. Se qualcosa va storto
    dopo l'inserimento toglie la riga e i file: niente voci vuote."""
    album = _nome_album(voce)
    file_path = f"google:/{album}/{voce.nome}"
    if get_photo_id_by_path(db_path, file_path) is not None:
        raise ValueError(f"Esiste gia' una foto con percorso {file_path}")
    ext = os.path.splitext(voce.nome)[1].lower()
    ha_coordinate = voce.latitudine is not None and voce.longitudine is not None
    photo_id = insert_photo(
        db_path,
        file_path=file_path,
        folder_path=f"google:/{album}",
        filename=voce.nome,
        format=_EXT_TO_FORMAT.get(ext, ext.lstrip(".")),
        file_size=meta.get("file_size"),
        width=meta.get("width"), height=meta.get("height"),
        exif_orientation=meta.get("exif_orientation"),
        # Preferisce l'EXIF: e' l'ora locale della fotocamera, come per le foto NAS.
        exif_date=meta.get("exif_date") or voce.scattata_il,
        camera_make=meta.get("camera_make"), camera_model=meta.get("camera_model"),
        lens_model=meta.get("lens_model"), focal_length=meta.get("focal_length"),
        aperture=meta.get("aperture"), shutter_speed=meta.get("shutter_speed"),
        iso=meta.get("iso"),
        latitude=voce.latitudine if ha_coordinate else None,
        longitude=voce.longitudine if ha_coordinate else None,
        location_source="takeout" if ha_coordinate else None,
    )
    try:
        derivati.scrivi(photo_id, "thumb", thumb)
        derivati.scrivi(photo_id, "proxy", proxy)
        with get_db(db_path) as conn:
            conn.execute(
                "UPDATE photos SET origine = 'google', phash = ?, "
                "derivati_at = datetime('now') WHERE id = ?", (phash, photo_id))
    except BaseException:
        derivati.cancella(photo_id)
        delete_photo_by_path(db_path, file_path)
        raise
    return photo_id


def _registra_sospetto(db_path: str, google_id: int, esito) -> None:
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO doppioni_sospetti "
            "(photo_id_google, photo_id_nas, motivo, distanza, stato) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (google_id, esito.photo_id, esito.motivo, esito.distanza))


def importa_album(zip_paths: list, db_path: Optional[str] = None,
                  forza: bool = False) -> dict:
    """
    Importa gli ZIP di un album Takeout. Ritorna il riepilogo:
    nuove, arricchite, incerte, video_saltati, gemelli_scartati,
    json_illeggibili, errori, gia_presenti (con il dettaglio per motivo:
    gia_presenti_per_istante / gia_presenti_per_phash), senza_impronta e
    zip_da_rimuovere.

    Solleva HTTPException(507) se lo spazio per i derivati non basta e
    HTTPException(409) se la passata delle impronte non e' finita, a meno che
    `forza` non sia True.
    Gli ZIP non vengono toccati; la directory di lavoro si': contiene gli
    originali estratti.
    """
    db_path = db_path or config.LOCAL_DB

    # Una riga di catalogo senza impronta disarma la salvaguardia di decidi():
    # l'abbinamento per solo istante fonde senza poter verificare che le due
    # immagini si somiglino, e la copia dell'archivio sparisce. E' l'unica
    # configurazione che perde una foto, quindi si controlla PRIMA di toccare
    # qualunque cosa.
    senza_impronta = conta_foto_senza_impronta(db_path)
    if senza_impronta and not forza:
        raise HTTPException(
            status_code=409,
            detail=f"{senza_impronta} foto del catalogo non hanno ancora "
                   f"l'impronta: un abbinamento per istante le fonderebbe "
                   f"senza poterle confrontare, e la foto dell'archivio "
                   f"andrebbe persa. Esegui POST /api/photos/impronte finche' "
                   f"`elaborate` non torna 0, poi riprova; se restano file "
                   f"illeggibili, forza=true importa lo stesso.")

    r = {"nuove": 0, "arricchite": 0, "incerte": 0, "video_saltati": 0,
         "gemelli_scartati": 0, "json_illeggibili": 0, "errori": 0,
         "gia_presenti": 0, "gia_presenti_per_istante": 0,
         "gia_presenti_per_phash": 0, "senza_impronta": senza_impronta,
         "zip_da_rimuovere": list(zip_paths)}

    # Gli originali estratti sono grandi: meglio sulla NAS che sul disco della VM.
    base = config.APP_DATA_PATH if os.path.isdir(config.APP_DATA_PATH) else None
    lavoro = tempfile.mkdtemp(prefix="takeout_", dir=base)
    try:
        radice = takeout_archivio.scompatta(zip_paths, lavoro)
        contenuto = takeout_archivio.leggi(radice)
        r["video_saltati"] = contenuto.video_saltati
        r["gemelli_scartati"] = contenuto.gemelli_scartati
        r["json_illeggibili"] = contenuto.json_illeggibili

        _controlla_spazio(len(contenuto.voci))
        indice = costruisci_indice(db_path)

        album_con_foto = set()
        for voce in contenuto.voci:
            try:
                _elabora(db_path, voce, indice, r, album_con_foto)
            except Exception as exc:
                logger.warning("Import di %s/%s fallito: %s", voce.album, voce.nome, exc)
                r["errori"] += 1

        # Solo gli album che hanno almeno una riga Google: se erano tutte gia'
        # nel catalogo non c'e' nessuna foto "google:/<album>" da mostrare, e
        # la cartella sarebbe vuota.
        for album in sorted(album_con_foto):
            try:
                _assicura_cartella(db_path, album)
            except Exception as exc:
                # Le foto sono dentro: una barra laterale incompleta non vale
                # un import fallito. Resta nel log.
                logger.warning("Cartella dell'album %s non creata: %s", album, exc)
    finally:
        shutil.rmtree(lavoro, ignore_errors=True)
    return r


def _elabora(db_path: str, voce, indice, r: dict, album_con_foto: set) -> None:
    meta = read_exif(voce.percorso_file)
    img = image_processor.open_any_format(voce.percorso_file)
    try:
        phash = impronta.calcola(img)
    finally:
        img.close()
    # Lo stesso istante che `_inserisci_google` scrive e che
    # `_aggiungi_all_indice` indicizza: l'EXIF del file dell'archivio (ora
    # locale della fotocamera), con l'UTC di Google solo come ripiego.
    esito = decidi(voce, phash, indice,
                   camera_make=meta.get("camera_make"),
                   camera_model=meta.get("camera_model"),
                   istante=meta.get("exif_date") or voce.scattata_il)

    if esito.decisione == "gia_presente":
        r["gia_presenti"] += 1
        if esito.motivo == "istante":
            r["gia_presenti_per_istante"] += 1
        elif esito.motivo == "phash":
            r["gia_presenti_per_phash"] += 1
        if _arricchisci(db_path, esito.photo_id, voce):
            r["arricchite"] += 1
        return

    # Prima i derivati, in memoria: se non si generano non si inserisce nulla.
    # L'originale sta per essere cancellato, una riga senza proxy resterebbe
    # per sempre un riquadro vuoto nel catalogo.
    thumb = image_processor.generate_thumbnail(voce.percorso_file)
    proxy = image_processor.generate_proxy(voce.percorso_file)
    photo_id = _inserisci_google(db_path, voce, meta, phash, thumb, proxy)

    # Coda e doppioni_sospetti stanno nello stesso rollback dell'insert: una
    # riga Google senza coda verrebbe poi giudicata gia_presente e non sarebbe
    # mai analizzata; un'incerta senza voce non arriverebbe alla revisione.
    try:
        if esito.decisione == "incerta":
            _registra_sospetto(db_path, photo_id, esito)
        else:
            add_to_queue(db_path, photo_id=photo_id)
    except BaseException:
        # Il guasto che porta qui (un DB bloccato) e' proprio quello che puo'
        # far fallire anche la pulizia. Se la sua eccezione sostituisse
        # l'originale, il log direbbe il sintomo sbagliato e il conteggio
        # degli errori resterebbe lo stesso: meglio registrarla a parte.
        try:
            _annulla(db_path, photo_id)
        except Exception as pulizia:
            logger.error(
                "Pulizia della foto %s fallita: puo' restare una riga Google "
                "con i derivati ma senza coda ne' sospetto, da togliere a "
                "mano: %s", photo_id, pulizia)
        raise

    # Le copie della stessa foto in altri album dello stesso archivio devono
    # vedere le righe nuove: l'indice e' costruito una volta sola, prima del ciclo.
    # Le incerte NON si indicizzano: una loro copia si fonderebbe con loro, e se
    # la revisione le risolvesse come doppioni della foto NAS e le cancellasse,
    # la copia sparirebbe senza essere mai stata confrontata con la NAS. Cosi'
    # la copia torna incerta e ha la sua riga di revisione.
    if esito.decisione == "incerta":
        r["incerte"] += 1
    else:
        _aggiungi_all_indice(indice, photo_id, phash, meta, voce)
        r["nuove"] += 1

    # Solo ora: se il passo precedente fosse fallito, `_annulla` avrebbe tolto
    # la riga e l'album potrebbe restare senza nemmeno una foto.
    album_con_foto.add(_nome_album(voce))


def _annulla(db_path: str, photo_id: int) -> None:
    """Toglie del tutto una riga Google appena inserita, con derivati e code."""
    derivati.cancella(photo_id)
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM doppioni_sospetti WHERE photo_id_google = ?", (photo_id,))
        conn.execute("DELETE FROM analysis_queue WHERE photo_id = ?", (photo_id,))
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))


def _aggiungi_all_indice(indice, photo_id: int, phash: str, meta: dict, voce) -> None:
    """Rende visibile a decidi() la foto appena inserita (stessi criteri di
    costruisci_indice: impronta e istante di scatto)."""
    indice.impronte.append((photo_id, phash))
    indice.phash_di[photo_id] = phash
    istante = meta.get("exif_date") or voce.scattata_il
    if istante:
        indice.per_chiave.setdefault(
            (istante, meta.get("camera_make"), meta.get("camera_model")), []).append(photo_id)
        indice.per_istante.setdefault(istante, []).append(photo_id)
