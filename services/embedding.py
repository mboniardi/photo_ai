"""
Generazione di embedding vettoriali.

Deliberatamente separata da services/ai/: analizzare un'immagine e
vettorizzare un testo sono responsabilità distinte, e non tutti i motori
di analisi offrono un'API di embedding.
"""
from abc import ABC, abstractmethod
from typing import Optional

import httpx

import config


class Embedder(ABC):
    """Interfaccia di un generatore di embedding."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Numero di componenti dei vettori prodotti."""

    @abstractmethod
    async def embed(self, text: str) -> list:
        """Vettorizza un singolo testo."""

    @abstractmethod
    async def embed_batch(self, texts: list) -> list:
        """Vettorizza più testi in una sola chiamata HTTP."""


class OllamaEmbedder(Embedder):
    """
    bge-m3 servito da Ollama.

    Il modello è simmetrico: non richiede istruzioni diverse per query e
    documenti. I vettori arrivano già normalizzati (norma L2 = 1).
    """

    DIMENSION = 1024

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self._base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self._model = model or config.OLLAMA_EMBED_MODEL
        self._timeout = timeout

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    async def embed(self, text: str) -> list:
        vectors = await self.embed_batch([text])
        return vectors[0] if vectors else []

    async def embed_batch(self, texts: list) -> list:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": list(texts)},
            )
            resp.raise_for_status()
            return resp.json()["embeddings"]
