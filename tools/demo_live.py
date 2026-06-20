"""End-to-end LIVE demo: a full conversation through the orchestrator with the
real Vertex Gemini and the ingested IVT 490 manual in context. Prints each turn.

Run after: make_demo_pdf + seed_kb + ingest_pdf (see the Makefile `demo` target).
"""
import os
import sys
from pathlib import Path

import django

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from chat import orchestrator as orch  # noqa: E402


def main():
    conv, greet = orch.open_conversation("en")
    print("BOT:", greet["message"], "\n")

    def say(text):
        r = orch.process_turn(conv, text)
        print("YOU:", text)
        print("BOT:", (r["message"] or "")[:500])
        print(f"     [state={r['state']} decision={r.get('decision')}]\n")
        return r

    say("heat_pump")
    say("My IVT 490 shows alarm E11 and the hot water is gone")
    say("IVT")
    say("IVT 490")
    conv.refresh_from_db()
    cs = conv.case_state
    print(f"[debug] confidence={cs.get('confidence')} decision={cs.get('decision')} "
          f"match={cs.get('match_confidence')} reason={cs.get('escalation_reason')}")
    print("=== demo complete ===")


if __name__ == "__main__":
    main()
