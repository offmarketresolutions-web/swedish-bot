"""Load the owner-authored initial service-area polygons (plan S5, owner decision #4)
into crm.ServiceArea, from docs/service-areas/initial-polygons.geojson.

GeoSettings stays at its current value (default OFF) — loading the polygons does
NOT flip the feature live; an operator must explicitly enable it in the dashboard.
Idempotent: update_or_create keyed on name.

    python manage.py seed_service_areas
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

DEFAULT_PATH = Path(settings.BASE_DIR) / "docs" / "service-areas" / "initial-polygons.geojson"


class Command(BaseCommand):
    help = "Load the initial owner-authored service-area polygons (GeoSettings stays OFF)."

    def add_arguments(self, parser):
        parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH),
                             help="Path to the FeatureCollection GeoJSON (default: docs/service-areas/initial-polygons.geojson)")

    def handle(self, *args, **options):
        from crm import geo
        from crm.models import ServiceArea

        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"file not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        features = data.get("features") or []
        n_created = n_updated = 0

        for feat in features:
            props = feat.get("properties") or {}
            name = props.get("name")
            kind = props.get("kind") if props.get("kind") in ("inside", "extension") else "inside"
            border_km = float(props.get("border_km") or 10)
            geometry, bbox_warning, error = geo.clean_polygon(feat.get("geometry"))
            if error:
                self.stderr.write(self.style.ERROR(f"{name}: {error} — skipped."))
                continue
            if bbox_warning:
                self.stderr.write(self.style.WARNING(f"{name}: no vertex inside the Sweden bbox — check axes."))
            _, created = ServiceArea.objects.update_or_create(
                name=name, defaults={"kind": kind, "polygon": geometry, "border_km": border_km})
            n_created += created
            n_updated += not created

        self.stdout.write(self.style.SUCCESS(
            f"ServiceArea: {n_created} created, {n_updated} updated. "
            f"GeoSettings.enabled is unchanged (dashboard-controlled) — nothing goes live from this command."))
