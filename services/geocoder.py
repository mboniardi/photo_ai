"""
Reverse geocoding tramite Nominatim/OSM (gratuito, §6.4).
Ritorna una stringa "Città, Paese" o None.
User-Agent obbligatorio per Nominatim (policy OSM).
"""
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_HEADERS = {"User-Agent": "PhotoAIManager/1.0 (personal-use)"}
_TIMEOUT = 10.0


async def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """
    Chiama Nominatim per ottenere il nome del luogo da coordinate.
    Ritorna 'Città, Paese' o None in caso di errore o risposta vuota.
    Il risultato deve essere cachato dal chiamante (nel DB photos).
    """
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
        "accept-language": "it",
    }
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT) as client:
            resp = await client.get(_NOMINATIM_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("reverse_geocode(%s, %s) failed: %s", lat, lon, exc)
        return None

    address = data.get("address", {})
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
    )
    country = address.get("country")

    if not city and not country:
        return None
    if city and country:
        return f"{city}, {country}"
    return city or country
