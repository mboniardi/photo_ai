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

    # I motori che sanno analizzare piu' immagini in una sola chiamata
    # dichiarano True. Gli altri restano com'erano: il worker li usa una foto
    # per volta.
    supporta_gruppi: bool = False

    async def identify_location(self, immagini: list) -> dict:
        """
        Identifica il luogo comune a piu' fotografie, in una sola chiamata.
        Ritorna {'luogo_riconosciuto', 'luogo_lat', 'luogo_lon'}.
        """
        raise NotImplementedError(
            f"{type(self).__name__} non sa identificare il luogo da un gruppo")

    async def analyze_group(self, immagini: list, luogo: str,
                            latitudine=None, longitudine=None) -> list:
        """
        Descrive un blocco di fotografie di cui il luogo e' gia' noto.
        Ritorna una lista di PhotoAnalysis lunga quanto `immagini`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} non sa analizzare un gruppo")

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
