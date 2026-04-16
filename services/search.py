"""Logica di ricerca semantica sulle foto."""
import re
import json
from typing import Optional

import numpy as np

from database.photos import get_photos

QUALITY_KEYWORDS = frozenset({
    "migliori", "top", "eccellenti", "belle",
    "meilleurs", "meilleures",
    "best", "excellent",
})

SIMILARITY_THRESHOLD = 0.55


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def is_quality_query(query: str) -> bool:
    words = set(re.split(r"\W+", query.lower()))
    return bool(words & QUALITY_KEYWORDS)


def extract_limit(query: str) -> Optional[int]:
    m = re.search(r"\b(\d+)\b", query)
    return int(m.group(1)) if m else None


def semantic_search(
    db_path: Optional[str],
    query_embedding: list[float],
    *,
    is_quality: bool = False,
    limit: Optional[int] = None,
    threshold: float = SIMILARITY_THRESHOLD,
    folder_path: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    is_trash: Optional[bool] = None,
    min_score: Optional[float] = None,
    format: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    orientation: Optional[str] = None,
) -> list[dict]:
    photos = get_photos(
        db_path,
        analyzed_only=True,
        folder_path=folder_path,
        is_favorite=is_favorite,
        is_trash=is_trash,
        min_score=min_score,
        format=format,
        date_from=date_from,
        date_to=date_to,
        location=location,
        orientation=orientation,
        limit=100_000,
    )

    results: list[dict] = []
    for p in photos:
        if p["embedding"] is None:
            continue
        emb = json.loads(p["embedding"])
        if not emb:
            continue
        sim = cosine_similarity(query_embedding, emb)
        if sim < threshold:
            continue
        photo_dict = dict(p)
        photo_dict["similarity"] = round(sim, 4)
        results.append(photo_dict)

    if is_quality:
        # "le migliori foto di X": la similarity ha già filtrato per X,
        # ora ordina per qualità (overall_score) con similarity come tiebreaker
        results.sort(key=lambda r: (r.get("overall_score") or 0.0, r["similarity"]), reverse=True)
    else:
        results.sort(key=lambda r: r["similarity"], reverse=True)

    if limit is not None:
        results = results[:limit]

    return results


# Mantenuto per compatibilità con import esistenti
def text_search(*args, **kwargs) -> list[dict]:
    return []
