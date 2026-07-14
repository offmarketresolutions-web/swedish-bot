"""Post-deploy health check — verifies the DB + static assets are in the state a
live deploy needs, and prints a PASS/FAIL/WARN table. Exits 1 on any FAIL.

FAIL = would break the bot in production (missing migration, missing prompt,
no vendor/machine, no static widget file).
WARN = owner go-live item, not a code defect (GeoSettings/ServiceArea, FormButton,
unapproved FAQ backlog) — doesn't fail the command, just flags it.

    python manage.py selfcheck
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.migrations.executor import MigrationExecutor
from django.db import connections

from core.enums import AGENT_ROLE_CHOICES


class Command(BaseCommand):
    help = "Verify the deploy is in a servable state; prints a PASS/FAIL/WARN table (exit 1 on FAIL)."

    def handle(self, *args, **opts):
        rows: list[tuple[str, str, str]] = []  # (check, status, detail)
        failed = False

        def check(name: str, ok: bool, detail: str = "", warn_only: bool = False):
            nonlocal failed
            if ok:
                status = "PASS"
            elif warn_only:
                status = "WARN"
            else:
                status = "FAIL"
                failed = True
            rows.append((name, status, detail))

        # 1. Pending migrations.
        conn = connections["default"]
        executor = MigrationExecutor(conn)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        check("migrations applied", not plan,
              "no pending migrations" if not plan
              else f"{len(plan)} pending: " + ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan[:5]))

        # 2. AgentPrompt rows for every AGENT_ROLE choice, non-empty body.
        from kb.models import AgentPrompt
        roles = [r for r, _ in AGENT_ROLE_CHOICES]
        prompts = {p.role: p for p in AgentPrompt.objects.filter(role__in=roles)}
        missing = [r for r in roles if r not in prompts]
        blank = [r for r, p in prompts.items() if not p.body.strip()]
        check("AgentPrompt rows (all roles, non-empty body)",
              not missing and not blank,
              (f"missing: {', '.join(missing)}. " if missing else "")
              + (f"blank body: {', '.join(blank)}." if blank else "")
              or f"{len(prompts)}/{len(roles)} roles present")

        # 3. At least one active Vendor/Machine.
        from kb.models import Vendor, Machine
        n_vendor = Vendor.objects.filter(is_active=True).count()
        n_machine = Machine.objects.filter(is_supported=True).count()
        check("active Vendor + Machine present", n_vendor > 0 and n_machine > 0,
              f"{n_vendor} active vendors, {n_machine} supported machines")

        # 4. FAQEntry corpus counts (approved vs pending) — informational, never fails.
        from kb.models import FAQEntry
        n_approved = FAQEntry.objects.filter(is_approved=True).count()
        n_pending = FAQEntry.objects.filter(is_approved=False).count()
        check("FAQEntry corpus", True, f"{n_approved} approved, {n_pending} pending owner review")

        # 5. GeoSettings + ServiceArea state — WARN, owner go-live item.
        from crm.models import GeoSettings, ServiceArea
        geo = GeoSettings.load()
        n_areas = ServiceArea.objects.count()
        check("GeoSettings / ServiceArea configured", geo.enabled and n_areas > 0,
              f"GeoSettings.enabled={geo.enabled}, {n_areas} ServiceArea rows "
              "(owner enables in dashboard once polygons are reviewed)", warn_only=True)

        # 6. FormButton rows present/active — WARN, owner go-live item.
        from crm.models import FormButton
        n_buttons = FormButton.objects.filter(is_active=True).count()
        n_expected = len(FormButton.CATEGORY)
        check("FormButton rows present/active", n_buttons >= n_expected,
              f"{n_buttons}/{n_expected} active (owner fills real URLs in dashboard)",
              warn_only=True)

        # 7. PostcodeArea count.
        from crm.models import PostcodeArea
        n_postcodes = PostcodeArea.objects.count()
        check("PostcodeArea loaded", n_postcodes > 0,
              f"{n_postcodes} rows (import_postcodes SE.zip if 0)")

        # 8. Static widget file exists.
        widget_path = settings.BASE_DIR / "static" / "widget" / "nordland-widget.js"
        check("static widget file exists", widget_path.exists(), str(widget_path))

        # ── Print table ──
        w1 = max(len(r[0]) for r in rows) + 2
        w2 = 8
        self.stdout.write(f"{'CHECK'.ljust(w1)}{'STATUS'.ljust(w2)}DETAIL")
        self.stdout.write("-" * (w1 + w2 + 40))
        for name, status, detail in rows:
            style = self.style.SUCCESS if status == "PASS" else (
                self.style.WARNING if status == "WARN" else self.style.ERROR)
            self.stdout.write(f"{name.ljust(w1)}{style(status.ljust(w2))}{detail}")

        n_fail = sum(1 for _, s, _ in rows if s == "FAIL")
        n_warn = sum(1 for _, s, _ in rows if s == "WARN")
        self.stdout.write("")
        summary = f"{len(rows) - n_fail - n_warn} pass, {n_warn} warn, {n_fail} fail"
        if failed:
            self.stdout.write(self.style.ERROR(f"selfcheck FAILED ({summary})"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"selfcheck PASSED ({summary})"))
