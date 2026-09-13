"""Print one eval conversation as a readable transcript (harness-only helper).

The judged/results JSONL rows embed the transcript as a list of {role, content}
dicts alongside ~20 metadata keys, so eyeballing a single conversation otherwise
means writing the same extraction snippet every time.

    python tools/eval/show.py R018
    python tools/eval/show.py R018 --file judged-cur.jsonl
    python tools/eval/show.py --failures --file judged-cur.jsonl   # list mismatches

No Django, no DB — it only reads the JSONL.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "evals" / "2026-07-12-live-eval"


def load(name: str) -> list[dict]:
    path = EVAL_DIR / name
    if not path.exists():
        raise SystemExit(f"No such results file: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def outcome(row: dict) -> tuple[str, str, bool]:
    """(expected, actual, match) — judged rows carry it, raw results rows don't."""
    det = (row.get("judge") or {}).get("deterministic") or {}
    o = det.get("outcome") or {}
    return o.get("expected", row.get("expected_outcome", "?")), o.get("actual", "?"), bool(o.get("match"))


def show(row: dict) -> None:
    exp, act, ok = outcome(row)
    print(f"{row['id']}  [{row['category']}]  {row.get('persona', '')}")
    print(f"  code={row.get('code_version')}  turns={row.get('turns_taken')}/{row.get('target_turns')}  "
          f"state={row.get('final_state')}  decision={row.get('decision')}  "
          f"esc_reason={row.get('escalation_reason')}")
    print(f"  expected={exp}  actual={act}  {'MATCH' if ok else 'MISMATCH'}")
    if row.get("notes"):
        print(f"  notes: {row['notes']}")
    if row.get("error"):
        print(f"  ERROR: {row['error']}")
    print("-" * 78)
    for m in row.get("transcript") or []:
        print(f"[{m.get('role', '?'):9}] {m.get('content', '')}")
    llm = (row.get("judge") or {}).get("llm") or {}
    if llm:
        print("-" * 78)
        for dim, v in llm.items():
            if isinstance(v, dict):
                print(f"  {dim}: score={v.get('score')} — {str(v.get('evidence', ''))[:300]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="spec ids to print (e.g. R018 A002)")
    ap.add_argument("--file", default="judged-run100.jsonl")
    ap.add_argument("--failures", action="store_true", help="list outcome mismatches and exit")
    args = ap.parse_args()

    rows = load(args.file)
    if args.failures:
        bad = [r for r in rows if not outcome(r)[2]]
        print(f"{len(bad)}/{len(rows)} outcome mismatches in {args.file}")
        for r in sorted(bad, key=lambda x: x["id"]):
            exp, act, _ = outcome(r)
            print(f"  {r['id']:6} {r['category']:12} {exp} -> {act}")
        return 0

    by_id = {r["id"]: r for r in rows}
    for i in args.ids:
        if i not in by_id:
            print(f"!! {i} not in {args.file}")
            continue
        show(by_id[i])
        print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
