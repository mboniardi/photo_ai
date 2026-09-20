"""Route /api/geo-check — foto collocate in un posto incoerente con le vicine."""
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

import config
from database.photos import (
    clear_analysis, get_photo_by_id, get_photos_for_geo_check, update_photo,
    mark_location_confirmed,
)
from database.queue import add_to_queue
from services.geo_anomaly import prepara, rileva, raggruppa

router = APIRouter(prefix="/api/geo-check", tags=["geo-check"])


def _posizione(f: dict) -> dict:
    return {
        "latitude": f["latitude"],
        "longitude": f["longitude"],
        "location_name": f.get("location_name"),
        "location_source": f.get("location_source"),
    }


@router.get("")
def elenca_casi():
    """
    I casi da rivedere, i più clamorosi per primi.

    Si calcola su richiesta: è una revisione manuale, non un cruscotto.
    """
    foto = prepara(get_photos_for_geo_check(config.LOCAL_DB))
    anomalie = rileva(
        foto,
        max_gap_ore=config.GEO_MAX_GAP_ORE,
        accordo_km=config.GEO_ACCORDO_KM,
        fuori_scala_km=config.GEO_FUORI_SCALA_KM,
    )
    gruppi = raggruppa(
        anomalie,
        raggio_km=config.GEO_RAGGIO_GRUPPO_KM,
        finestra_ore=config.GEO_FINESTRA_GRUPPO_ORE,
    )

    casi = []
    for g in gruppi:
        ids = [f["id"] for f in g.foto]
        casi.append({
            "id": f"{ids[0]}-{ids[-1]}",
            "photo_ids": ids,
            "n_foto": len(ids),
            "quando": g.foto[0]["t"].isoformat(),
            "distanza_km": round(g.distanza_km, 1),
            "attuale": _posizione(g.foto[0]),
            "proposta": _posizione(g.proposta),
        })
    casi.sort(key=lambda c: -c["distanza_km"])

    return {"esaminate": len(foto), "segnalate": len(anomalie), "casi": casi}


class AcceptRequest(BaseModel):
    photo_ids: list[int] = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: Optional[str] = None


@router.post("/accept")
def accetta_proposta(req: AcceptRequest):
    """
    Applica la posizione proposta e rimanda le foto in analisi.

    La descrizione se ne va con l'analisi: era scritta a partire dal posto
    sbagliato. La nuova analisi riceve la posizione corretta come contesto,
    perché il worker costruisce il proprio suggerimento dai campi che qui
    vengono scritti.

    Un id che non esiste più non è un errore: tra il caricamento dell'elenco
    e l'accettazione la foto può essere stata cestinata. Non blocchiamo la
    correzione delle altre foto del gruppo per questo: la saltiamo e la
    segnaliamo nella risposta invece di far fallire l'intera richiesta (le
    foreign key sono attive, quindi un id inesistente farebbe esplodere
    `add_to_queue`, e ogni scrittura precedente nel ciclo sarebbe comunque
    già stata committata in modo permanente).
    """
    mancanti = [pid for pid in req.photo_ids if get_photo_by_id(config.LOCAL_DB, pid) is None]
    validi = [pid for pid in req.photo_ids if pid not in mancanti]

    aggiornate = in_coda = 0
    for pid in validi:
        clear_analysis(config.LOCAL_DB, pid)
        update_photo(
            config.LOCAL_DB, pid,
            latitude=req.latitude,
            longitude=req.longitude,
            location_name=req.location_name,
            location_source="corrected",
        )
        aggiornate += 1
        # priorità alta: è una correzione chiesta a mano, non un arretrato
        add_to_queue(config.LOCAL_DB, photo_id=pid, priority=1)
        in_coda += 1

    return {"ok": True, "aggiornate": aggiornate, "in_coda": in_coda, "mancanti": mancanti}


class ConfirmRequest(BaseModel):
    photo_ids: list[int] = Field(min_length=1)


@router.post("/confirm")
def conferma_posizione(req: ConfirmRequest):
    """
    La posizione attuale e' gia' giusta: e' la proposta a sbagliare.

    Si limita a marcarla 'manual'. Niente azzeramento della descrizione,
    niente rianalisi: non c'e' nulla da rifare e non si spende nulla. Il caso
    sparisce dall'elenco perche' 'manual' e' fra le origini affidabili, che il
    rilevatore non discute.
    """
    return {"ok": True,
            "confermate": mark_location_confirmed(config.LOCAL_DB,
                                                  photo_ids=req.photo_ids)}
