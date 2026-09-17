"""
Implementazione AIEngine per Google Gemini.
SDK: google-genai (API v1 stabile).
Modelli: GEMINI_MODEL (visione), GEMINI_EMBED_MODEL (embedding).
"""
import asyncio
import logging

import httpx
from google import genai
from google.genai import types

import config
from services.ai.base import AIEngine, PhotoAnalysis
from services.ai.prompt import build_prompt, parse_response

logger = logging.getLogger(__name__)


class GeminiEngine(AIEngine):
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key Gemini obbligatoria")
        self._api_key = api_key
        self._client = genai.Client(api_key=api_key)

    async def analyze(
        self,
        image_bytes: bytes,
        location_hint: str = "",
    ) -> PhotoAnalysis:
        prompt = build_prompt(location_hint)
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[prompt, image_part],
            )
        )
        data = parse_response(response.text)
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

    async def embed(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list:
        if not config.GEMINI_EMBED_MODEL:
            return []
        model = config.GEMINI_EMBED_MODEL.removeprefix("models/")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
        payload = {
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, params={"key": self._api_key})
            resp.raise_for_status()
            return resp.json()["embedding"]["values"]
