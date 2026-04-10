"""Test per services/ai/base.py — interfaccia astratta AIEngine."""
import pytest


class TestAIEngineInterface:
    def test_cannot_instantiate_directly(self):
        from services.ai.base import AIEngine
        with pytest.raises(TypeError):
            AIEngine()

    def test_concrete_subclass_must_implement_analyze(self):
        from services.ai.base import AIEngine

        class Incomplete(AIEngine):
            async def embed(self, text): return []

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_must_implement_embed(self):
        from services.ai.base import AIEngine

        class Incomplete(AIEngine):
            async def analyze(self, image_bytes, location_hint=""): ...

        with pytest.raises(TypeError):
            Incomplete()

    def test_complete_subclass_instantiates(self):
        from services.ai.base import AIEngine

        class Complete(AIEngine):
            async def analyze(self, image_bytes, location_hint=""): ...
            async def embed(self, text): return []

        engine = Complete()
        assert engine is not None


class TestPhotoAnalysis:
    def test_overall_score_formula(self):
        from services.ai.base import PhotoAnalysis
        a = PhotoAnalysis(
            description="Test",
            technical_score=7.0,
            aesthetic_score=9.0,
            subject="paesaggio",
            atmosphere="serena",
            colors=["blu", "verde"],
            strengths="buona luce",
            weaknesses=None,
            ai_engine="gemini",
        )
        # overall = round(0.35*7 + 0.65*9, 1) = round(2.45 + 5.85, 1) = 8.3
        assert a.overall_score == pytest.approx(8.3, abs=0.05)

    def test_overall_score_computed_at_init(self):
        from services.ai.base import PhotoAnalysis
        a = PhotoAnalysis(
            description="x", technical_score=5.0, aesthetic_score=5.0,
            subject="x", atmosphere="x", colors=[], strengths="x",
            weaknesses=None, ai_engine="gemini",
        )
        assert a.overall_score == pytest.approx(5.0, abs=0.05)
