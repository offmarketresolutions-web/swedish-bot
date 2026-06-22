"""Ingest a manual PDF for a machine (plan §8). Stores the file, parses text for
a token estimate (drives the cache-vs-inline decision), and records a sha256.

Usage: python manage.py ingest_pdf <machine_slug> <path/to/manual.pdf> [--lang en] [--kind manual]

The specialist loads the PDF into Gemini context as inline bytes; parsed_text here
is for the token estimate + an audit/searchable copy, NOT for chunk-retrieval.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from kb.ingest import IngestError, ingest_pdf_bytes, parse_pdf_text
from kb.models import Machine

# Back-compat alias: import_kb imports _parse_pdf_text from this module.
_parse_pdf_text = parse_pdf_text


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

        try:
            doc = ingest_pdf_bytes(machine, path.read_bytes(), path.name,
                                   lang=opts["lang"], kind=opts["kind"])
        except IngestError as exc:
            raise CommandError(str(exc)) from None

        self.stdout.write(self.style.SUCCESS(
            f"Ingested {path.name} for {machine}: ~{doc.token_estimate} tokens, sha {doc.sha256[:12]}"))
