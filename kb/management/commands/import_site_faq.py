"""Import the public FAQ ('Vanliga frågor') from nordlandvvs.se into kb.SiteFAQ.

Pulls the WordPress REST API (clean structured JSON, no HTML scraping) and upserts
by slug, so it is idempotent + re-runnable to refresh.

    python manage.py import_site_faq [--base-url https://www.nordlandvvs.se] [--dry-run]
"""
import html
import json
import re
import urllib.request
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError

DEFAULT_BASE = "https://www.nordlandvvs.se"
ENDPOINT = "/wp-json/wp/v2/vanliga-fragor?per_page=100&_embed"


def _strip_html(raw: str) -> str:
    t = re.sub(r"<(script|style)[\s\S]*?</\1>", "", raw or "", flags=re.I)
    t = re.sub(r"</(p|div|h[1-6]|li|br)\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<li[^>]*>", "• ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _topic(item: dict) -> str:
    try:
        terms = item.get("_embedded", {}).get("wp:term", [])
        for group in terms:
            for term in group:
                if term.get("taxonomy") == "frageamne":
                    return term.get("slug", "")
    except Exception:  # noqa: BLE001
        pass
    return ""


class Command(BaseCommand):
    help = "Import the public FAQ from nordlandvvs.se into kb.SiteFAQ (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default=DEFAULT_BASE)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from kb.models import SiteFAQ

        parts = urlsplit(opts["base_url"])
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise CommandError("--base-url must be an http(s) URL (SSRF guard).")
        url = opts["base_url"].rstrip("/") + ENDPOINT
        req = urllib.request.Request(url, headers={"User-Agent": "NordlandKB/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            items = json.load(resp)

        created = updated = 0
        for it in items:
            slug = it.get("slug")
            if not slug:
                continue
            question = html.unescape((it.get("title") or {}).get("rendered", "")).strip()
            answer = _strip_html((it.get("content") or {}).get("rendered", ""))
            if not question or not answer:
                continue
            fields = {
                "topic": _topic(it), "question": question[:300], "answer": answer,
                "lang": "sv", "source_url": it.get("link", ""), "is_active": True,
            }
            if opts["dry_run"]:
                self.stdout.write(f"[{fields['topic'] or '—':22}] {question[:70]}")
                continue
            obj, was_created = SiteFAQ.objects.update_or_create(slug=slug, defaults=fields)
            created += was_created
            updated += not was_created

        if opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Dry run: {len(items)} FAQ items fetched."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"SiteFAQ import: {created} created, {updated} updated "
                f"({SiteFAQ.objects.count()} total)."))
