#!/usr/bin/env bash
# Quota-aware wrapper around judge.py (mirrors run100_resume.sh). judge.py itself
# already resumes correctly -- it skips any id already present in judged-*.jsonl
# with LLM scores -- so a 429 mid-run just needs a retry, not special recovery.
set -u
cd "$(dirname "$0")/../.."
PY=./.venv/Scripts/python.exe
RESULTS_N=100
JUDGED=docs/evals/2026-07-12-live-eval/judged-run100.jsonl
SLEEP_EXHAUSTED=${SLEEP_EXHAUSTED:-180}

probe() {
  POSTGRES_DB=eval_nordland "$PY" - <<'PY' 2>/dev/null
import os, sys, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from core.services import gemini
try:
    gemini.generate("ok", model="gemini-2.5-flash", max_output_tokens=5)
    sys.exit(0)
except Exception as e:
    sys.exit(0 if "429" not in str(e) and "RESOURCE_EXHAUSTED" not in str(e) else 1)
PY
}

while true; do
  n=$(awk 'END{print NR}' "$JUDGED" 2>/dev/null); n=${n:-0}
  if [ "$n" -ge "$RESULTS_N" ]; then echo "[judge-resume] $n/$RESULTS_N judged — done."; break; fi
  if probe; then
    echo "[judge-resume] quota OK at $(date +%H:%M:%S) — running judge.py ($n/$RESULTS_N so far)"
    EVAL_RESULTS_FILE=results-run100.jsonl POSTGRES_DB=eval_nordland \
      "$PY" tools/eval/judge.py >>docs/evals/2026-07-12-live-eval/judge100.log 2>&1
    echo "[judge-resume] pass exited rc=$? at $(date +%H:%M:%S)"
  else
    echo "[judge-resume] quota exhausted at $(date +%H:%M:%S) — sleeping ${SLEEP_EXHAUSTED}s ($n/$RESULTS_N)"
    sleep "$SLEEP_EXHAUSTED"
  fi
done
