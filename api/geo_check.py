"""Route /api/geo-check — foto collocate in un posto incoerente con le vicine."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from database.photos import get_photos_for_geo_check
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
