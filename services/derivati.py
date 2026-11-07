"""
Store dei derivati su disco: due JPEG per foto (thumb per la griglia,
proxy per lightbox e AI).

Cache rigenerabile, NON nel backup: ogni foto ha un padrone altrove
(NAS o Google). La radice e' config.DERIVATI_PATH, letta a ogni chiamata
(non copiata in una costante di modulo) cosi' i test possono sostituirla.

Funzioni:
  percorso(photo_id, tipo)        → str
  scrivi(photo_id, tipo, dati)    → str  (scrittura atomica)
  leggi(photo_id, tipo)           → Optional[bytes]
  cancella(photo_id)              → int  (file rimossi)
"""
import os
import tempfile
from typing import Optional

import config

TIPI = ("thumb", "proxy")


def percorso(photo_id: int, tipo: str) -> str:
    """
    Percorso del derivato. Due livelli di sottocartelle dalle cifre MENO
    significative dell'id (ultime due, poi le due precedenti): evita
    directory enormi e distribuisce uniformemente gli id sequenziali.
    Solleva ValueError se tipo non e' "thumb" o "proxy".
    """
    if tipo not in TIPI:
        raise ValueError(f"Tipo di derivato sconosciuto: '{tipo}' (attesi: {', '.join(TIPI)})")
    livello1 = f"{photo_id % 100:02d}"
    livello2 = f"{(photo_id // 100) % 100:02d}"
    return os.path.join(config.DERIVATI_PATH, livello1, livello2, f"{photo_id}_{tipo}.jpg")


def scrivi(photo_id: int, tipo: str, dati: bytes) -> str:
    """
    Scrive il derivato in modo atomico: file temporaneo nella stessa
    directory, poi os.replace. Ritorna il percorso.
    """
    dest = percorso(photo_id, tipo)
    cartella = os.path.dirname(dest)
    os.makedirs(cartella, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=cartella, prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dati)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dest


def leggi(photo_id: int, tipo: str) -> Optional[bytes]:
    """Contenuto del derivato, None se assente."""
    try:
        with open(percorso(photo_id, tipo), "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def cancella(photo_id: int) -> int:
    """Rimuove thumb e proxy. Ritorna quanti file ha tolto."""
    rimossi = 0
    for tipo in TIPI:
        try:
            os.unlink(percorso(photo_id, tipo))
            rimossi += 1
        except FileNotFoundError:
            pass
    return rimossi
