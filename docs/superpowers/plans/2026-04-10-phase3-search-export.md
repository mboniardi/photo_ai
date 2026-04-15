# Phase 3 — Semantic Search + ZIP Export

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semantic photo search (cosine similarity on AI embeddings) and ZIP export of selected photos.

**Architecture:** `services/search.py` contains pure search logic (cosine similarity, quality keyword detection, ranking). `api/search.py` handles HTTP: embeds the query via the configured AI engine then calls `semantic_search()`. `api/export.py` builds a ZIP in-memory (no temp files) and returns it as a StreamingResponse. `database/photos.py`'s `get_photos()` is extended with 3 new pre-filter params (date range, location partial match, orientation).

**Tech Stack:** NumPy (already installed), Python zipfile + io.BytesIO, FastAPI StreamingResponse, re (stdlib), pytest + fastapi.testclient

---

## File Map

```
database/
  photos.py           # MODIFY — add date_from, date_to, location, orientation to get_photos()
services/
  search.py           # CREATE — cosine_similarity, is_quality_query, extract_limit, semantic_search
api/
  search.py           # CREATE — POST /api/search
  export.py           # CREATE — POST /api/export/zip
main.py               # MODIFY — include search_router and export_router
tests/
  test_search.py      # CREATE — unit tests for services/search.py
  test_api_search.py  # CREATE — API tests for /api/search
  test_api_export.py  # CREATE — API tests for /api/export/zip
```

---

## Task A: Extend database/photos.py + Create services/search.py

**Files:**
- Modify: `database/photos.py` — add 4 new optional params to `get_photos()`
- Create: `services/search.py`
- Create: `tests/test_search.py`

### New filters to add to get_photos()

Current signature ends at `offset: int = 0`. Add these params before `sort_by`:

```python
date_from: Optional[str] = None,    # "YYYY-MM-DD" lower bound on exif_date
date_to: Optional[str] = None,      # "YYYY-MM-DD" upper bound on exif_date
location: Optional[str] = None,     # partial case-insensitive match on location_name
orientation: Optional[str] = None,  # "horizontal" | "vertical" | "square"
```

Add these conditions inside `get_photos()` after the existing `if format is not None` block:

```python
if date_from is not None:
    conditions.append("substr(exif_date, 1, 10) >= ?")
    params.append(date_from)
if date_to is not None:
    conditions.append("substr(exif_date, 1, 10) <= ?")
    params.append(date_to)
if location is not None:
    conditions.append("location_name LIKE ?")
    params.append(f"%{location}%")
if orientation == "horizontal":
    conditions.append("width > height")
elif orientation == "vertical":
    conditions.append("height > width")
elif orientation == "square":
    conditions.append("width = height")
```

### services/search.py — full implementation

```python
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

SIMILARITY_THRESHOLD = 0.25


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 if either vector is zero-norm."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def is_quality_query(query: str) -> bool:
    """True if query contains at least one quality keyword."""
    words = set(re.split(r"\W+", query.lower()))
    return bool(words & QUALITY_KEYWORDS)


def extract_limit(query: str) -> Optional[int]:
    """Return first integer found in query, or None. E.g. 'le 10 migliori' -> 10."""
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
    """
    Return photos ranked by cosine similarity to query_embedding.
    Only considers analyzed photos (embedding IS NOT NULL).
    Pre-filters using the provided filter params before computing similarity.
    """
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
        sim = cosine_similarity(query_embedding, emb)
        if sim < threshold:
            continue
        photo_dict = dict(p)
        photo_dict["similarity"] = round(sim, 4)
        results.append(photo_dict)

    if is_quality:
        def _rank(r: dict) -> float:
            score_norm = (r.get("overall_score") or 0.0) / 10.0
            return 0.6 * r["similarity"] + 0.4 * score_norm
        results.sort(key=_rank, reverse=True)
    else:
        results.sort(key=lambda r: r["similarity"], reverse=True)

    if limit is not None:
        results = results[:limit]

    return results
```

### tests/test_search.py — full test file

```python
"""Test per services/search.py e per i nuovi filtri di database/photos.py."""
import json
import pytest
from database.models import init_db
from database.photos import insert_photo, update_photo, get_photos


@pytest.fixture
def db_with_photos(tmp_path):
    """
    DB con 3 foto:
      p1 — score 9.0, embedding [1, 0, 0], horizontal (100x80), date 2023-06-01, location Roma
      p2 — score 4.0, embedding [0.9, 0.1, 0], vertical (80x100), date 2023-08-15, location Parigi
      p3 — score 5.0, NO embedding, square (100x100)
    """
    db = str(tmp_path / "test.db")
    init_db(db)

    p1 = insert_photo(db, file_path=str(tmp_path / "p1.jpg"),
                      folder_path=str(tmp_path), filename="p1.jpg",
                      format="jpg", file_size=1000, width=100, height=80)
    update_photo(db, p1, overall_score=9.0,
                 embedding=json.dumps([1.0, 0.0, 0.0]),
                 analyzed_at="2023-06-01T10:00:00",
                 location_name="Roma, Italy", exif_date="2023-06-01T10:00:00")

    p2 = insert_photo(db, file_path=str(tmp_path / "p2.jpg"),
                      folder_path=str(tmp_path), filename="p2.jpg",
                      format="jpg", file_size=1000, width=80, height=100)
    update_photo(db, p2, overall_score=4.0,
                 embedding=json.dumps([0.9, 0.1, 0.0]),
                 analyzed_at="2023-08-15T10:00:00",
                 location_name="Parigi, France", exif_date="2023-08-15T10:00:00")

    p3 = insert_photo(db, file_path=str(tmp_path / "p3.jpg"),
                      folder_path=str(tmp_path), filename="p3.jpg",
                      format="jpg", file_size=1000, width=100, height=100)
    update_photo(db, p3, overall_score=5.0)

    return db, p1, p2, p3


# ── database/photos.py new filters ────────────────────────────────

class TestGetPhotosNewFilters:
    def test_date_from_filters(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        results = get_photos(db, date_from="2023-07-01")
        ids = [r["id"] for r in results]
        assert p2 in ids
        assert p1 not in ids

    def test_date_to_filters(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        results = get_photos(db, date_to="2023-07-01")
        ids = [r["id"] for r in results]
        assert p1 in ids
        assert p2 not in ids

    def test_date_range_filters(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        results = get_photos(db, date_from="2023-06-01", date_to="2023-07-01")
        ids = [r["id"] for r in results]
        assert p1 in ids
        assert p2 not in ids

    def test_location_partial_match(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        results = get_photos(db, location="Roma")
        ids = [r["id"] for r in results]
        assert p1 in ids
        assert p2 not in ids

    def test_orientation_horizontal(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        results = get_photos(db, orientation="horizontal")
        ids = [r["id"] for r in results]
        assert p1 in ids
        assert p2 not in ids
        assert p3 not in ids

    def test_orientation_vertical(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        results = get_photos(db, orientation="vertical")
        ids = [r["id"] for r in results]
        assert p2 in ids
        assert p1 not in ids

    def test_orientation_square(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        results = get_photos(db, orientation="square")
        ids = [r["id"] for r in results]
        assert p3 in ids
        assert p1 not in ids


# ── cosine_similarity ──────────────────────────────────────────────

class TestCosineSimilarity:
    def test_identical_vectors(self):
        from services.search import cosine_similarity
        assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        from services.search import cosine_similarity
        assert cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) == pytest.approx(0.0)

    def test_zero_vector_returns_zero(self):
        from services.search import cosine_similarity
        assert cosine_similarity([0.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 0.0

    def test_opposite_vectors(self):
        from services.search import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


# ── is_quality_query ───────────────────────────────────────────────

class TestIsQualityQuery:
    def test_migliori(self):
        from services.search import is_quality_query
        assert is_quality_query("le 10 migliori foto di Roma") is True

    def test_top(self):
        from services.search import is_quality_query
        assert is_quality_query("top paesaggi montani") is True

    def test_eccellenti(self):
        from services.search import is_quality_query
        assert is_quality_query("foto eccellenti di Parigi") is True

    def test_french_meilleurs(self):
        from services.search import is_quality_query
        assert is_quality_query("les meilleurs couchers de soleil") is True

    def test_normal_query_not_quality(self):
        from services.search import is_quality_query
        assert is_quality_query("paesaggi montani al tramonto") is False

    def test_case_insensitive(self):
        from services.search import is_quality_query
        assert is_quality_query("le MIGLIORI foto") is True


# ── extract_limit ──────────────────────────────────────────────────

class TestExtractLimit:
    def test_extracts_number_from_query(self):
        from services.search import extract_limit
        assert extract_limit("le 10 migliori foto") == 10

    def test_no_number_returns_none(self):
        from services.search import extract_limit
        assert extract_limit("paesaggi montani") is None

    def test_first_number_returned(self):
        from services.search import extract_limit
        assert extract_limit("le 5 foto del 2023") == 5


# ── semantic_search ────────────────────────────────────────────────

class TestSemanticSearch:
    def test_excludes_photos_without_embedding(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        results = semantic_search(db, [1.0, 0.0, 0.0])
        ids = [r["id"] for r in results]
        assert p3 not in ids

    def test_filters_by_similarity_threshold(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        # orthogonal to all embeddings
        results = semantic_search(db, [0.0, 0.0, 1.0])
        assert results == []

    def test_similarity_key_present_in_result(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        results = semantic_search(db, [1.0, 0.0, 0.0])
        assert len(results) > 0
        assert "similarity" in results[0]

    def test_sorted_by_similarity_desc(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        results = semantic_search(db, [1.0, 0.0, 0.0])
        sims = [r["similarity"] for r in results]
        assert sims == sorted(sims, reverse=True)

    def test_quality_ranking_prefers_high_score(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        # p1 has score 9.0, p2 has score 4.0; with quality ranking p1 should win
        results = semantic_search(db, [1.0, 0.0, 0.0], is_quality=True)
        assert results[0]["id"] == p1

    def test_limit_applied(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        results = semantic_search(db, [1.0, 0.0, 0.0], limit=1)
        assert len(results) == 1

    def test_orientation_prefilter(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        results = semantic_search(db, [1.0, 0.0, 0.0], orientation="vertical")
        ids = [r["id"] for r in results]
        assert p1 not in ids
        assert p2 in ids
```

### Steps

- [ ] **Step A.1: Write failing tests for get_photos new filters (RED)**

  Run: `.venv/bin/pytest tests/test_search.py::TestGetPhotosNewFilters -v`
  Expected: `ImportError` or `TypeError` (params not yet in get_photos)

- [ ] **Step A.2: Add new params to get_photos() in database/photos.py**

  Edit `database/photos.py` — update signature and conditions block as shown above.

- [ ] **Step A.3: Run filter tests (GREEN)**

  Run: `.venv/bin/pytest tests/test_search.py::TestGetPhotosNewFilters -v`
  Expected: 7 PASSED

- [ ] **Step A.4: Write failing tests for services/search.py (RED)**

  Run: `.venv/bin/pytest tests/test_search.py -v --ignore-glob="*TestGetPhotos*"`
  Expected: `ModuleNotFoundError: No module named 'services.search'`

- [ ] **Step A.5: Create services/search.py**

  Create file with the full implementation shown above.

- [ ] **Step A.6: Run all test_search.py tests (GREEN)**

  Run: `.venv/bin/pytest tests/test_search.py -v`
  Expected: All PASSED (17 tests)

- [ ] **Step A.7: Run full test suite to check no regressions**

  Run: `.venv/bin/pytest -q`
  Expected: All PASSED

- [ ] **Step A.8: Commit**

  ```bash
  git add database/photos.py services/search.py tests/test_search.py
  git commit -m "feat(phase3): semantic search logic + extended photo filters"
  ```

---

## Task B: api/search.py + api/export.py + main.py

**Files:**
- Create: `api/search.py`
- Create: `api/export.py`
- Create: `tests/test_api_search.py`
- Create: `tests/test_api_export.py`
- Modify: `main.py`

### api/search.py — full implementation

```python
"""Route /api/search — ricerca semantica."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import config
from database.settings import get_setting
from services.search import semantic_search, is_quality_query, extract_limit

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    folder_path: Optional[str] = None
    is_favorite: Optional[bool] = None
    is_trash: Optional[bool] = None
    min_score: Optional[float] = None
    format: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    location: Optional[str] = None
    orientation: Optional[str] = None
    limit: Optional[int] = None


async def _get_engine():
    """Returns the configured AI engine (Gemini or Ollama)."""
    from services.ai.gemini import GeminiEngine
    from services.ai.ollama import OllamaEngine

    engine_name = get_setting(config.LOCAL_DB, "ai_engine") or "gemini"
    if engine_name == "ollama":
        base_url = get_setting(config.LOCAL_DB, "ollama_base_url") or "http://localhost:11434"
        vision = get_setting(config.LOCAL_DB, "ollama_vision_model") or "llava"
        embed = get_setting(config.LOCAL_DB, "ollama_embed_model") or "nomic-embed-text"
        return OllamaEngine(vision_model=vision, embed_model=embed, base_url=base_url)
    api_key = get_setting(config.LOCAL_DB, "gemini_api_key") or config.GEMINI_API_KEY
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API key non configurata")
    return GeminiEngine(api_key=api_key)


@router.post("")
async def search_photos(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query non può essere vuota")

    engine = await _get_engine()
    query_embedding = await engine.embed(req.query)

    is_quality = is_quality_query(req.query)
    limit = req.limit if req.limit is not None else extract_limit(req.query)

    return semantic_search(
        config.LOCAL_DB,
        query_embedding,
        is_quality=is_quality,
        limit=limit,
        folder_path=req.folder_path,
        is_favorite=req.is_favorite,
        is_trash=req.is_trash,
        min_score=req.min_score,
        format=req.format,
        date_from=req.date_from,
        date_to=req.date_to,
        location=req.location,
        orientation=req.orientation,
    )
```

### api/export.py — full implementation

```python
"""Route /api/export — esporta selezione foto come ZIP in-memory."""
import io
import zipfile
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database.photos import get_photo_by_id
import config

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportRequest(BaseModel):
    photo_ids: list[int]


@router.post("/zip")
def export_zip(req: ExportRequest):
    if not req.photo_ids:
        raise HTTPException(status_code=400, detail="Nessuna foto selezionata")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"foto_selezione_{timestamp}.zip"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for photo_id in req.photo_ids:
            photo = get_photo_by_id(config.LOCAL_DB, photo_id)
            if photo is None:
                continue
            try:
                with open(photo["file_path"], "rb") as f:
                    zf.writestr(photo["filename"], f.read())
            except OSError:
                continue
    buf.seek(0)

    return StreamingResponse(
        iter([buf.read()]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )
```

### main.py changes

Add imports after existing router imports:
```python
from api.search import router as search_router
from api.export import router as export_router
```

Add router registrations after existing `app.include_router(queue_router)`:
```python
app.include_router(search_router)
app.include_router(export_router)
```

### tests/test_api_search.py — full test file

```python
"""Test per api/search.py."""
import json
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_analyzed_photo(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo, update_photo
    init_db(db)
    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (100, 80)).save(photo_path, "JPEG")
    pid = insert_photo(db, file_path=photo_path, folder_path=str(tmp_path),
                       filename="test.jpg", format="jpg", file_size=1000,
                       width=100, height=80)
    update_photo(db, pid, overall_score=8.0,
                 embedding=json.dumps([1.0, 0.0, 0.0]),
                 analyzed_at="2023-06-01T10:00:00")
    from main import app
    return TestClient(app), pid


class FakeEngine:
    async def embed(self, text: str) -> list:
        return [1.0, 0.0, 0.0]


def _async_fake_engine():
    async def _inner():
        return FakeEngine()
    return _inner


class TestSearchPhotos:
    def test_returns_200(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        resp = c.post("/api/search", json={"query": "paesaggi"})
        assert resp.status_code == 200

    def test_returns_list(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        data = c.post("/api/search", json={"query": "paesaggi"}).json()
        assert isinstance(data, list)

    def test_result_has_similarity(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        data = c.post("/api/search", json={"query": "paesaggi"}).json()
        assert len(data) == 1
        assert "similarity" in data[0]

    def test_empty_query_returns_400(self, client_with_analyzed_photo, monkeypatch):
        c, _ = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        resp = c.post("/api/search", json={"query": "   "})
        assert resp.status_code == 400

    def test_with_orientation_filter(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        data = c.post("/api/search",
                      json={"query": "paesaggi", "orientation": "horizontal"}).json()
        assert len(data) == 1

    def test_vertical_filter_excludes_photo(self, client_with_analyzed_photo, monkeypatch):
        c, pid = client_with_analyzed_photo
        import api.search as m
        monkeypatch.setattr(m, "_get_engine", _async_fake_engine())
        # Photo is 100x80 (horizontal); vertical filter should return 0
        data = c.post("/api/search",
                      json={"query": "paesaggi", "orientation": "vertical"}).json()
        assert len(data) == 0
```

### tests/test_api_export.py — full test file

```python
"""Test per api/export.py."""
import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_photo(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo
    init_db(db)
    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (100, 100)).save(photo_path, "JPEG")
    pid = insert_photo(db, file_path=photo_path, folder_path=str(tmp_path),
                       filename="test.jpg", format="jpg", file_size=1000,
                       width=100, height=100)
    from main import app
    return TestClient(app), pid


class TestExportZip:
    def test_returns_200(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        assert resp.status_code == 200

    def test_content_type_is_zip(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        assert resp.headers["content-type"] == "application/zip"

    def test_filename_has_timestamp_prefix(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        cd = resp.headers["content-disposition"]
        assert "foto_selezione_" in cd
        assert ".zip" in cd

    def test_zip_contains_photo_file(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [pid]})
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert "test.jpg" in zf.namelist()

    def test_empty_photo_ids_returns_400(self, client_with_photo):
        c, _ = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": []})
        assert resp.status_code == 400

    def test_invalid_photo_id_skipped_gracefully(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/export/zip", json={"photo_ids": [99999]})
        assert resp.status_code == 200

    def test_multiple_photos_in_zip(self, client_with_photo, tmp_path, monkeypatch):
        c, pid = client_with_photo
        import config
        from database.photos import insert_photo
        photo2 = str(tmp_path / "second.jpg")
        Image.new("RGB", (50, 50)).save(photo2, "JPEG")
        pid2 = insert_photo(config.LOCAL_DB, file_path=photo2,
                            folder_path=str(tmp_path), filename="second.jpg",
                            format="jpg", file_size=500, width=50, height=50)
        resp = c.post("/api/export/zip", json={"photo_ids": [pid, pid2]})
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert len(zf.namelist()) == 2
```

### Steps

- [ ] **Step B.1: Write failing API search tests (RED)**

  Run: `.venv/bin/pytest tests/test_api_search.py -v`
  Expected: `ImportError` (api/search.py does not exist yet)

- [ ] **Step B.2: Write failing API export tests (RED)**

  Run: `.venv/bin/pytest tests/test_api_export.py -v`
  Expected: `ImportError` (api/export.py does not exist yet)

- [ ] **Step B.3: Create api/search.py**

  Create with the full implementation shown above.

- [ ] **Step B.4: Create api/export.py**

  Create with the full implementation shown above.

- [ ] **Step B.5: Add routers to main.py**

  In `main.py`, after the existing imports:
  ```python
  from api.search import router as search_router
  from api.export import router as export_router
  ```
  After `app.include_router(queue_router)`:
  ```python
  app.include_router(search_router)
  app.include_router(export_router)
  ```

- [ ] **Step B.6: Run all new API tests (GREEN)**

  Run: `.venv/bin/pytest tests/test_api_search.py tests/test_api_export.py -v`
  Expected: All PASSED (12 tests total)

- [ ] **Step B.7: Run full test suite to check no regressions**

  Run: `.venv/bin/pytest -q`
  Expected: All PASSED

- [ ] **Step B.8: Commit**

  ```bash
  git add api/search.py api/export.py tests/test_api_search.py tests/test_api_export.py main.py
  git commit -m "feat(phase3): /api/search semantic search and /api/export/zip"
  ```
