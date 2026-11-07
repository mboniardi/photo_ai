"""Passata di impronte sulla libreria esistente.

Calcola l'impronta percettiva delle foto che ne sono prive decodificandole a
bassa risoluzione. Non genera proxy e non scrive nello store dei derivati:
costa minuti, non ore, e nessuno spazio su disco.
"""
import logging
from typing import Optional

from database.photos import (
    conta_foto_senza_impronta, foto_senza_impronta, update_photo,
)
from services import impronta
from services.image_processor import open_any_format

logger = logging.getLogger(__name__)

# Lato massimo richiesto al decoder JPEG: basta e avanza per un hash a 32x32.
_LATO_DRAFT = 256


def _impronta_del_file(percorso: str) -> str:
    img = open_any_format(percorso)
    try:
        # draft() va chiamato PRIMA che l'immagine sia caricata: cosi' il
        # decoder JPEG scala mentre decodifica (stesso ordine che in
        # image_processor evita il picco di memoria). Su HEIC, RAW e PNG non
        # ha effetto e si decodifica normalmente.
        img.draft("L", (_LATO_DRAFT, _LATO_DRAFT))
        return impronta.calcola(img)
    finally:
        img.close()


def calcola_mancanti(db_path: Optional[str] = None, limite: int = 500) -> dict:
    """Calcola l'impronta di al massimo `limite` foto che non ce l'hanno.

    Un file illeggibile (vuoto, troncato, sparito) non ferma la passata: viene
    contato in `errori`, registrato nel log, e si prosegue. `rimaste` conta le
    foto ancora senza impronta, compresi i file illeggibili.
    """
    elaborate = 0
    errori = 0
    for riga in foto_senza_impronta(db_path, limite):
        try:
            valore = _impronta_del_file(riga["file_path"])
        except Exception:
            logger.warning("Impronta non calcolabile per %s", riga["file_path"],
                           exc_info=True)
            errori += 1
            continue
        update_photo(db_path, riga["id"], phash=valore)
        elaborate += 1
    return {"elaborate": elaborate, "errori": errori,
            "rimaste": conta_foto_senza_impronta(db_path)}
