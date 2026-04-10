"""
Elaborazione immagini per analisi AI e generazione thumbnail.

Funzioni principali:
  open_any_format(path)         → PIL.Image  (JPG, PNG, HEIC, RAW)
  prepare_for_ai(path)          → bytes JPEG ottimizzati per LLM
  generate_thumbnail(path, size) → bytes JPEG thumbnail UI

Nessun file mai scritto su disco (§10 "Thumbnail generate in memoria").
"""
import io
import os
from typing import Optional

from PIL import Image

import config

# Estensioni supportate per formato (lowercase)
_JPEG_EXTS = {".jpg", ".jpeg"}
_PNG_EXTS = {".png"}
_HEIC_EXTS = {".heic", ".heif"}
_RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2"}


def open_any_format(path: str) -> Image.Image:
    """
    Apre un file immagine in qualsiasi formato supportato.
    Ritorna una PIL.Image in modalità RGB o L.
    Solleva ValueError per estensioni non supportate,
    o le eccezioni native di PIL/rawpy/pillow-heif per file corrotti.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in _JPEG_EXTS or ext in _PNG_EXTS:
        return Image.open(path)

    if ext in _HEIC_EXTS:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError as e:
            raise ImportError(
                "pillow-heif non installato. "
                "Esegui: pip install pillow-heif"
            ) from e
        return Image.open(path)

    if ext in _RAW_EXTS:
        try:
            import rawpy
            import numpy as np
        except ImportError as e:
            raise ImportError(
                "rawpy non installato. Esegui: pip install rawpy"
            ) from e
        with rawpy.imread(path) as raw:
            rgb_array = raw.postprocess(use_camera_wb=True, no_auto_bright=False)
        return Image.fromarray(rgb_array)

    raise ValueError(
        f"Formato non supportato: '{ext}'. "
        f"Estensioni accettate: JPG, PNG, HEIC, RAW ({', '.join(sorted(_RAW_EXTS))})"
    )


def prepare_for_ai(
    image_path: str,
    max_side_px: Optional[int] = None,
    jpeg_quality: Optional[int] = None,
    target_max_kb: Optional[int] = None,
) -> bytes:
    """
    Prepara un'immagine per l'invio all'AI (§13):
      1. Apre il file in qualsiasi formato supportato
      2. Ridimensiona al lato massimo (mai upscale)
      3. Converte in RGB se necessario
      4. Codifica in JPEG con qualità configurabile
      5. Se ancora > target_max_kb, abbassa la qualità (min 60%)

    Ritorna i byte JPEG. MAI scrive su disco.
    """
    side = max_side_px or config.MAX_SIDE_PX
    quality = jpeg_quality or config.JPEG_QUALITY
    target_kb = target_max_kb or config.TARGET_MAX_KB

    img = open_any_format(image_path)

    # Ridimensiona solo se necessario (thumbnail non fa upscale)
    if max(img.size) > side:
        img.thumbnail((side, side), Image.LANCZOS)

    # Converti in RGB (richiesto per JPEG: no RGBA, no palette)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = _encode_jpeg(img, quality)

    # Auto-downgrade qualità se il file è ancora troppo grande
    while len(buf) > target_kb * 1024 and quality > 60:
        quality -= 10
        buf = _encode_jpeg(img, quality)

    return buf


def generate_thumbnail(
    image_path: str,
    size: Optional[int] = None,
    quality: Optional[int] = None,
) -> bytes:
    """
    Genera una thumbnail JPEG per la UI (griglia / lightbox).
    - Lato lungo massimo: size (default config.THUMBNAIL_SIZE = 400px)
    - Qualità: config.THUMBNAIL_QUALITY (default 82%)
    - Mai upscale: immagini già piccole restano invariate

    Ritorna i byte JPEG. MAI scrive su disco.
    """
    thumb_size = size or config.THUMBNAIL_SIZE
    thumb_quality = quality or config.THUMBNAIL_QUALITY

    img = open_any_format(image_path)

    # thumbnail() di PIL non fa upscale
    img.thumbnail((thumb_size, thumb_size), Image.LANCZOS)

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    return _encode_jpeg(img, thumb_quality)


# ── Helpers privati ───────────────────────────────────────────────

def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    """Codifica una PIL.Image in bytes JPEG con la qualità indicata."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
