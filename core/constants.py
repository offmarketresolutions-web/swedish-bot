"""Single source of truth for Gemini model ids + pricing (plan §2, §9, §13).

Every layer (agent router, cache builder, cost accounting) reads ids + prices
from HERE — a model rename or price change is a one-line edit.

PHASE 0 STATUS (verified 2026-06 against the reused django_base Vertex project,
us-central1): the 3.x ids (gemini-3.5-flash, gemini-3.1-pro, gemini-flash-lite-*)
all 404 on that project — only the 2.5 family is available there, so we run the
demo on 2.5. `gemini-2.5-flash` and `gemini-2.5-flash-lite` confirmed callable.
When the client provisions their own europe-north1 project, re-run the spike and
update MODELS here if 3.x is available — every layer reads ids from this dict.
Prices below are best-known GA values; confirm against live billing before relying
on the $ figures (token COUNTS from the spike are exact; cost = counts × rate).
"""
from __future__ import annotations

# Logical role -> concrete model id. AgentPrompt.model_id in the DB overrides
# these per-agent (plan §7 canonical data model); this dict only seeds defaults.
MODELS = {
    "flash": "gemini-2.5-flash",        # workhorse: 1M ctx, multimodal (verified)
    "flash_lite": "gemini-2.5-flash-lite",  # intake/extraction/router/safety (verified)
    "pro": "gemini-2.5-pro",            # reserved: v2 QA / hard cases
}

# Per-1,000-token prices in USD: (input, output, cached_input).
PRICING_PER_1K = {
    "gemini-2.5-flash": (0.0003, 0.0025, 0.000075),
    "gemini-2.5-flash-lite": (0.0001, 0.0004, 0.000025),
    "gemini-2.5-pro": (0.00125, 0.010, 0.0003125),
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
    """Compute cost. Gemini's usage_metadata reports `prompt_token_count` as the
    TOTAL input (cache hits included) and `cached_content_token_count` as the
    cached subset. Billing: cached tokens at the cached rate, the remaining input
    at the full input rate (verified in the Phase 0 spike — do NOT double-count)."""
    rate_in, rate_out, rate_cached = price_per_1k(model_id)
    billable_input = max(prompt_tokens - cached_tokens, 0)
    return (
        (billable_input / 1000.0) * rate_in
        + (cached_tokens / 1000.0) * rate_cached
        + (completion_tokens / 1000.0) * rate_out
    )
