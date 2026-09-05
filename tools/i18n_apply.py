"""Apply a JSON batch of {msgid, msgstr} translations into the .po, then compile.

    python tools/i18n_apply.py translations.json

Refuses a translation whose placeholders don't match its msgid — a msgstr that drops or
mangles `{{ name }}` / `%(x)s` / `{% ... %}` renders broken text or raises at runtime, and
that is the one class of translation error a human reviewer reliably misses. Rejected
entries are reported and left untranslated rather than silently written.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import polib

REPO_ROOT = Path(__file__).resolve().parent.parent
PO_PATH = REPO_ROOT / "locale" / "sv" / "LC_MESSAGES" / "django.po"

# Everything that must survive translation byte-for-byte.
_PLACEHOLDER = re.compile(r"(\{\{.*?\}\}|\{%.*?%\}|%\([^)]*\)[sd]|%[sd]|<[^>]+>)")


def placeholders(text: str) -> list[str]:
    return sorted(_PLACEHOLDER.findall(text or ""))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    items = payload.get("final") or payload.get("translations") or payload
    if not isinstance(items, list):
        print("expected a JSON list of {msgid, msgstr}")
        return 2

    po = polib.pofile(str(PO_PATH))
    by_id = {e.msgid: e for e in po}
    applied = skipped_missing = rejected = unchanged = 0
    problems: list[str] = []

    for item in items:
        msgid, msgstr = item.get("msgid"), (item.get("msgstr") or "").strip()
        if not msgid or not msgstr:
            continue
        entry = by_id.get(msgid)
        if entry is None:
            skipped_missing += 1
            continue
        if placeholders(msgid) != placeholders(msgstr):
            rejected += 1
            problems.append(f"  {msgid[:58]!r}\n    -> {msgstr[:58]!r}\n"
                            f"    src={placeholders(msgid)} dst={placeholders(msgstr)}")
            continue
        if entry.msgstr == msgstr:
            unchanged += 1
            continue
        entry.msgstr = msgstr
        applied += 1

    po.save(str(PO_PATH))
    live = [e for e in po if not e.obsolete]
    done = [e for e in live if e.msgstr]
    print(f"applied {applied} | unchanged {unchanged} | rejected(placeholder mismatch) {rejected} "
          f"| msgid not in catalogue {skipped_missing}")
    print(f"catalogue now {len(done)}/{len(live)} translated "
          f"({100 * len(done) // max(1, len(live))}%)")
    if problems:
        print("\nREJECTED — placeholders differ (left untranslated):")
        print("\n".join(problems[:15]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
