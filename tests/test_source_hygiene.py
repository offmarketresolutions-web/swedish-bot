"""Repo-level source invariants.

Control characters inside a regex are the specific accident this guards against: a `\\b`
word boundary written through a mangling toolchain becomes a literal backspace (0x08),
which Python accepts silently. The regex then still compiles, still runs, and quietly
matches nothing — so a checker built on it reports "all clear" and guarantees nothing.

That happened three times in one session, once inside tools/eval/spec_conformance.py,
the file every spec-conformance claim is measured with. A cheap invariant beats noticing
it a fourth time.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", ".git", "node_modules", "__pycache__", "staticfiles", "data"}

# Tab and newline are legitimate; everything else in the C0 range is not.
FORBIDDEN = {chr(c) for c in range(32)} - {"\t", "\n", "\r"}


def _source_files():
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def test_no_control_characters_in_python_sources():
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            bad = sorted({ch for ch in line if ch in FORBIDDEN})
            if bad:
                names = ", ".join(f"0x{ord(c):02x}" for c in bad)
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} contains {names}")
    assert not offenders, "control characters in source (a mangled \\b?):\n" + "\n".join(offenders)


def test_no_unicode_replacement_characters_in_python_sources():
    """U+FFFD means an encoding round-trip already destroyed a character — in this repo
    that is usually a Swedish å/ä/ö inside a pattern or a customer-facing string."""
    offenders = [
        f"{p.relative_to(REPO_ROOT)}"
        for p in _source_files()
        if "\ufffd" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, "mojibake (U+FFFD) in source:\n" + "\n".join(offenders)


def test_no_multiline_django_comments_in_templates():
    """Django's {# #} is SINGLE-LINE only. A multi-line one is not a comment at all —
    it renders to the page as literal text. Two of them sat in dashboard/base.html, so
    every dashboard screen showed staff a paragraph of raw template source. Verified
    against the real engine: Template("A{# a\n b #}B").render() returns the comment.
    Use {% comment %}...{% endcomment %} for anything spanning lines."""
    import re

    offenders = []
    for path in (REPO_ROOT / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\{#", text):
            close = text.find("#}", m.start())
            if close != -1 and "\n" in text[m.start():close]:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{text[:m.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "multi-line {# #} renders as visible text; use {% comment %}:\n" + "\n".join(offenders))
