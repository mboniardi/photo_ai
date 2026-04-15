"""
Implementazione AIEngine per Google Gemini.
SDK: google-genai (API v1 stabile).
Modelli: GEMINI_MODEL (visione), GEMINI_EMBED_MODEL (embedding).
"""
import asyncio
import json
import re

from google import genai
from google.genai import types

import config
from services.ai.base import AIEngine, PhotoAnalysis

_REQUIRED_FIELDS = {
    "descrizione", "punteggio_tecnico", "punteggio_estetico",
    "soggetto", "atmosfera", "colori_dominanti",
    "punti_di_forza", "punti_di_debolezza",
    "luogo_riconosciuto", "luogo_lat", "luogo_lon",
}


class GeminiEngine(AIEngine):
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key Gemini obbligatoria")
        self._client = genai.Client(api_key=api_key)

    async def analyze(
        self,
        image_bytes: bytes,
        location_hint: str = "",
    ) -> PhotoAnalysis:
        prompt = _build_prompt(location_hint)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt, image_part],
            )
        )
        data = _parse_response(response.text)
        return PhotoAnalysis(
            description=data["descrizione"],
            technical_score=float(data["punteggio_tecnico"]),
            aesthetic_score=float(data["punteggio_estetico"]),
            subject=data["soggetto"],
            atmosphere=data["atmosfera"],
            colors=data["colori_dominanti"] or [],
            strengths=data["punti_di_forza"] or "",
            weaknesses=data.get("punti_di_debolezza"),
            ai_engine="gemini",
            location_name=data.get("luogo_riconosciuto"),
            latitude=data.get("luogo_lat"),
            longitude=data.get("luogo_lon"),
        )

    async def embed(self, text: str) -> list:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._client.models.embed_content(
                model=config.GEMINI_EMBED_MODEL,
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
        )
        return result.embeddings[0].values


def _build_prompt(location_hint: str) -> str:
    location_section = ""
    if location_hint:
        location_section = f"\n[SE DISPONIBILE: La foto è stata scattata a: {location_hint}]"

    return f"""Sei un critico fotografico esperto. Analizza questa fotografia e rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo aggiuntivo, nessun markdown, nessun delimitatore).

{{
  "descrizione": "Descrizione dettagliata in italiano, 3-5 frasi. Descrivi soggetto, composizione, luce, colori, atmosfera. Sii specifico e evocativo.",
  "punteggio_tecnico": <intero 1-10: messa a fuoco, esposizione corretta, rumore, nitidezza, bilanciamento bianco>,
  "punteggio_estetico": <intero 1-10: composizione, uso della luce, impatto emotivo, creatività, equilibrio visivo>,
  "soggetto": "<soggetto principale in 3-5 parole>",
  "atmosfera": "<una parola: es. romantica, drammatica, serena, malinconica, vivace, misteriosa>",
  "colori_dominanti": ["<colore1>", "<colore2>", "<colore3>"],
  "punti_di_forza": "<cosa funziona bene, 1-2 frasi>",
  "punti_di_debolezza": "<cosa potrebbe migliorare, 1-2 frasi, oppure null se non ci sono problemi evidenti>",
  "luogo_riconosciuto": "<nome del luogo specifico se riconoscibile, altrimenti null>",
  "luogo_lat": <latitudine approssimativa se luogo riconosciuto, altrimenti null>,
  "luogo_lon": <longitudine approssimativa se luogo riconosciuto, altrimenti null>
}}{location_section}

Scala di valutazione:
1-3: Foto con problemi tecnici/estetici significativi
4-5: Foto nella media, accettabile
6-7: Foto buona, sopra la media
8-9: Foto eccellente, da conservare
10: Capolavoro fotografico (rarissimo)"""


def _parse_response(text: str) -> dict:
    """
    Estrae il JSON dalla risposta del modello.
    Rimuove eventuali code fence markdown.
    Lancia ValueError se il JSON non è valido o mancano campi obbligatori.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Risposta AI non è JSON valido: {e}\nTesto: {text[:200]}") from e

    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Campi mancanti nella risposta AI: {missing}")

    return data
