"""One-shot: prune completed (non-error) v2-code RESOLVABLE records from the live
results file so the driver/runner re-runs them under the fixed customer_sim
resolve-arc (see customer_sim._RESOLVABLE_ARC).

WHY: the 2026-07-12 run scored resolvable 0/35 not because the bot regressed but
because (a) 15 records were open_conversation infra timeouts — the driver already
auto-prunes those between passes — and (b) the 18 completed resolvable records all
became escalated_lead: the OLD sim never confirmed a Tier-0 fix worked, so every
resolvable conversation collapsed into a technician lead. With the sim fix in place,
re-running the 18 lets genuine simple fixes actually CLOSE the case. Those 18 have
no `error`, so the driver's own error-prune leaves them; this removes them by id so
the runner re-attempts them.

SAFETY: the postfix driver rewrites the whole results file at each pass boundary
(_prune_errors_keep_good). Run this ONLY when the driver is idle / between passes,
never while a runner subprocess is mid-pass appending. Writes a .bak first.

Usage (driver idle):
    EVAL_RESULTS_FILE=results-postfix.jsonl uv run python tools/eval/prune_for_rerun.py
    EVAL_RESULTS_FILE=results-postfix.jsonl uv run python tools/eval/prune_for_rerun.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS = REPO_ROOT / "docs" / "evals" / "2026-07-12-live-eval" / os.environ.get(
    "EVAL_RESULTS_FILE", "results-postfix.jsonl")

# v2 code SHAs whose resolvable records are re-runnable under the sim fix. Older
# SHAs (e.g. 4b87654) are pre-v2 and out of scope for the v2 validation.
V2_SHAS = {"72e147c", "4154565"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the pruned file (else dry-run)")
    args = ap.parse_args()

    recs = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    to_drop, keep = [], []
    for r in recs:
        drop = (r.get("category") == "resolvable"
                and not r.get("error")
                and r.get("code_version") in V2_SHAS)
        (to_drop if drop else keep).append(r)

    print(f"{RESULTS.name}: {len(recs)} rows -> drop {len(to_drop)} v2 resolvable, keep {len(keep)}")
    print("dropping ids:", sorted(r["id"] for r in to_drop))
    if not args.apply:
        print("(dry-run; pass --apply to write. Ensure the driver is idle first.)")
        return
    shutil.copy2(RESULTS, RESULTS.with_suffix(RESULTS.suffix + ".bak_prune"))
    RESULTS.write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in keep),
        encoding="utf-8")
    print(f"wrote {len(keep)} rows; backup at {RESULTS.name}.bak_prune")


if __name__ == "__main__":
    main()
