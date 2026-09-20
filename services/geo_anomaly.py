"""
Rilevamento di foto collocate in un posto geograficamente incoerente con
quelle scattate immediatamente prima e immediatamente dopo.

Modulo puro: riceve dizionari, ritorna dizionari. Non conosce il database,
la configurazione né la rete, così si può provare senza infrastruttura.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional, Sequence

# Posizioni di cui ci si può fidare: vengono da un GPS o da una scelta
# esplicita dell'utente, non da un'ipotesi del modello.
ORIGINI_AFFIDABILI = ("exif", "takeout", "manual", "corrected")

_RAGGIO_TERRA_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in chilometri fra due punti sulla superficie terrestre."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _RAGGIO_TERRA_KM * math.asin(math.sqrt(h))


def prepara(righe: Iterable[dict]) -> list[dict]:
    """
    Normalizza le righe del database in foto ordinate cronologicamente.

    Scarta chi non ha una data leggibile o non ha coordinate: senza uno dei
    due non c'è nulla da confrontare.
    """
    foto = []
    for r in righe:
        d = dict(r)
        if d.get("latitude") is None or d.get("longitude") is None:
            continue
        try:
            d["t"] = datetime.fromisoformat(d["exif_date"])
        except (TypeError, ValueError):
            continue
        foto.append(d)
    foto.sort(key=lambda f: (f["t"], f["id"]))
    return foto
