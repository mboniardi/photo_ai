"""
Interfaccia astratta per i motori AI (§6.5, §6.6).
GeminiEngine e GroqEngine implementano AIEngine.
PhotoAnalysis è il dataclass di ritorno da analyze().
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PhotoAnalysis:
    """Risultato strutturato dell'analisi visiva AI di una foto."""
    description: str
    technical_score: float          # 1-10
    aesthetic_score: float          # 1-10
    subject: str                    # soggetto principale (3-5 parole)
    atmosphere: str                 # una parola (romantica, serena, …)
    colors: list                    # colori dominanti
    strengths: str
    weaknesses: Optional[str]
    ai_engine: str                  # 'gemini' | 'gemini_paid' | 'groq'

    # Campi facoltativi (riconoscimento luogo)
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Calcolato automaticamente alla creazione
    overall_score: float = field(init=False)

    def __post_init__(self):
        # Formula §6.6: overall = round(0.35*T + 0.65*E, 1)
        self.overall_score = round(
            0.35 * self.technical_score + 0.65 * self.aesthetic_score, 1
        )


class AIEngine(ABC):
    """
    Interfaccia astratta per motori AI di analisi fotografica.
    Implementata da GeminiEngine (services/ai/gemini.py)
    e GroqEngine (services/ai/groq_engine.py).
    """

    @property
    def max_side_px(self) -> Optional[int]:
        """Risoluzione massima (lato lungo) da usare per prepare_for_ai. None = default di config."""
        return None

    @abstractmethod
    async def analyze(
        self,
        image_bytes: bytes,
        location_hint: str = "",
    ) -> PhotoAnalysis:
        """
        Analizza un'immagine JPEG (bytes) e ritorna un PhotoAnalysis.
        location_hint: stringa opzionale con il nome del luogo noto
                       (usata nel prompt se la foto ha location_source='exif').
        """

    @abstractmethod
    async def embed(self, text: str) -> list:
        """
        Genera l'embedding vettoriale di un testo.
        Ritorna una lista di float (768 dimensioni per text-embedding-004).
        """
