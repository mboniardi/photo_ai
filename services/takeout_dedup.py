"""
Riconoscimento dei doppioni fra un archivio Takeout e il catalogo.

Per ogni foto dell'archivio decide se il catalogo la ha gia'. I due errori non
pesano uguale: fondere due foto diverse ne fa perdere una (la copia
dell'archivio viene scartata in silenzio), mentre un doppione non riconosciuto
costa solo una voce in piu'. Quindi si fonde solo quando si e' sicuri; nel
dubbio la decisione e' "incerta" e la scelta resta a una persona.
"""
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

import config
from services import impronta
from services.takeout_archivio import Voce


@dataclass
class Esito:
    decisione: str                  # "gia_presente" | "nuova" | "incerta"
    photo_id: Optional[int] = None
    motivo: Optional[str] = None    # "istante" | "phash" (solo se gia_presente)
    distanza: Optional[int] = None  # distanza di Hamming, se decisa per impronta


@dataclass
class Indice:
    """Cio' che serve del catalogo, caricato una volta per import."""
    impronte: list = field(default_factory=list)    # [(photo_id, phash)]
    per_chiave: dict = field(default_factory=dict)  # (exif_date, make, model) -> [photo_id]
    per_istante: dict = field(default_factory=dict)  # exif_date -> [photo_id]
    phash_di: dict = field(default_factory=dict)    # photo_id -> phash


def costruisci_indice(db_path: str) -> Indice:
    """Carica impronte e istanti di scatto del catalogo. Da chiamare una sola
    volta per import, non per foto."""
    indice = Indice()
    conn = sqlite3.connect(db_path)
    try:
        # Le foto nel cestino non assorbono nulla: se poi il cestino venisse
        # svuotato, la copia dell'archivio andrebbe persa.
        righe = conn.execute(
            "SELECT id, phash, exif_date, camera_make, camera_model "
            "FROM photos WHERE COALESCE(is_trash, 0) = 0 ORDER BY id").fetchall()
    finally:
        conn.close()
    for pid, phash, exif_date, make, model in righe:
        if phash:
            indice.impronte.append((pid, phash))
            indice.phash_di[pid] = phash
        # Le righe senza istante restano fuori: le scansioni di diapositive
        # hanno exif_date NULL e, abbinate su NULL = NULL, si fonderebbero
        # tutte in una sola foto.
        if exif_date:
            indice.per_chiave.setdefault((exif_date, make, model), []).append(pid)
            indice.per_istante.setdefault(exif_date, []).append(pid)
    return indice


def decidi(voce: Voce, impronta_voce: Optional[str], indice: Indice,
           camera_make: Optional[str] = None,
           camera_model: Optional[str] = None) -> Esito:
    """Decide se `voce` e' gia' nel catalogo, e' nuova o e' incerta.

    `camera_make`/`camera_model` vengono dall'EXIF del file dell'archivio. Se
    ci sono entrambi, l'istante si confronta sulla terna completa; se manca
    uno dei due si ripiega sul solo istante.
    """
    # 1. Stesso istante di scatto. Piu' corrispondenze sono una raffica (stesso
    # istante, stesso posto): restano certe, e l'unica azione e' riempire le
    # coordinate. Si prende la prima. Con la fotocamera nota si usa la terna
    # (istante, marca, modello): due corpi macchina nello stesso secondo non
    # sono la stessa foto, e una fusione sbagliata perde la foto dell'archivio
    # e mette le sue coordinate sulla riga di un'altra. Senza fotocamera si
    # ripiega sul solo istante.
    if voce.scattata_il:
        if camera_make is not None and camera_model is not None:
            ids = indice.per_chiave.get((voce.scattata_il, camera_make, camera_model))
        else:
            ids = indice.per_istante.get(voce.scattata_il)
        if ids:
            pid = ids[0]
            # Salvaguardia: lo stesso istante non basta se le due immagini non
            # si somigliano affatto (es. la foto di un altro contributore
            # dell'album, scattata nello stesso secondo). Qui si fonderebbe e
            # la foto andrebbe persa: meglio "incerta". Le raffiche stanno ben
            # dentro la fascia. Se manca un'impronta non si puo' dire nulla e
            # vale l'istante.
            h_catalogo = indice.phash_di.get(pid)
            if impronta_voce and h_catalogo:
                dist = impronta.distanza(impronta_voce, h_catalogo)
                if dist > config.TAKEOUT_PHASH_INCERTO:
                    return Esito("incerta", pid, "istante_ma_impronta_lontana", dist)
            return Esito("gia_presente", pid, "istante")

    # 2-3. Impronta percettiva. Una foto solo simile NON e' la stessa foto:
    # entro la soglia stretta si fonde, nella fascia intermedia si lascia
    # decidere a una persona.
    if impronta_voce:
        vicine = impronta.simili(impronta_voce, indice.impronte,
                                 config.TAKEOUT_PHASH_INCERTO)
        if vicine:
            pid, dist = vicine[0]
            if dist <= config.TAKEOUT_PHASH_CERTO:
                return Esito("gia_presente", pid, "phash", dist)
            return Esito("incerta", pid, None, dist)

    return Esito("nuova")
