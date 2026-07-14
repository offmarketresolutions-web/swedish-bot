"""Autonomous convergence driver for the live eval (harness-only helper).

Runs tools/eval/runner.py in repeated passes until all 200 specs have a SUCCESS
record in results.jsonl. Between passes it prunes error records (infra_timeout /
exhausted-retry 429) so the runner re-attempts them; concurrency steps down over
passes so stubborn stragglers run with minimal flash-quota contention (the tight
Vertex flash quota is the binding constraint — high concurrency 429s, low
concurrency is slow-but-clean). Idempotent: safe to launch after a partial run.

Usage:  POSTGRES_DB=eval_nordland python tools/eval/drive_eval.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# EVAL_RESULTS_FILE keeps post-fix runs (merged conversation-gap fixes) in a
# separate dataset from the frozen pre-fix baseline in results.jsonl. The child
# runner inherits the same env var, so driver and runner always agree on the file.
RESULTS = REPO_ROOT / "docs" / "evals" / "2026-07-12-live-eval" / os.environ.get(
    "EVAL_RESULTS_FILE", "results.jsonl")
RUNNER = REPO_ROOT / "tools" / "eval" / "runner.py"
PY = sys.executable

# Per-pass (workers, wall_cap_seconds). The binding constraint is the ~24-30/min
# LLM call ceiling (flash latency + a light global throttle); with ~6 calls/turn a
# conversation shares that budget with its concurrent peers, so per-conversation
# wall time GROWS with worker count. The cap must therefore be GENEROUS (a low cap
# at high concurrency fails everything). Strategy: run the bulk at moderate
# concurrency for aggregate throughput, then step concurrency DOWN for the long
# escalation/looping stragglers (less peer-sharing → they finish under the cap and
# with fewer 429s). Every pass keeps a generous cap so genuine long conversations
# complete as real records; only truly pathological runs hit it.
PASS_PLAN = [
    (3, 1300), (3, 1300), (2, 1400), (2, 1400),
    (2, 1400), (1, 1400), (1, 1400), (1, 1400), (1, 1400), (1, 1400),
]
TARGET = 200


def _load():
    if not RESULTS.exists():
        return []
    return [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]


def _prune_errors_keep_good() -> tuple[int, int]:
    recs = _load()
    good = {}
    for r in recs:
        if r.get("error"):
            continue
        good.setdefault(r["id"], r)  # keep first success per id
    RESULTS.write_text(
        "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in good.values()),
        encoding="utf-8",
    )
    return len(good), len(recs)


def main():
    for i, (workers, wall) in enumerate(PASS_PLAN, 1):
        good, _ = _prune_errors_keep_good()
        if good >= TARGET:
            print(f"[drive] all {good}/{TARGET} specs have success records — done.", flush=True)
            break
        print(f"[drive] pass {i}: {good}/{TARGET} good; launching runner --workers {workers} "
              f"wall_cap={wall}s at {time.strftime('%H:%M:%S')}", flush=True)
        env = dict(os.environ)
        env["EVAL_CONV_WALL_S"] = str(wall)
        env["EVAL_CONV_HARD_S"] = str(wall + 150)
        # Runner skips ids already present (the good ones) and attempts the rest once.
        proc = subprocess.run([PY, str(RUNNER), "--workers", str(workers)],
                              cwd=str(REPO_ROOT), env=env)
        print(f"[drive] pass {i} runner exited rc={proc.returncode} at "
              f"{time.strftime('%H:%M:%S')}", flush=True)

    good, total = _prune_errors_keep_good()
    print(f"[drive] FINAL: {good}/{TARGET} success records ({total} rows before prune). "
          f"Missing: {TARGET - good}", flush=True)
    if good < TARGET:
        done_ids = {r["id"] for r in _load()}
        # Report which ids never succeeded (import specs to enumerate).
        sys.path.insert(0, str(REPO_ROOT))
        os.environ.setdefault("POSTGRES_DB", "eval_nordland")
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django
        django.setup()
        from tools.eval import personas
        missing = [s.id for s in personas.SPECS if s.id not in done_ids]
        print(f"[drive] still-missing ids: {missing}", flush=True)


if __name__ == "__main__":
    main()
