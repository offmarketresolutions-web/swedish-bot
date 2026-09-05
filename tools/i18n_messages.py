"""Extract translatable strings and compile the catalogue — without GNU gettext.

Django's `makemessages`/`compilemessages` shell out to xgettext/msgfmt, which are not
installed on the Windows dev box (Git for Windows does not bundle them). This does the same
two jobs in pure Python via polib, so the workflow is:

    python tools/i18n_messages.py extract     # templates + .py -> locale/sv/.../django.po
    python tools/i18n_messages.py compile     # .po -> .mo  (Django reads ONLY the .mo)
    python tools/i18n_messages.py stats       # how much is still untranslated

Why it matters: the repo had a 33-entry .po against ~586 {% trans %} tags and NO compiled
.mo at all, so switching the dashboard to Swedish silently rendered English.

Deliberately narrow: it understands the constructs this codebase actually uses —
{% trans "x" %}, {% translate "x" %}, {% blocktrans %}…{% endblocktrans %}, and
gettext/gettext_lazy/_( "x" ) in Python. It is not a general gettext replacement, and it
never invents translations: existing msgstr values are preserved on re-extract.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import polib

REPO_ROOT = Path(__file__).resolve().parent.parent
PO_PATH = REPO_ROOT / "locale" / "sv" / "LC_MESSAGES" / "django.po"
MO_PATH = PO_PATH.with_suffix(".mo")
TEMPLATE_DIRS = [REPO_ROOT / "templates"]
PY_PACKAGES = ["chat", "crm", "core", "dashboard", "kb", "voice", "config"]

# {% trans "x" %} / {% translate 'x' %}  (optional `context` / `as var` tails tolerated)
_TRANS = re.compile(r"{%\s*(?:trans|translate)\s+(\"([^\"]*)\"|'([^']*)')")
# {% blocktrans ... %} BODY {% endblocktrans %}
_BLOCK = re.compile(r"{%\s*blocktrans(?:late)?[^%]*%}(.*?){%\s*endblocktrans(?:late)?\s*%}", re.S)
# gettext("x") / gettext_lazy('x') / _("x")
_PY = re.compile(r"\b(?:gettext_lazy|gettext|ugettext|_)\(\s*(\"([^\"]*)\"|'([^']*)')")


def _pick(m: re.Match) -> str:
    return m.group(2) if m.group(2) is not None else (m.group(3) or "")


def extract() -> dict[str, list[str]]:
    """msgid -> list of "path:line" occurrences, in stable (sorted) order."""
    found: dict[str, list[str]] = {}

    def add(msgid: str, path: Path, lineno: int) -> None:
        msgid = msgid.strip()
        if msgid:
            found.setdefault(msgid, []).append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}")

    for root in TEMPLATE_DIRS:
        for tpl in sorted(root.rglob("*.html")):
            text = tpl.read_text(encoding="utf-8")
            for m in _TRANS.finditer(text):
                add(_pick(m), tpl, text[:m.start()].count("\n") + 1)
            for m in _BLOCK.finditer(text):
                # blocktrans bodies keep their {{ placeholders }} verbatim in the msgid
                add(" ".join(m.group(1).split()), tpl, text[:m.start()].count("\n") + 1)

    for pkg in PY_PACKAGES:
        for py in sorted((REPO_ROOT / pkg).rglob("*.py")):
            if "migrations" in py.parts:
                continue
            text = py.read_text(encoding="utf-8")
            for m in _PY.finditer(text):
                add(_pick(m), py, text[:m.start()].count("\n") + 1)
    return found


def write_po(found: dict[str, list[str]]) -> tuple[int, int, int]:
    """Merge into the .po, PRESERVING every existing translation. Returns (total, new, stale)."""
    po = polib.pofile(str(PO_PATH)) if PO_PATH.exists() else polib.POFile()
    po.metadata = po.metadata or {}
    po.metadata.update({
        "Project-Id-Version": "nordland-bot",
        "Language": "sv",
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    })
    existing = {e.msgid: e for e in po}
    new = 0
    for msgid, occurrences in found.items():
        occ = [(p.rsplit(":", 1)[0], p.rsplit(":", 1)[1]) for p in occurrences]
        if msgid in existing:
            existing[msgid].occurrences = occ
            existing[msgid].obsolete = False
        else:
            po.append(polib.POEntry(msgid=msgid, msgstr="", occurrences=occ))
            new += 1
    stale = 0
    for entry in po:
        if entry.msgid not in found and entry.msgid:
            entry.obsolete = True      # keep the translation, stop shipping it
            stale += 1
    PO_PATH.parent.mkdir(parents=True, exist_ok=True)
    po.save(str(PO_PATH))
    return len(found), new, stale


def compile_mo() -> tuple[int, int]:
    po = polib.pofile(str(PO_PATH))
    translated = [e for e in po if e.msgstr and not e.obsolete]
    po.save_as_mofile(str(MO_PATH))
    return len(translated), len([e for e in po if not e.obsolete])


def stats() -> None:
    if not PO_PATH.exists():
        print("no .po yet — run extract")
        return
    po = polib.pofile(str(PO_PATH))
    live = [e for e in po if not e.obsolete]
    done = [e for e in live if e.msgstr]
    print(f"{len(done)}/{len(live)} translated ({100 * len(done) // max(1, len(live))}%)"
          f" | obsolete kept: {len([e for e in po if e.obsolete])}"
          f" | .mo {'present' if MO_PATH.exists() else 'MISSING'}")
    missing = [e.msgid for e in live if not e.msgstr]
    if missing:
        print(f"untranslated sample: {missing[:8]}")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "extract":
        total, new, stale = write_po(extract())
        print(f"extracted {total} msgids ({new} new, {stale} now obsolete) -> {PO_PATH.relative_to(REPO_ROOT)}")
    elif cmd == "compile":
        translated, live = compile_mo()
        print(f"compiled {translated}/{live} translated entries -> {MO_PATH.relative_to(REPO_ROOT)}")
    elif cmd == "stats":
        stats()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
