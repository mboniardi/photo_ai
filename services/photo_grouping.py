"""
Raggruppamento delle foto per vicinanza temporale.

Le fotografie non arrivano isolate: arrivano in raffiche. Un gruppo e' una
catena di scatti consecutivi ravvicinati, e corrisponde a un luogo.

Modulo puro: riceve dizionari, ritorna dizionari. Nessun database, nessuna
rete. L'unico I/O ammesso e' leggere la data di modifica di un file, per le
foto che non hanno EXIF.
"""
import os
from datetime import datetime
from typing import Iterable, Optional, Sequence

# Posizioni di cui ci si puo' fidare: vengono da un GPS o da una scelta
# esplicita dell'utente, non da un'ipotesi del modello.
ORIGINI_AFFIDABILI = ("exif", "takeout", "manual", "corrected")


def istante_scatto(riga: dict) -> Optional[datetime]:
    """
    Quando e' stata scattata. Prima l'EXIF; se manca, la data di modifica del
    file.

    La data del file non e' l'ora dello scatto — misurata, se ne discosta di
    sei ore in mediana — ma la DISTANZA fra scatti consecutivi si conserva, ed
    e' quella che serve alla catena. L'alternativa sarebbe lasciare fuori dai
    gruppi le foto senza EXIF, che e' misurato essere peggio.
    """
    data = riga.get("exif_date")
    if data:
        try:
            return datetime.fromisoformat(data)
        except (TypeError, ValueError):
            pass
    percorso = riga.get("file_path")
    if percorso:
        try:
            return datetime.fromtimestamp(os.path.getmtime(percorso))
        except OSError:
            pass
    return None


def prepara(righe: Iterable[dict]) -> list[dict]:
    """Normalizza le righe in foto ordinate cronologicamente, con la chiave `t`."""
    foto = []
    for r in righe:
        t = istante_scatto(r)
        if t is None:
            continue
        foto.append(dict(r, t=t))
    foto.sort(key=lambda f: (f["t"], f["photo_id"]))
    return foto


def incatena(foto: Sequence[dict], gap_minuti: float = 15.0) -> list[list[dict]]:
    """
    Incatena le foto consecutive: se la successiva dista dalla precedente non
    piu' di `gap_minuti`, entra nel gruppo; altrimenti il gruppo si chiude.

    Nessun tetto alla dimensione ne' alla durata. Cento foto scattate ogni
    cinque minuti sono un gruppo solo anche se durano ore: e' lo stesso posto.
    Un tetto sulla durata e' stato misurato e scartato perche' non scatta mai.
    """
    if not foto:
        return []
    gruppi: list[list[dict]] = []
    corrente = [foto[0]]
    for precedente, f in zip(foto, foto[1:]):
        minuti = (f["t"] - precedente["t"]).total_seconds() / 60.0
        if minuti > gap_minuti or f["folder_path"] != precedente["folder_path"]:
            gruppi.append(corrente)
            corrente = [f]
        else:
            corrente.append(f)
    gruppi.append(corrente)
    return gruppi


def gruppo_di(foto: Sequence[dict], photo_id: int,
              gap_minuti: float = 15.0) -> list[dict]:
    """La catena che contiene quella foto, vuota se la foto non c'e'."""
    for g in incatena(foto, gap_minuti):
        if any(f["photo_id"] == photo_id for f in g):
            return g
    return []
