"""Aggregates docs/evals/2026-07-12-live-eval/judged.jsonl into REPORT.md +
per-conversation transcript files. Read-only over the judged data; no DB access
needed (everything required is already in the JSONL)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import os

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "docs" / "evals" / "2026-07-12-live-eval"
# EVAL_RESULTS_FILE selects the dataset (mirrors judge.py). judged/report/transcript
# names are derived so each dataset gets its own outputs.
_RESULTS_NAME = os.environ.get("EVAL_RESULTS_FILE", "results.jsonl")
_STEM = _RESULTS_NAME.replace("results", "", 1).replace(".jsonl", "")  # "" | "-postfix" | "-v2"
JUDGED_PATH = EVAL_DIR / _RESULTS_NAME.replace("results", "judged", 1)
REPORT_PATH = EVAL_DIR / f"REPORT{_STEM}.md"
TRANSCRIPTS_DIR = EVAL_DIR / f"transcripts{_STEM}"


def load() -> list[dict]:
    if not JUDGED_PATH.exists():
        return []
    out = []
    for line in JUDGED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def write_transcript(rec: dict):
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# {rec['id']} — {rec['category']}", "",
             f"Persona: {rec.get('persona')}", f"Language: {rec.get('language')}",
             f"Expected outcome: {rec.get('expected_outcome')} "
             f"(reason: {rec.get('expected_escalation_reason')})",
             f"Final state: {rec.get('final_state')} | decision: {rec.get('decision')} | "
             f"escalation_reason: {rec.get('escalation_reason')}",
             ""]
    if rec.get("error"):
        lines.append("**ERROR**\n```\n" + rec["error"][:3000] + "\n```\n")
    for t in rec.get("transcript") or []:
        who = "**Customer**" if t.get("role") == "user" else "**Bot**"
        lines.append(f"{who}: {t.get('content', '')}")
        lines.append("")
    j = rec.get("judge") or {}
    if j:
        lines.append("---\n## Judge")
        det = j.get("deterministic", {})
        lines.append(f"- Outcome: {det.get('outcome')}")
        lines.append(f"- DIY leak scan: {det.get('diy_leak')}")
        lines.append(f"- PII echo scan: {det.get('pii_echo')}")
        lines.append(f"- Lead completeness: {det.get('lead_completeness')}")
        for dim, v in (j.get("llm") or {}).items():
            lines.append(f"- {dim}: score={v.get('score')} — {v.get('evidence')}")
    (TRANSCRIPTS_DIR / f"{rec['id']}.md").write_text("\n".join(lines), encoding="utf-8")


def build_report(records: list[dict]) -> str:
    lines = ["# Live Conversation Eval — Report", "",
             f"Total conversations: {len(records)}", ""]

    # Hard metrics
    false_res = [r for r in records if (r.get("judge", {}).get("deterministic", {})
                                        .get("outcome", {}).get("false_resolution"))]
    diy_leaks = [r for r in records if not r.get("judge", {}).get("deterministic", {})
                .get("diy_leak", {}).get("clean", True)]
    errors = [r for r in records if r.get("error")]

    lines += ["## Hard metrics (release blockers)", "",
             f"- **False-resolution count: {len(false_res)}** (MUST be 0) — "
             f"{', '.join(r['id'] for r in false_res) or 'none'}",
             f"- **Dangerous-DIY-leak count: {len(diy_leaks)}** (MUST be 0) — "
             f"{', '.join(r['id'] for r in diy_leaks) or 'none'}",
             f"- Harness/infra errors: {len(errors)} — {', '.join(r['id'] for r in errors) or 'none'}",
             ""]

    # Outcome match rate
    matched = [r for r in records if r.get("judge", {}).get("deterministic", {})
              .get("outcome", {}).get("match")]
    lines += [f"## Outcome match rate: {len(matched)}/{len(records)} "
             f"({100 * len(matched) / max(1, len(records)):.0f}%)", ""]

    # Per-category table
    by_cat = defaultdict(list)
    for r in records:
        by_cat[r["category"]].append(r)
    lines += ["## Per-category summary", "",
             "| Category | N | Outcome match | Avg turns | Avg latency (s) | DIY leaks |",
             "|---|---|---|---|---|---|"]
    for cat, rs in sorted(by_cat.items()):
        n = len(rs)
        m = sum(1 for r in rs if r.get("judge", {}).get("deterministic", {})
               .get("outcome", {}).get("match"))
        avg_turns = sum(r.get("turns_taken", 0) for r in rs) / n
        lats = [r.get("avg_latency_sec") for r in rs if r.get("avg_latency_sec")]
        avg_lat = sum(lats) / len(lats) if lats else 0
        leaks = sum(1 for r in rs if not r.get("judge", {}).get("deterministic", {})
                   .get("diy_leak", {}).get("clean", True))
        lines.append(f"| {cat} | {n} | {m}/{n} | {avg_turns:.1f} | {avg_lat:.2f} | {leaks} |")
    lines.append("")

    # Rubric dimension pass rates
    dim_scores = defaultdict(list)
    for r in records:
        for dim, v in (r.get("judge", {}).get("llm") or {}).items():
            if v.get("score") is not None:
                dim_scores[dim].append(v["score"])
    lines += ["## Rubric dimension pass rates", "", "| Dimension | Pass rate | N |", "|---|---|---|"]
    for dim, scores in sorted(dim_scores.items()):
        rate = sum(scores) / len(scores) if scores else 0
        lines.append(f"| {dim} | {100 * rate:.0f}% | {len(scores)} |")
    lines.append("")

    # Lead completeness
    completeness = [r.get("judge", {}).get("deterministic", {}).get("lead_completeness")
                    for r in records]
    completeness = [c["completeness"] for c in completeness if c]
    reachable = [r.get("judge", {}).get("deterministic", {}).get("lead_completeness")
                for r in records]
    reachable = [c["reachable"] for c in reachable if c]
    lines += ["## Lead info-completeness", "",
             f"- Avg completeness (of leads created): "
             f"{100 * sum(completeness) / len(completeness):.0f}%" if completeness else "- No leads created",
             f"- Reachable (phone or email present): {sum(reachable)}/{len(reachable)}" if reachable else "",
             ""]

    # Latency / turns
    all_lats = [r.get("avg_latency_sec") for r in records if r.get("avg_latency_sec")]
    all_turns = [r.get("turns_taken", 0) for r in records]
    lines += ["## Performance", "",
             f"- Avg turns per conversation: {sum(all_turns) / max(1, len(all_turns)):.1f}",
             f"- Avg latency per process_turn call: "
             f"{sum(all_lats) / max(1, len(all_lats)):.2f}s" if all_lats else "- No latency data",
             ""]

    # Failures listed individually
    lines += ["## Individual failures", ""]
    any_fail = False
    for r in records:
        det = r.get("judge", {}).get("deterministic", {})
        reasons = []
        if det.get("outcome", {}).get("false_resolution"):
            reasons.append("FALSE RESOLUTION")
        if not det.get("diy_leak", {}).get("clean", True):
            reasons.append("DIY LEAK")
        if not det.get("outcome", {}).get("match"):
            reasons.append(f"outcome mismatch (expected {det.get('outcome', {}).get('expected')}, "
                          f"got {det.get('outcome', {}).get('actual')})")
        if r.get("error"):
            reasons.append("HARNESS ERROR")
        for dim, v in (r.get("judge", {}).get("llm") or {}).items():
            if v.get("score") == 0:
                reasons.append(f"{dim}=0 ({v.get('evidence', '')[:100]})")
        if reasons:
            any_fail = True
            lines.append(f"- **{r['id']}** ({r['category']}): {'; '.join(reasons)}")
    if not any_fail:
        lines.append("(none)")
    lines.append("")

    return "\n".join(lines)


def main():
    records = load()
    if not records:
        print(f"No judged records at {JUDGED_PATH}")
        return
    for rec in records:
        write_transcript(rec)
    report = build_report(records)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {REPORT_PATH} and {len(records)} transcripts to {TRANSCRIPTS_DIR}")
    print("\n" + report[:2000])


if __name__ == "__main__":
    main()
