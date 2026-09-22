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
from services.ai.prompt import (
    build_prompt, parse_response,
    build_location_prompt, parse_location_response,
    build_group_prompt, parse_group_response,
)

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
            "max_tokens": config.DEEPSEEK_MAX_TOKENS,
            "temperature": 0.2,
            # Senza questo il modello consuma il budget ragionando e "content"
            # torna vuoto: parse_response fallirebbe su ogni foto.
            "thinking": {"type": config.DEEPSEEK_THINKING},
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

    supporta_gruppi: bool = True

    def _parti(self, testo: str, immagini: list) -> list:
        """Un messaggio con un testo e N immagini, nel formato OpenAI."""
        parti = [{"type": "text", "text": testo}]
        for b in immagini:
            parti.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64,"
                                     + base64.b64encode(b).decode()},
            })
        return parti

    async def _chiedi(self, parti: list, max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": parti}],
                    "max_tokens": max_tokens,
                    "thinking": {"type": config.DEEPSEEK_THINKING},
                },
            )
            resp.raise_for_status()
            body = resp.json()
        return body["choices"][0]["message"]["content"]

    async def identify_location(self, immagini: list) -> dict:
        """
        Il luogo comune a piu' fotografie, in una chiamata sola.

        Si usano immagini a bassa risoluzione: riconoscere un tempio richiede
        molto meno dettaglio che descriverlo. Misurato: a 320 px il modello ha
        identificato tutti i luoghi di prova, con 1700 token contro i 3750 a
        risoluzione piena e nessun miglioramento.
        """
        if not immagini:
            return {"luogo_riconosciuto": None, "luogo_lat": None, "luogo_lon": None}
        testo = await self._chiedi(
            self._parti(build_location_prompt(len(immagini)), immagini), 300)
        return parse_location_response(testo)

    async def analyze_group(self, immagini: list, luogo: str,
                            latitudine=None, longitudine=None) -> list:
        """
        Descrive un blocco di fotografie sapendo gia' dove sono state scattate.

        Il luogo non viene chiesto al modello ma imposto: e' stato determinato
        una volta per tutto il gruppo, e vale per ogni foto del blocco.
        """
        if not immagini:
            return []
        prompt = build_group_prompt(len(immagini), luogo,
                                    config.GROUP_DESCRIZIONE_MIN_CARATTERI)
        # Budget generoso: dodici descrizioni da 600 caratteri sono circa 4000
        # token, e una risposta troncata fa perdere l'intero blocco.
        testo = await self._chiedi(self._parti(prompt, immagini),
                                   1500 * len(immagini))
        voci = parse_group_response(testo, len(immagini))

        return [
            PhotoAnalysis(
                description=v["descrizione"],
                technical_score=float(v["punteggio_tecnico"]),
                aesthetic_score=float(v["punteggio_estetico"]),
                subject=v.get("soggetto", "") or "",
                atmosphere=v.get("atmosfera", "") or "",
                colors=v.get("colori_dominanti", []) or [],
                strengths=v.get("punti_di_forza", "") or "",
                weaknesses=v.get("punti_di_debolezza"),
                location_name=luogo,
                latitude=latitudine,
                longitude=longitudine,
                ai_engine=f"deepseek/{self._model}",
            )
            for v in voci
        ]
