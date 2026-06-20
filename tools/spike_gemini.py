"""Phase 0 de-risk spike (plan §13).

Proves the load-bearing assumptions BEFORE the architecture is built on them:
  1. The exact gemini model ids in core/constants.py are callable on this auth setup.
  2. Files API upload + context caching actually work.
  3. Turn 2 re-uses the cache (cached_content_token_count > 0) → the ~10% cost lever.
  4. Real per-turn token counts + $ cost match the cost model (~$0.04/turn cached).

Run:  make spike            (uses creds from .env)
  or: uv run python tools/spike_gemini.py [path/to/manual.pdf]

If no PDF is given, a large synthetic manual (.txt) is generated so the caching
mechanics + pricing can be verified without the real IVT manual. Swap in a real
PDF once available to confirm multimodal/diagram handling too.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from core import constants  # noqa: E402
from core.services import gemini  # noqa: E402


def _make_synthetic_doc() -> tuple[str, str]:
    """Write a large synthetic 'manual' to exercise caching. Returns (path, mime)."""
    out = ROOT / "data" / "uploads" / "_spike_manual.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    section = (
        "SECTION {n}: Exhaust-air heat pump service notes.\n"
        "Alarm codes: E{n}1 low airflow (check filter), E{n}2 high condenser temp, "
        "E{n}3 sensor fault. Hot-water production drops when the extract-air filter "
        "is clogged. Always read the display alarm log before any reset. See the "
        "wiring overview on page {n} for sensor placement. Do NOT open electrical "
        "panels or touch the refrigerant circuit; escalate to a technician.\n\n"
    )
    out.write_text("".join(section.format(n=i) for i in range(1, 1200)), encoding="utf-8")
    return str(out), "text/plain"


def main() -> int:
    print("=== Phase 0 Gemini spike ===")
    health = gemini.health_check()
    print("auth:", health)
    if not health.get("ready"):
        print("\nABORT: no usable Gemini credentials. Set Vertex (GOOGLE_CLOUD_PROJECT + ADC/SA) "
              "or GEMINI_API_KEY in .env, then re-run `make spike`.")
        return 1

    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        doc_path, mime = sys.argv[1], None
        print(f"\nUsing provided document: {doc_path}")
    else:
        doc_path, mime = _make_synthetic_doc()
        print(f"\nNo PDF given — generated synthetic manual: {doc_path} "
              f"({Path(doc_path).stat().st_size // 1024} KB)")

    flash = constants.MODELS["flash"]
    flash_lite = constants.MODELS["flash_lite"]

    # --- confirm flash-lite id is callable (cheap classify path) ---
    print(f"\n[1] flash-lite id check: {flash_lite}")
    try:
        r = gemini.generate("Reply with the single word: OK", model=flash_lite, max_output_tokens=8)
        print(f"    PASS  text={r.text!r}  in={r.prompt_tokens} out={r.completion_tokens} "
              f"cost=${r.cost_usd:.6f}  mode={r.auth_mode}")
    except Exception as e:  # noqa: BLE001
        print(f"    FAIL  {type(e).__name__}: {e}")

    # --- upload + cache the manual, run 2 turns on flash ---
    print(f"\n[2] Files API upload + context cache on: {flash}")
    try:
        handle = gemini.upload_file(doc_path, mime_type=mime)
        print(f"    uploaded: {getattr(handle, 'name', handle)}")
        cache_name = gemini.create_cache(
            model=flash, contents=[handle], ttl_seconds=600, display_name="spike-manual"
        )
        print(f"    cache: {cache_name}")
    except Exception as e:  # noqa: BLE001
        print(f"    FAIL (upload/cache): {type(e).__name__}: {e}")
        return 2

    q1 = "From the manual, what does alarm code E11 mean and what is the first safe check?"
    q2 = "And what about E32 — what does it indicate?"
    for i, q in enumerate((q1, q2), start=1):
        try:
            r = gemini.generate(q, model=flash, cached_content=cache_name, max_output_tokens=256)
            print(f"\n    turn {i}: in={r.prompt_tokens} cached={r.cached_tokens} "
                  f"out={r.completion_tokens} cost=${r.cost_usd:.6f}")
            print(f"      answer: {r.text[:160]!r}")
        except Exception as e:  # noqa: BLE001
            print(f"\n    turn {i} FAIL: {type(e).__name__}: {e}")

    print("\n=== Spike done. If turn 2 shows cached>0 and costs match core/constants, "
          "pin the ids/prices and proceed to Phase 1+. ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
