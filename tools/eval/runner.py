"""Live conversation eval runner. Drives `chat.orchestrator.process_turn` against
the REAL Vertex Gemini pipeline (no mocks) for each persona spec in
`tools/eval/personas.py`, with a simulated customer (`tools/eval/customer_sim.py`)
playing the other side.

MANDATORY DB isolation: this script points Django at `eval_nordland` (never the
dev `nordland` DB) via a POSTGRES_DB env override set BEFORE django.setup().

Usage (from repo root, uv venv):
    uv run python tools/eval/runner.py --limit 10
    uv run python tools/eval/runner.py --ids R001,E001,U001,S001,D001,A001,X001
    uv run python tools/eval/runner.py                # full 200

Checkpoints each finished conversation to docs/evals/2026-07-12-live-eval/results.jsonl
immediately (append + flush) — resumable: spec ids already present are skipped.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

# ── Anti-stall config (harness-only; production code untouched) ─────────────
# Root cause of the twin stalls: (1) the genai client is built with NO socket
# timeout, so one hung TLS connection wedges a worker forever; (2) a dead DB
# socket (the eval_nordland container exited mid-run) hangs psycopg recv() with
# no timeout. Both are now bounded by layered caps below.
LLM_HTTP_TIMEOUT_MS = int(os.environ.get("EVAL_LLM_TIMEOUT_MS", "120000"))  # per HTTP call
PER_CALL_HARD_TIMEOUT = float(os.environ.get("EVAL_CALL_TIMEOUT_S", "240"))  # per turn (calls self-heal internally)
CONV_WALL_CAP = float(os.environ.get("EVAL_CONV_WALL_S", "1200"))  # in-loop soft cap → infra_timeout
CONV_HARD_CAP = float(os.environ.get("EVAL_CONV_HARD_S", "1320"))  # backstop hard cap on run_one
WATCHDOG_INTERVAL = float(os.environ.get("EVAL_WATCHDOG_S", "180"))  # faulthandler thread dumps
HEARTBEAT_INTERVAL = float(os.environ.get("EVAL_HEARTBEAT_S", "60"))

_DONE_COUNT = 0
_DONE_LOCK = threading.Lock()

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ── DB isolation: MUST happen before django.setup() ─────────────────────────
os.environ.setdefault("POSTGRES_DB", "eval_nordland")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

assert os.environ.get("POSTGRES_DB") == "eval_nordland" or settings.DATABASES["default"]["NAME"] == "eval_nordland", (
    "Refusing to run: POSTGRES_DB is not pinned to eval_nordland. "
    f"Resolved DB name = {settings.DATABASES['default']['NAME']!r}"
)

from tools.eval import customer_sim, personas  # noqa: E402

# ── Inject a socket timeout into the genai client (the missing-timeout fix) ──
# Production `core.services.gemini.make_client` builds `genai.Client(...)` with no
# http_options timeout. We wrap the factory (harness-side monkeypatch, production
# file untouched) and stamp a per-request timeout on the client's api-client so a
# hung TLS connection raises instead of wedging the worker forever. Both the real
# orchestrator and the customer simulator route through make_client, so this one
# seam covers every LLM call in the harness.
from core.services import gemini as _gemini  # noqa: E402

_orig_make_client = _gemini.make_client


def _make_client_with_timeout(api_key: str | None = None):
    client, mode = _orig_make_client(api_key)
    try:
        client._api_client._http_options.timeout = LLM_HTTP_TIMEOUT_MS
    except Exception:  # noqa: BLE001 — never let the patch break a real run
        pass
    return client, mode


_gemini.make_client = _make_client_with_timeout

# ── Global QPM throttle (the real cure for the 429 storm) ────────────────────
# The Vertex project has a tight per-minute request quota. Unthrottled, even 2
# workers burst many generateContent/embed calls per second and trip 429
# RESOURCE_EXHAUSTED faster than backoff can recover. We pace the *start* of every
# LLM call globally (one gate across all workers and all call types) to stay under
# the QPM ceiling; worker count then only buys latency-hiding, not extra QPS.
_LLM_MIN_INTERVAL = float(os.environ.get("EVAL_LLM_MIN_INTERVAL_S", "2.0"))  # ~30 calls/min ceiling
_LLM_GATE = threading.Lock()
_LLM_LAST = [0.0]


def _throttle():
    with _LLM_GATE:
        wait = _LLM_MIN_INTERVAL - (time.monotonic() - _LLM_LAST[0])
        if wait > 0:
            time.sleep(wait)
        _LLM_LAST[0] = time.monotonic()


def _resilient_llm(fn, *, max_attempts=9):
    """Throttle + absorb 429s at the SINGLE-CALL level with full-jitter backoff.

    This is the key latency/robustness fix: previously an embed/flash 429 raised
    out of process_turn and forced the harness to re-run the ENTIRE turn (classify
    + embed + generate) after a long backoff — one 429 cost a whole wasted turn.
    Recovering per-call keeps a transient 429 from cascading into a turn re-run,
    so conversations finish fast and a brief flash-quota blip no longer fails a
    conversation. Full jitter decorrelates retries across workers (herd cure)."""
    import functools
    import random

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        last = None
        for attempt in range(max_attempts):
            _throttle()
            try:
                return fn(*a, **kw)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == max_attempts - 1 or not _is_transient(exc):
                    raise
                ceil = min(3.0 * (2 ** attempt), 45.0)
                time.sleep(random.uniform(0.5, ceil))
        raise last  # pragma: no cover

    return wrapper


def _throttled(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        _throttle()
        return fn(*a, **kw)
    return wrapper


# generate/embed self-heal on 429 at the call level. generate_stream is a lazy
# generator (the HTTP fires during iteration, not at call), so a call-level retry
# can't catch its 429s — it only gets throttled; the eval path uses generate, not
# generate_stream, so this is fine.
_gemini.generate = _resilient_llm(_gemini.generate)
_gemini.embed = _resilient_llm(_gemini.embed)
_gemini.generate_stream = _throttled(_gemini.generate_stream)

# Dataset separation (coordinator, 2026-07-13): the 59 pre-fix records in
# results.jsonl are the frozen baseline (old orchestrator). Runs against the merged
# conversation-gap fixes (commits b00e035+0d06dba) write to a separate file via
# EVAL_RESULTS_FILE, and every record carries the git SHA it ran against.
RESULTS_PATH = REPO_ROOT / "docs" / "evals" / "2026-07-12-live-eval" / os.environ.get(
    "EVAL_RESULTS_FILE", "results.jsonl")
_WRITE_LOCK = threading.Lock()


def _git_sha() -> str:
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


CODE_VERSION = _git_sha()

_TRANSIENT_MARKERS = ("429", "resource_exhausted", "503", "unavailable", "deadline",
                      "internal", "500", "timeout")


def _is_transient(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(m in s for m in _TRANSIENT_MARKERS)


def _call_with_timeout(fn, timeout: float):
    """Run fn in a throwaway thread and hard-cap it. A hung call (dead TLS/DB
    socket the socket-timeout somehow missed) can't be killed in Python, so we
    orphan the thread (shutdown(wait=False)) and raise — the worker recovers
    instead of wedging. Leaked threads are bounded (≤ one per genuinely hung
    call) and daemonic, so they never block interpreter exit."""
    ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evalcall")
    fut = ex.submit(fn)
    try:
        result = fut.result(timeout=timeout)
        ex.shutdown(wait=False)
        return result
    except FuturesTimeout:
        ex.shutdown(wait=False)  # orphan the hung thread; do NOT join
        raise TimeoutError(f"per-call hard timeout ({timeout:.0f}s) exceeded")


def _retry(fn, *, max_attempts=4, base_delay=4.0, call_timeout=PER_CALL_HARD_TIMEOUT):
    """Retry transient failures (429 RESOURCE_EXHAUSTED under the tight shared
    Vertex flash quota is the dominant one) with FULL-JITTER backoff. Full jitter
    (sleep a uniform random 0..cap, not cap±small) decorrelates retries across
    workers so they stop colliding on the same per-minute quota window — the
    thundering-herd cure. Cap is 55s so a single retry can outlast a full quota
    minute; wall cap still bounds total conversation time."""
    import random
    last = None
    for attempt in range(max_attempts):
        try:
            return _call_with_timeout(fn, call_timeout)
        except Exception as exc:  # noqa: BLE001
            last = exc
            transient = _is_transient(exc) or isinstance(exc, TimeoutError)
            if attempt == max_attempts - 1 or not transient:
                raise
            ceil = min(base_delay * (2 ** attempt), 55.0)
            time.sleep(random.uniform(0.5, ceil))  # full jitter
    raise last  # pragma: no cover


def _load_done_ids() -> set[str]:
    if not RESULTS_PATH.exists():
        return set()
    done = set()
    for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line)["id"])
        except Exception:  # noqa: BLE001
            continue
    return done


def _append_result(record: dict):
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK:
        with open(RESULTS_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def _artifacts_for(conv) -> dict:
    """Mirror what the real HTTP endpoint would have produced: crm.Session +
    ServiceRequest. Import locally so django.setup() has already run."""
    from crm.models import ServiceRequest, Session

    session = Session.objects.filter(conversation=conv).first()
    srs = list(ServiceRequest.objects.filter(session=session)) if session else []
    return {
        "session_id": session.id if session else None,
        "session_status": session.status if session else None,
        "session_resolved": session.resolved if session else None,
        "session_severity": session.severity if session else None,
        "decision": session.decision if session else None,
        "manufacturer": session.manufacturer if session else "",
        "model": session.model if session else "",
        "error_code": session.error_code if session else "",
        "service_request_count": len(srs),
        "service_requests": [
            {"id": sr.id, "escalation_reason": sr.escalation_reason, "payload_json": sr.payload_json}
            for sr in srs
        ],
    }


def run_one(spec) -> dict:
    from chat.orchestrator import open_conversation, process_turn

    t0 = time.time()
    latencies: list[float] = []
    transcript: list[dict] = []
    error = None
    final_case_state = {}

    try:
        conv, greet = _retry(lambda: open_conversation(spec.language))
        bot_msg = greet["message"]
        chips = greet.get("chips", [])
        transcript.append({"role": "assistant", "content": bot_msg, "chips": chips})

        user_text = spec.opening or ""
        # Escalation needs ~7 extra turns (diag + 4 contact slots + approval + thanks),
        # so the ceiling leaves room for a lead flow that starts near target_turns.
        max_iters = max(spec.target_turns, 6) + 10
        turns_done = 0
        last_state = greet.get("state")

        for _ in range(max_iters):
            if time.time() - t0 > CONV_WALL_CAP:
                error = (f"infra_timeout: conversation exceeded {CONV_WALL_CAP:.0f}s wall cap "
                         f"after {turns_done} turns (recorded as infra failure, not a bot failure)")
                break
            turns_done += 1
            t_turn = time.time()
            result = _retry(lambda: process_turn(conv, user_text, image=None))
            latencies.append(time.time() - t_turn)

            transcript.append({"role": "user", "content": user_text})
            bot_msg = result.get("message", "")
            chips = result.get("chips", [])
            last_state = result.get("state")
            transcript.append({"role": "assistant", "content": bot_msg, "chips": chips,
                               "state": last_state, "decision": result.get("decision")})

            if last_state == "RESOLVED":
                break
            # Stop at target_turns UNLESS an escalation contact/approval flow is in
            # flight — cutting that off mid-way would fabricate incomplete-lead failures.
            if turns_done >= spec.target_turns and last_state != "ESCALATE":
                break

            hist = [{"role": m["role"], "content": m["content"]} for m in transcript[:-1]]
            user_text = _retry(lambda: customer_sim.next_reply(spec, hist, bot_msg, chips=chips))

        conv.refresh_from_db()
        final_case_state = conv.case_state or {}
        artifacts = _artifacts_for(conv)
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()
        artifacts = {}

    wallclock = time.time() - t0
    return {
        "id": spec.id,
        "code_version": CODE_VERSION,
        "category": spec.category,
        "persona": spec.persona,
        "language": spec.language,
        "expected_outcome": spec.expected_outcome,
        "expected_escalation_reason": spec.expected_escalation_reason,
        "notes": spec.notes,
        "target_turns": spec.target_turns,
        "turns_taken": len(transcript) // 2,
        "final_state": final_case_state.get("state"),
        "escalation_reason": final_case_state.get("escalation_reason"),
        "decision": final_case_state.get("decision"),
        "slots": final_case_state.get("slots"),
        "contact": final_case_state.get("contact"),
        "artifacts": artifacts,
        "transcript": transcript,
        "latencies_sec": latencies,
        "avg_latency_sec": (sum(latencies) / len(latencies)) if latencies else None,
        "wallclock_sec": wallclock,
        "error": error,
    }


def _infra_record(spec, msg: str) -> dict:
    """A minimal, judge-compatible record for a conversation the harness had to
    abandon (hung past the hard cap). `error` set → judge.py skips the LLM judge
    and report.py counts it under harness/infra errors, never as a bot failure."""
    return {
        "id": spec.id, "code_version": CODE_VERSION, "category": spec.category, "persona": spec.persona,
        "language": spec.language, "expected_outcome": spec.expected_outcome,
        "expected_escalation_reason": spec.expected_escalation_reason, "notes": spec.notes,
        "target_turns": spec.target_turns, "turns_taken": 0, "final_state": None,
        "escalation_reason": None, "decision": None, "slots": None, "contact": None,
        "artifacts": {}, "transcript": [], "latencies_sec": [], "avg_latency_sec": None,
        "wallclock_sec": None, "error": msg,
    }


def run_one_guarded(spec) -> dict:
    """run_one with a hard wall-clock backstop. The in-loop CONV_WALL_CAP should
    normally fire first (clean record + partial artifacts); this catches a hang
    that never returns to the loop head (e.g. a wedged DB commit)."""
    ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evalconv")
    fut = ex.submit(run_one, spec)
    try:
        rec = fut.result(timeout=CONV_HARD_CAP)
        ex.shutdown(wait=False)
        return rec
    except FuturesTimeout:
        ex.shutdown(wait=False)  # orphan the wedged conversation thread
        return _infra_record(spec, f"infra_timeout: run_one exceeded {CONV_HARD_CAP:.0f}s hard cap")


def _heartbeat(stop_evt: threading.Event, total: int):
    while not stop_evt.wait(HEARTBEAT_INTERVAL):
        with _DONE_LOCK:
            done = _DONE_COUNT
        print(f"[hb] alive — {done}/{total} finished this run "
              f"({time.strftime('%H:%M:%S')})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", type=str, default=None, help="comma-separated spec ids")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    # Watchdog: dump every thread's traceback to stderr every WATCHDOG_INTERVAL s
    # so a silent stall is instantly diagnosable from the log (repeat=True keeps
    # re-arming). This is what was missing when the run "froze with no traceback".
    faulthandler.enable()
    faulthandler.dump_traceback_later(WATCHDOG_INTERVAL, repeat=True)

    if args.ids:
        wanted = [x.strip() for x in args.ids.split(",") if x.strip()]
        specs = [s for s in personas.SPECS if s.id in wanted]
        missing = set(wanted) - {s.id for s in specs}
        if missing:
            print(f"WARNING: unknown ids requested: {missing}")
    else:
        specs = list(personas.SPECS)
        if args.limit:
            specs = specs[: args.limit]

    done = _load_done_ids()
    todo = [s for s in specs if s.id not in done]
    # Category-priority order (coordinator, 2026-07-13): safety/difficult/edge have
    # never produced a completed conversation and carry the hard release metrics, so
    # they run FIRST; resolvable next (the before/after vs the 31-conv pre-fix
    # baseline is the key deliverable). Shuffle within each priority group with a
    # deterministic seed so no single long/looping cluster front-loads a pass.
    _PRIO = {"safety": 0, "difficult": 1, "edge": 2, "resolvable": 3,
             "adversarial": 4, "unsupported": 5, "escalate": 6}
    import random as _r
    _r.Random(20260713).shuffle(todo)
    todo.sort(key=lambda s: _PRIO.get(s.category, 9))
    print(f"DB: {settings.DATABASES['default']['NAME']} | total specs selected: {len(specs)} | "
          f"already done: {len(specs) - len(todo)} | to run: {len(todo)}")

    if not todo:
        print("Nothing to do (all selected specs already in results.jsonl).")
        return

    global _DONE_COUNT
    stop_evt = threading.Event()
    hb = threading.Thread(target=_heartbeat, args=(stop_evt, len(todo)), daemon=True)
    hb.start()

    ok, failed = 0, 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_one_guarded, s): s for s in todo}
            for fut in as_completed(futures):
                spec = futures[fut]
                try:
                    rec = fut.result()
                except Exception:  # noqa: BLE001
                    rec = {"id": spec.id, "category": spec.category, "error": traceback.format_exc()}
                _append_result(rec)
                with _DONE_LOCK:
                    _DONE_COUNT += 1
                if rec.get("error"):
                    failed += 1
                    print(f"[FAIL] {spec.id} ({spec.category}) — {str(rec['error'])[:200]}", flush=True)
                else:
                    ok += 1
                    print(f"[OK]   {spec.id} ({spec.category}) state={rec.get('final_state')} "
                          f"turns={rec.get('turns_taken')} avg_lat={rec.get('avg_latency_sec')}", flush=True)
    finally:
        stop_evt.set()
        faulthandler.cancel_dump_traceback_later()

    print(f"\nDone. ok={ok} failed={failed} total_this_run={ok + failed}", flush=True)


if __name__ == "__main__":
    main()
