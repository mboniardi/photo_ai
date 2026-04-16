"""Logica di ricerca testuale con query expansion."""
import re
import sqlite3
from typing import Optional

QUALITY_KEYWORDS = frozenset({
    "migliori", "top", "eccellenti", "belle",
    "meilleurs", "meilleures",
    "best", "excellent",
})


def is_quality_query(query: str) -> bool:
    words = set(re.split(r"\W+", query.lower()))
    return bool(words & QUALITY_KEYWORDS)


def extract_limit(query: str) -> Optional[int]:
    m = re.search(r"\b(\d+)\b", query)
    return int(m.group(1)) if m else None


def text_search(
    db_path: str,
    keywords: list[str],
    *,
    is_quality: bool = False,
    limit: Optional[int] = None,
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
    """
    Ricerca foto per keyword nelle colonne testuali.
    Ogni keyword trovata in description/subject/atmosphere/location_name
    incrementa il punteggio di rilevanza. Risultati ordinati per rilevanza
    (+ overall_score se is_quality=True).
    """
    if not keywords:
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Costruisci filtri WHERE
    conditions = ["analyzed_at IS NOT NULL"]
    params: list = []

    if is_trash is not None:
        conditions.append("COALESCE(is_trash, 0) = ?")
        params.append(1 if is_trash else 0)
    if is_favorite is not None:
        conditions.append("COALESCE(is_favorite, 0) = ?")
        params.append(1 if is_favorite else 0)
    if folder_path:
        conditions.append("(folder_path = ? OR file_path LIKE ?)")
        params += [folder_path, f"{folder_path}/%"]
    if min_score is not None:
        conditions.append("overall_score >= ?")
        params.append(min_score)
    if format:
        conditions.append("LOWER(format) = ?")
        params.append(format.lower())
    if date_from:
        conditions.append("exif_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("exif_date <= ?")
        params.append(date_to)
    if location:
        conditions.append("LOWER(location_name) LIKE ?")
        params.append(f"%{location.lower()}%")
    if orientation:
        conditions.append("orientation = ?")
        params.append(orientation)

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM photos WHERE {where} LIMIT 100000",
        params,
    ).fetchall()
    conn.close()

    # Calcola rilevanza: conta quante keyword compaiono nel testo della foto
    search_fields = ("description", "subject", "atmosphere", "location_name")
    results = []
    for row in rows:
        combined = " ".join(
            (row[f] or "").lower() for f in search_fields
        )
        hits = sum(1 for kw in keywords if kw in combined)
        if hits == 0:
            continue
        photo = dict(row)
        photo["relevance"] = hits
        results.append(photo)

    # Ordina
    if is_quality:
        def _rank(r: dict) -> float:
            score_norm = (r.get("overall_score") or 0.0) / 10.0
            rel_norm = r["relevance"] / len(keywords)
            return 0.5 * rel_norm + 0.5 * score_norm
        results.sort(key=_rank, reverse=True)
    else:
        results.sort(key=lambda r: r["relevance"], reverse=True)

    if limit is not None:
        results = results[:limit]

    return results
