"""
Motore di analisi DeepSeek.
API compatibile OpenAI (chat completions) su https://api.deepseek.com.
Il modello con visione è `deepseek-flash`, configurabile via DEEPSEEK_MODEL.

DeepSeek non offre un'API di embedding: la vettorizzazione è compito
di services/embedding.py.
"""
import base64
import logging
from typing import Optional

import httpx

import config
from services.ai.base import AIEngine, PhotoAnalysis
from services.ai.prompt import build_prompt, parse_response

logger = logging.getLogger(__name__)


class DeepSeekEngine(AIEngine):

    def __init__(
        self,
        api_key: str,
        model: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        timeout: float = 120.0,
    ):
        if not api_key:
            raise ValueError("API key DeepSeek obbligatoria")
        self._api_key = api_key
        self._model = model or config.DEEPSEEK_MODEL
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def max_side_px(self) -> int:
        return config.DEEPSEEK_MAX_SIDE_PX

    async def analyze(self, image_bytes: bytes, location_hint: str = "") -> PhotoAnalysis:
        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self._model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": build_prompt(location_hint)},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            "max_tokens": 1024,
            "temperature": 0.2,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()

        data = parse_response(body["choices"][0]["message"]["content"])

        return PhotoAnalysis(
            description=data["descrizione"],
            technical_score=float(data["punteggio_tecnico"]),
            aesthetic_score=float(data["punteggio_estetico"]),
            subject=data.get("soggetto", ""),
            atmosphere=data.get("atmosfera", ""),
            colors=data.get("colori_dominanti", []) or [],
            strengths=data.get("punti_di_forza", "") or "",
            weaknesses=data.get("punti_di_debolezza"),
            location_name=data.get("luogo_riconosciuto"),
            latitude=data.get("luogo_lat"),
            longitude=data.get("luogo_lon"),
            ai_engine=f"deepseek/{self._model}",
        )
