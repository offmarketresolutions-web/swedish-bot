"""Unit tests for core constants (cost) + the Gemini client shims. No DB, no network."""
import datetime as dt
import tempfile

import pytest

from core import constants
from core.services import gemini


def test_cost_does_not_double_count_cached():
    # From the Phase 0 spike: in=126375 total, cached=126356, out=10.
    c = constants.cost_usd("gemini-2.5-flash", prompt_tokens=126375, cached_tokens=126356, completion_tokens=10)
    # Only 19 tokens at full input rate + 126356 at cached + 10 out.
    rate_in, rate_out, rate_cached = constants.PRICING_PER_1K["gemini-2.5-flash"]
    expected = (19 / 1000) * rate_in + (126356 / 1000) * rate_cached + (10 / 1000) * rate_out
    assert c == pytest.approx(expected, rel=1e-9)
    # Sanity: materially cheaper than billing all 126375 at full input rate
    # (cached input ~25% of input rate for 2.5-flash).
    naive = (126375 / 1000) * rate_in
    assert c < naive * 0.5


def test_cached_is_cheaper_than_uncached():
    cached = constants.cost_usd("gemini-2.5-flash", prompt_tokens=120000, cached_tokens=120000)
    uncached = constants.cost_usd("gemini-2.5-flash", prompt_tokens=120000, cached_tokens=0)
    assert cached < uncached


def test_unknown_model_raises_not_zero():
    with pytest.raises(constants.UnknownModelError):
        constants.price_per_1k("gemini-nonexistent")
    with pytest.raises(constants.UnknownModelError):
        constants.cost_usd("gemini-nonexistent", prompt_tokens=100)


def test_models_map_has_expected_roles():
    assert set(constants.MODELS) == {"flash", "flash_lite", "pro", "embedding"}
    # generation defaults are priced in PRICING_PER_1K …
    for role in ("flash", "flash_lite", "pro"):
        assert constants.MODELS[role] in constants.PRICING_PER_1K
    # … the embedding default is priced in EMBED_PRICING_PER_1K
    assert constants.MODELS["embedding"] in constants.EMBED_PRICING_PER_1K


def test_clock_shim_patches_google_auth(monkeypatch):
    monkeypatch.setattr(gemini, "_measure_real_utc", lambda timeout=5.0: None)  # offline, fast
    gemini.ensure_clock_correction(force=True)
    import google.auth._helpers as helpers
    assert helpers.utcnow is gemini._corrected_utcnow
    assert isinstance(gemini._corrected_utcnow(), dt.datetime)


def test_file_part_builds_inline_part():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        fh.write(b"%PDF-1.4 fake")
        path = fh.name
    part = gemini.file_part(path)
    assert part is not None
    assert getattr(part, "inline_data", None) is not None  # google.genai Part


def test_guess_mime():
    assert gemini._guess_mime("a.pdf") == "application/pdf"
    assert gemini._guess_mime("a.PNG") == "image/png"
    assert gemini._guess_mime("a.unknown") == "application/octet-stream"
