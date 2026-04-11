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

    def test_is_trash_false_excludes_trash(self, db_with_photos):
        db, p1, p2, p3 = db_with_photos
        update_photo(db, p1, is_trash=1)
        results = get_photos(db, is_trash=False)
        ids = [r["id"] for r in results]
        assert p1 not in ids
        assert p2 in ids


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

    def test_excludes_trash_by_default(self, db_with_photos):
        from services.search import semantic_search
        db, p1, p2, p3 = db_with_photos
        update_photo(db, p2, is_trash=1)
        results = semantic_search(db, [0.9, 0.1, 0.0])
        ids = [r["id"] for r in results]
        assert p2 not in ids
