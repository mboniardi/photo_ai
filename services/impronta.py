"""Impronta percettiva (pHash a 64 bit) e confronto per distanza di Hamming.

Serve a riconoscere la stessa foto anche quando il file non e' identico
byte per byte (ricompressione, ridimensionamento): l'impronta dipende dalla
struttura a basse frequenze dell'immagine, non dai suoi byte.
"""
import re

import numpy as np
from PIL import Image

_LATO = 32      # lato dell'immagine ridotta su cui si calcola la DCT
_BLOCCO = 8     # lato del blocco di basse frequenze usato per l'impronta
_FORMATO = re.compile(r"[0-9a-fA-F]{16}")


def _matrice_dct(n: int) -> np.ndarray:
    """Matrice ortonormale della DCT-II di lunghezza n (niente scipy)."""
    k = np.arange(n).reshape(-1, 1)
    i = np.arange(n).reshape(1, -1)
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    m[0, :] = np.sqrt(1.0 / n)
    return m


_DCT = _matrice_dct(_LATO)


def calcola(img: Image.Image) -> str:
    """pHash a 64 bit come 16 caratteri esadecimali minuscoli."""
    grigio = img.convert("L").resize((_LATO, _LATO), Image.LANCZOS)
    pixel = np.asarray(grigio, dtype=np.float64)
    dct = _DCT @ pixel @ _DCT.T
    # Basse frequenze 8x8 senza il termine costante (0,0): porta la luminosita'
    # complessiva, che e' proprio cio' che cambia fra una copia ricompressa
    # e l'originale.
    blocco = dct[:_BLOCCO, :_BLOCCO].flatten()[1:]
    # I coefficienti sono 63: il 64esimo bit e' fissato a 0 per avere 64 bit.
    bit = np.zeros(64, dtype=bool)
    bit[:63] = blocco > np.median(blocco)
    valore = int(np.packbits(bit).view(">u8")[0])
    return f"{valore:016x}"


def _a_intero(impronta: str) -> int:
    if not isinstance(impronta, str) or not _FORMATO.fullmatch(impronta):
        raise ValueError(f"impronta non valida (attesi 16 caratteri esadecimali): {impronta!r}")
    return int(impronta, 16)


def _bit_accesi(valori: np.ndarray) -> np.ndarray:
    """Numero di bit a 1 per ogni elemento di un array uint64."""
    return np.unpackbits(valori.view(np.uint8).reshape(-1, 8), axis=1).sum(axis=1)


def distanza(a: str, b: str) -> int:
    """Distanza di Hamming fra due impronte, 0..64."""
    return (_a_intero(a) ^ _a_intero(b)).bit_count()


def simili(impronta: str, candidate: list[tuple[int, str]],
           soglia: int) -> list[tuple[int, int]]:
    """Le candidate `(photo_id, impronta)` entro `soglia` dall'impronta data,
    come `(photo_id, distanza)` ordinate per distanza crescente."""
    riferimento = np.uint64(_a_intero(impronta))
    if not candidate:
        return []
    ids = [pid for pid, _ in candidate]
    valori = np.array([_a_intero(h) for _, h in candidate], dtype=np.uint64)
    dist = _bit_accesi(valori ^ riferimento)
    # Ordinamento stabile: a parita' di distanza resta l'ordine di ingresso.
    ordine = np.argsort(dist, kind="stable")
    return [(int(ids[i]), int(dist[i])) for i in ordine if dist[i] <= soglia]
