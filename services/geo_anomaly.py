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


@dataclass
class Anomalia:
    """Una foto sospetta, e la foto vicina da cui viene la posizione proposta."""
    foto: dict
    proposta: dict
    distanza_km: float


def _ore(a: dict, b: dict) -> float:
    return abs((b["t"] - a["t"]).total_seconds()) / 3600.0


def _distanza(a: dict, b: dict) -> float:
    return haversine_km(a["latitude"], a["longitude"],
                        b["latitude"], b["longitude"])


def rileva(
    foto: Sequence[dict],
    *,
    max_gap_ore: float = 2.0,
    accordo_km: float = 50.0,
    fuori_scala_km: float = 150.0,
) -> list[Anomalia]:
    """
    Guarda la foto precedente e la successiva. Se sono vicine nel tempo, se
    concordano fra loro sulla posizione, e quella in mezzo è fuori scala
    rispetto a entrambe, la segnala.

    Confrontare a coppie non basta: le coordinate scritte dall'AI sono
    ipotesi, e un'ipotesi contro un'altra ipotesi non dimostra nulla. Serve
    che prima e dopo siano d'accordo fra loro.
    """
    anomalie: list[Anomalia] = []
    for i in range(1, len(foto) - 1):
        p, prima, dopo = foto[i], foto[i - 1], foto[i + 1]

        if (p.get("location_source") or "") in ORIGINI_AFFIDABILI:
            continue                                  # ha un GPS vero
        if _ore(prima, p) > max_gap_ore or _ore(p, dopo) > max_gap_ore:
            continue                                  # troppo isolata nel tempo
        if _distanza(prima, dopo) > accordo_km:
            continue                                  # i vicini non concordano

        d = min(_distanza(p, prima), _distanza(p, dopo))
        if d <= fuori_scala_km:
            continue

        # Fra le due vicine, una posizione da GPS vale più di un'ipotesi.
        affidabili = [v for v in (prima, dopo)
                      if (v.get("location_source") or "") in ORIGINI_AFFIDABILI]
        proposta = affidabili[0] if affidabili else prima
        anomalie.append(Anomalia(foto=p, proposta=proposta, distanza_km=d))
    return anomalie
