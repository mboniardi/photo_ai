"""
Groq AI engine — usa Llama 4 Maverick via API Groq.
Modello configurabile via GROQ_MODEL (default: meta-llama/llama-4-maverick-17b-128e-instruct).
"""
import asyncio
import base64
import logging

from services.ai.base import AIEngine, PhotoAnalysis
from services.ai.gemini import _build_prompt, _parse_response
import config

logger = logging.getLogger(__name__)


class GroqEngine(AIEngine):

    def __init__(self, api_key: str):
        from groq import Groq
        self._client = Groq(api_key=api_key)

    async def analyze(self, image_bytes: bytes, location_hint: str = "") -> PhotoAnalysis:
        loop = asyncio.get_running_loop()
        b64 = base64.b64encode(image_bytes).decode()
        prompt = _build_prompt(location_hint)

        def _call():
            return self._client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
                max_tokens=1024,
                temperature=0.2,
            )

        response = await loop.run_in_executor(None, _call)
        text = response.choices[0].message.content
        data = _parse_response(text)

        return PhotoAnalysis(
            description=data["descrizione"],
            technical_score=float(data["punteggio_tecnico"]),
            aesthetic_score=float(data["punteggio_estetico"]),
            subject=data.get("soggetto", ""),
            atmosphere=data.get("atmosfera", ""),
            colors=data.get("colori_dominanti", []),
            strengths=data.get("punti_di_forza", ""),
            weaknesses=data.get("punti_di_debolezza"),
            location_name=data.get("luogo_riconosciuto"),
            latitude=data.get("luogo_lat"),
            longitude=data.get("luogo_lon"),
            ai_engine=f"groq/{config.GROQ_MODEL}",
        )

    async def embed(self, text: str) -> list:
        return []  # Groq non offre API di embedding
