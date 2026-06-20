"""Single source of truth for Gemini model ids + pricing (plan §2, §9, §13).

Every layer (agent router, cache builder, cost accounting) reads ids + prices
from HERE — a model rename or price change is a one-line edit.

⚠️  PHASE 0: the ids and per-1K prices below are the best-known June-2026 values
from public sources and are NOT yet verified against the live Vertex catalog.
The Phase 0 spike (tools/spike_gemini.py) must confirm each id is callable and
each price is correct, then update this file. Do not trust these numbers for
billing until that spike has run.
"""
from __future__ import annotations

# Logical role -> concrete model id. AgentPrompt.model_id in the DB overrides
# these per-agent (plan §7 canonical data model); this dict only seeds defaults.
MODELS = {
    "flash": "gemini-3.5-flash",        # workhorse: 1M ctx, multimodal
    "flash_lite": "gemini-flash-lite-latest",  # intake/extraction/router/safety
    "pro": "gemini-3.1-pro",            # reserved: v2 QA / hard cases (2M ctx)
}

# Per-1,000-token prices in USD: (input, output, cached_input).
# Cached input ≈ 10% of input (Gemini context caching, plan §1/§12).
PRICING_PER_1K = {
    "gemini-3.5-flash": (0.0015, 0.009, 0.00015),
    "gemini-3.1-pro": (0.002, 0.012, 0.0002),
    "gemini-flash-lite-latest": (0.0001, 0.0004, 0.00001),
}

# Below this many tokens, skip context caching and inline the PDF (plan §8 —
# Gemini caching has a minimum-token floor). Confirm exact floor in Phase 0.
CACHE_MIN_TOKENS = 4096


class UnknownModelError(KeyError):
    """Raised when a price is requested for a model id we don't have. Fail loud —
    never silently bill $0 (the bug we inherited from hermes/creds/gemini.py)."""


def price_per_1k(model_id: str) -> tuple[float, float, float]:
    try:
        return PRICING_PER_1K[model_id]
    except KeyError as exc:
        raise UnknownModelError(
            f"No price for model {model_id!r}. Add it to PRICING_PER_1K in "
            f"core/constants.py (confirm the live rate first). Known: "
            f"{sorted(PRICING_PER_1K)}"
        ) from exc


def cost_usd(
    model_id: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
) -> float:
    """Compute cost. `cached_tokens` are billed at the cached rate and are assumed
    to be a subset already excluded from `prompt_tokens` by the SDK usage metadata."""
    rate_in, rate_out, rate_cached = price_per_1k(model_id)
    return (
        (prompt_tokens / 1000.0) * rate_in
        + (completion_tokens / 1000.0) * rate_out
        + (cached_tokens / 1000.0) * rate_cached
    )
