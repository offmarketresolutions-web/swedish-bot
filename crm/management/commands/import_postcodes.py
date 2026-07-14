"""Offline geocoding table import (plan S5/D2) — loads crm.PostcodeArea from the
GeoNames SE postal-code dump so service-area checks never need a runtime network
call or API key. CC-BY licensed, ~18k rows for Sweden.

Source: https://download.geonames.org/export/zip/SE.zip (contains SE.txt).
Format (tab-separated, no header): country_code, postal_code, place_name,
admin_name1, admin_code1, admin_name2, admin_code2, admin_name3, admin_code3,
latitude, longitude, accuracy.

    python manage.py import_postcodes path/to/SE.zip [--dry-run]
    python manage.py import_postcodes path/to/SE.txt [--dry-run]

Idempotent: update_or_create keyed on the 5-digit code, safe to re-run.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import GeoNames SE postal codes into crm.PostcodeArea (offline geocoding table)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to SE.zip or SE.txt (GeoNames postal-code export)")
        parser.add_argument("--dry-run", action="store_true", help="Parse and report only, write nothing")

    def handle(self, *args, **options):
        from crm.models import PostcodeArea

        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"file not found: {path}")

        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist()
                         if n.upper().endswith(".TXT") and "readme" not in n.lower()]
                if not names:
                    raise CommandError("no data .txt file found inside the zip")
                text = zf.read(names[0]).decode("utf-8")
        else:
            text = path.read_text(encoding="utf-8")

        dry = options["dry_run"]
        n_created = n_updated = n_skipped = 0
        rows = []
        for line in text.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 11:
                n_skipped += 1
                continue
            code = parts[1].strip().replace(" ", "")
            place = parts[2].strip()
            municipality = parts[5].strip()  # admin_name2
            county = parts[3].strip()        # admin_name1
            try:
                lat = float(parts[9])
                lng = float(parts[10])
            except ValueError:
                n_skipped += 1
                continue
            if not (len(code) == 5 and code.isdigit()):
                n_skipped += 1
                continue
            rows.append({"code": code, "lat": lat, "lng": lng, "city": place,
                         "municipality": municipality, "county": county})

        if dry:
            self.stdout.write(self.style.SUCCESS(
                f"Dry run: {len(rows)} valid rows parsed ({n_skipped} skipped)."))
            return

        for row in rows:
            code = row.pop("code")
            _, created = PostcodeArea.objects.update_or_create(code=code, defaults=row)
            n_created += created
            n_updated += not created

        self.stdout.write(self.style.SUCCESS(
            f"PostcodeArea: {n_created} created, {n_updated} updated, {n_skipped} skipped. "
            f"Total rows: {len(rows)}."))
