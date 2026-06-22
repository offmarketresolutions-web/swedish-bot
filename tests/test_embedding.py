"""Gemini embedding engine: service-layer contract (mocked) + health surface."""
from core.services import gemini


def test_embed_single_returns_one_vector(mock_gemini):
    v = gemini.embed("IVT Geo 600C no heat", output_dimensionality=768)
    assert isinstance(v, list) and len(v) == 768
    assert all(isinstance(x, float) for x in v)


def test_embed_batch_returns_vector_per_input(mock_gemini):
    vs = gemini.embed(["a", "b", "c"], output_dimensionality=64)
    assert len(vs) == 3 and all(len(x) == 64 for x in vs)


def test_embed_is_deterministic(mock_gemini):
    assert gemini.embed("same text") == gemini.embed("same text")


def test_embed_empty_list(mock_gemini):
    assert gemini.embed([]) == []


def test_l2_normalize_unit_length():
    import math
    v = gemini._l2_normalize([3.0, 4.0])
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9


def test_health_reports_embedding_engine():
    # real health_check (no network) — exposes the configured embedding model
    h = gemini.health_check()
    assert h["embedding_model"] == "gemini-embedding-2"   # configured / preferred (latest)
    assert "embedding_model_active" in h                  # resolved after 404 fallback
    assert h["embedding_dim"] == 768
    assert h["llm_model"] == "gemini-2.5-flash"
