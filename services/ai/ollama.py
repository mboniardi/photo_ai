"""
Implementazione AIEngine per Ollama locale (§3).
Modelli default: llava (visione), nomic-embed-text (embedding).
Nessun rate limit: elaborazione continua.
"""
import base64

import ollama

from services.ai.base import AIEngine, PhotoAnalysis
from services.ai.gemini import _build_prompt, _parse_response

_DEFAULT_VISION_MODEL = "llava"
_DEFAULT_EMBED_MODEL  = "nomic-embed-text"
_DEFAULT_BASE_URL     = "http://localhost:11434"


class OllamaEngine(AIEngine):
    def __init__(
        self,
        vision_model: str = _DEFAULT_VISION_MODEL,
        embed_model: str = _DEFAULT_EMBED_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
    ):
        self._vision_model = vision_model
        self._embed_model  = embed_model
        self._client = ollama.AsyncClient(host=base_url)

    async def analyze(
        self,
        image_bytes: bytes,
        location_hint: str = "",
    ) -> PhotoAnalysis:
        prompt = _build_prompt(location_hint)
        img_b64 = base64.b64encode(image_bytes).decode()

        response = await self._client.chat(
            model=self._vision_model,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [img_b64],
            }],
        )
        text = response["message"]["content"]
        data = _parse_response(text)

        return PhotoAnalysis(
            description=data["descrizione"],
            technical_score=float(data["punteggio_tecnico"]),
            aesthetic_score=float(data["punteggio_estetico"]),
            subject=data["soggetto"],
            atmosphere=data["atmosfera"],
            colors=data["colori_dominanti"] or [],
            strengths=data["punti_di_forza"] or "",
            weaknesses=data.get("punti_di_debolezza"),
            ai_engine="ollama",
            location_name=data.get("luogo_riconosciuto"),
            latitude=data.get("luogo_lat"),
            longitude=data.get("luogo_lon"),
        )

    async def embed(self, text: str) -> list:
        response = await self._client.embeddings(
            model=self._embed_model,
            prompt=text,
        )
        return response["embedding"]
