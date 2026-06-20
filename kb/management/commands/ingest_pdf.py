"""Ingest a manual PDF for a machine (plan §8). Stores the file, parses text for
a token estimate (drives the cache-vs-inline decision), and records a sha256.

Usage: python manage.py ingest_pdf <machine_slug> <path/to/manual.pdf> [--lang en] [--kind manual]

The specialist loads the PDF into Gemini context as inline bytes; parsed_text here
is for the token estimate + an audit/searchable copy, NOT for chunk-retrieval.
"""
import hashlib
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from kb.models import Machine, MachineDocument


def _parse_pdf_text(path: str) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


class Command(BaseCommand):
    help = "Ingest a manual PDF for a machine."

    def add_arguments(self, parser):
        parser.add_argument("machine_slug")
        parser.add_argument("pdf_path")
        parser.add_argument("--lang", default="en")
        parser.add_argument("--kind", default="manual")

    def handle(self, *args, **opts):
        try:
            machine = Machine.objects.get(slug=opts["machine_slug"])
        except Machine.DoesNotExist:
            raise CommandError(f"No machine with slug {opts['machine_slug']!r}") from None
        path = Path(opts["pdf_path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        text = _parse_pdf_text(str(path))
        token_estimate = max(len(text) // 4, 0)  # ~4 chars/token heuristic
        sha = hashlib.sha256(path.read_bytes()).hexdigest()

        doc = MachineDocument(
            machine=machine, lang=opts["lang"], kind=opts["kind"],
            parsed_text=text, token_estimate=token_estimate, sha256=sha,
        )
        with path.open("rb") as fh:
            doc.pdf.save(path.name, File(fh), save=True)

        self.stdout.write(self.style.SUCCESS(
            f"Ingested {path.name} for {machine}: ~{token_estimate} tokens, sha {sha[:12]}"))
