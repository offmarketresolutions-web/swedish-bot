"""Import the real Nordland VVS knowledge base (V2 §D). Maps the IVT manual PDFs
to Vendor=IVT + Category + Machine + MachineDocument, grouping variant PDFs under
one Machine. Idempotent (Machine by (vendor, model_name); MachineDocument by
sha256). `--include-terms` imports the Konsumentvillkor terms as PolicyDocuments.

    python manage.py import_kb --source "C:/Users/vladi/Downloads/Asistent/Asistent" \
        [--vendor IVT] [--lang sv] [--include-terms] [--dry-run]

The token/classify helpers are module-level so they can be unit-tested.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand

from kb.management.commands.ingest_pdf import _parse_pdf_text
from kb.models import Category, Machine, MachineDocument, PolicyDocument, Vendor

MANUALS_DIR = "Manulas IVT Heatingpumps"
TERMS_DIR = "Konsumentvilkor"

# Category tree the import needs (slug -> (name, parent_slug)).
CATEGORIES = {
    "heat_pump": ("Heat pump", None),
    "air_to_air": ("Air-to-air", "heat_pump"),
    "air_to_water": ("Air-to-water", "heat_pump"),
    "water_to_water": ("Water-to-water", "heat_pump"),
    "exhaust_air": ("Exhaust air", "heat_pump"),
}

TERMS_MAP = {
    "VVS_installationer_Villkor_Nordland_VVS.pdf":
        ("vvs_installation", "VVS installation terms", ["booking", "quote", "consumer_rights"]),
    "Villkor_entrepenad_for_gravarbeten-2024.pdf":
        ("groundwork", "Groundwork / excavation terms", ["quote", "booking"]),
    "varmepump_-_vatska_vatten_-_villa_villkor_version_2_Nordland_VVS.pdf":
        ("heatpump_brine", "Heat pump brine-water villa terms",
         ["booking", "quote", "maintenance", "consumer_rights"]),
    "villkor_brunnsborrning_for_energibrunn_2024.pdf":
        ("well_drilling", "Energy well drilling terms", ["quote", "booking"]),
}


def token_of(filename: str) -> str:
    t = re.sub(r"\.pdf$", "", filename, flags=re.I)
    t = re.sub(r"^Anvandarmanual_", "", t)
    t = re.sub(r"\s*\(\d+\)$", "", t)   # strip " (1)" dedup suffix
    t = re.sub(r"-\d+$", "", t)         # strip "-1" dedup suffix
    return t.strip()


def _spaced(token: str) -> str:
    s = token.replace("_", " ")
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", s)  # Geo600C -> Geo 600C
    return re.sub(r"\s+", " ", s).strip()


def _al(*xs) -> list[str]:
    seen, out = set(), []
    for x in xs:
        x = (x or "").strip().lower()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def classify(token: str) -> tuple[str, str, str, list[str]]:
    """token -> (category_slug, model_name, machine_slug, aliases). Groups variants."""
    low = token.lower()
    if low.startswith("airx400"):
        return "air_to_water", "AirX 400/400S", "airx-400-400s", _al("airx400", "airx 400", "airx400s", "airx 400s", "air x 400")
    if low.startswith("airx500"):
        return "air_to_water", "AirX 500", "airx-500", _al("airx500", "airx 500", "air x 500")
    if low.startswith("nordicinverter"):
        suf = token[len("NordicInverter"):].lstrip("_")
        suf_disp = suf.replace("_", " / ")
        name = f"NordicInverter {suf_disp}"
        al = ["nordicinverter", "nordic inverter " + suf_disp.lower(), suf.lower(), suf.lower().replace("-", "")]
        for piece in suf_disp.lower().split(" / "):
            al += [piece.strip(), piece.strip().replace("-", "")]
        return "air_to_air", name, "nordicinverter-" + _slug(suf), _al(*al)
    if low.startswith("aero"):
        if "fjarr" in low:
            return "air_to_air", "Aero Fjärrkontroll (remote)", "aero-fjarrkontroll", _al("aero fjarrkontroll", "aero remote", "fjarrkontroll")
        n = _spaced(token)
        return "air_to_air", n, _slug(n), _al(low, n.lower())
    if low.startswith("geo"):
        n = _spaced(token)
        return "water_to_water", n, _slug(n), _al(low, n.lower(), low.replace("geo", ""))
    if low.startswith("greenline"):
        suf = token[len("Greenline"):]
        return "water_to_water", f"Greenline {suf}", "greenline-" + _slug(suf), _al("greenline " + suf.lower(), suf.lower(), "greenline")
    if low.startswith("premiumline"):
        suf = token[len("PremiumLine"):]
        return "water_to_water", f"PremiumLine {suf}", "premiumline-" + _slug(suf), _al("premiumline " + suf.lower(), "premium line " + suf.lower(), suf.lower())
    if low.startswith("vent"):
        n = _spaced(token)
        return "exhaust_air", n, _slug(n), _al(low, n.lower())
    n = _spaced(token)
    return "heat_pump", n, _slug(n), _al(low)


def plan_machines(filenames: list[str]) -> dict[str, dict]:
    """Map a list of manual filenames to Machine rows (slug -> spec + source files).
    Pure function for testing — no DB."""
    machines: dict[str, dict] = {}
    for fn in filenames:
        cat, name, slug, aliases = classify(token_of(fn))
        m = machines.setdefault(slug, {"model_name": name, "category": cat, "aliases": set(), "files": []})
        m["aliases"].update(aliases)
        m["files"].append(fn)
    return machines


class Command(BaseCommand):
    help = "Import the IVT manuals (+ optional terms) into the knowledge base."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        parser.add_argument("--vendor", default="IVT")
        parser.add_argument("--lang", default="sv")
        parser.add_argument("--include-terms", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        src = Path(opts["source"])
        manuals = src / MANUALS_DIR
        files = sorted(f for f in os.listdir(manuals) if f.lower().endswith(".pdf")) if manuals.exists() else []
        plan = plan_machines(files)

        if opts["dry_run"]:
            self.stdout.write(f"DRY RUN — {len(files)} files -> {len(plan)} machines:")
            for slug, m in sorted(plan.items()):
                self.stdout.write(f"  [{m['category']}] {m['model_name']}  ({slug})  <- {len(m['files'])} file(s)")
            if opts["include_terms"]:
                self.stdout.write(f"  + {len(TERMS_MAP)} terms documents")
            return

        cats = {}
        for slug, (name, parent) in CATEGORIES.items():
            cats[slug], _ = Category.objects.get_or_create(
                slug=slug, defaults={"name": name, "parent": cats.get(parent) if parent else None})
        vendor, _ = Vendor.objects.get_or_create(
            slug=opts["vendor"].lower(), defaults={"name": opts["vendor"]})

        n_mach = n_doc = n_skip = 0
        for slug, m in plan.items():
            machine, created = Machine.objects.update_or_create(
                vendor=vendor, model_name=m["model_name"],
                defaults={"category": cats[m["category"]], "aliases": sorted(m["aliases"]), "slug": slug})
            n_mach += 1 if created else 0
            for fn in m["files"]:
                path = manuals / fn
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                if MachineDocument.objects.filter(sha256=sha).exists():
                    n_skip += 1
                    continue
                text = _parse_pdf_text(str(path))
                doc = MachineDocument(machine=machine, lang=opts["lang"], kind="manual",
                                      parsed_text=text, token_estimate=max(len(text) // 4, 0), sha256=sha)
                with path.open("rb") as fh:
                    doc.pdf.save(fn, File(fh), save=True)
                n_doc += 1

        n_terms = 0
        if opts["include_terms"]:
            tdir = src / TERMS_DIR
            for fn, (kind, title, cite_on) in TERMS_MAP.items():
                path = tdir / fn
                if not path.exists():
                    continue
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                if PolicyDocument.objects.filter(sha256=sha).exists():
                    continue
                text = _parse_pdf_text(str(path))
                pd = PolicyDocument(kind=kind, title=title, lang="sv", parsed_text=text,
                                    token_estimate=max(len(text) // 4, 0), sha256=sha, cite_on=cite_on)
                with path.open("rb") as fh:
                    pd.pdf.save(fn, File(fh), save=True)
                n_terms += 1

        self.stdout.write(self.style.SUCCESS(
            f"Imported: {len(plan)} machines ({n_mach} new), {n_doc} docs ({n_skip} skipped), {n_terms} terms."))
