#!/usr/bin/env bash
# Quota-aware outer loop for the 100-conversation run.
#
# The binding constraint is the shared Vertex flash quota, not the bot: at 3 workers a
# probe call returned 429 RESOURCE_EXHAUSTED and 16/20 conversations died retrying into
# the 240s per-call ceiling. This loop probes with ONE cheap call, runs a serial driver
# pass only while the quota answers, and sleeps out the exhausted periods. The driver is
# idempotent (keeps good records, prunes error rows, skips ids already done), so any
# number of interrupted passes converge on the same 100 records.
#
# Usage: bash tools/eval/run100_resume.sh
set -u
cd "$(dirname "$0")/../.."
PY=./.venv/Scripts/python.exe
RESULTS=docs/evals/2026-07-12-live-eval/results-run100.jsonl
TARGET=100
# The quota oscillates on a short (per-minute-ish) window rather than staying dry for
# hours: back-to-back probes minutes apart returned OK then 429. Sleep short enough to
# catch an open window; the driver's own retry/backoff rides out brief 429s once a pass
# has started.
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
  n=$(awk 'END{print NR}' "$RESULTS" 2>/dev/null); n=${n:-0}
  good=$(grep -c '"error": null' "$RESULTS" 2>/dev/null || echo "$n")
  if [ "$n" -ge "$TARGET" ]; then echo "[resume] $n/$TARGET records — done."; break; fi
  if probe; then
    echo "[resume] quota OK at $(date +%H:%M:%S) — serial driver pass ($n/$TARGET so far)"
    EVAL_RESULTS_FILE=results-run100.jsonl \
    POSTGRES_DB=eval_nordland \
    EVAL_PASS_WORKERS=1 \
    EVAL_CALL_TIMEOUT_S=300 \
      "$PY" tools/eval/drive_eval.py --ids-file tools/eval/run100_ids.txt >>docs/evals/2026-07-12-live-eval/run100-drive.log 2>&1
    echo "[resume] pass exited rc=$? at $(date +%H:%M:%S)"
  else
    echo "[resume] quota exhausted at $(date +%H:%M:%S) — sleeping ${SLEEP_EXHAUSTED}s ($n/$TARGET)"
    sleep "$SLEEP_EXHAUSTED"
  fi
done
