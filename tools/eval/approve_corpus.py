"""Approve the FAQ/knowledge corpus in the EVAL database only.

The Bobby spec (§5) requires general-knowledge retrieval over *approved* entries to
run before manual-level troubleshooting. Every eval so far exercised an unapproved
(hence empty-to-retrieval) corpus, leaving general mode unvalidated. Production
approval stays the owner's dashboard action — this script refuses to run against
any DB not named eval_*.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("POSTGRES_DB", "eval_nordland")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

db = os.environ["POSTGRES_DB"]
if not db.startswith("eval_"):
    sys.exit(f"Refusing: POSTGRES_DB={db!r} is not an eval database.")

import django  # noqa: E402

django.setup()

from kb.models import FAQEntry, SiteFAQ  # noqa: E402

a = FAQEntry.objects.filter(is_approved=False).update(is_approved=True)
b = SiteFAQ.objects.filter(is_approved=False).update(is_approved=True)
print(f"[{db}] approved: FAQEntry +{a} (now "
      f"{FAQEntry.objects.filter(is_approved=True).count()}/{FAQEntry.objects.count()}), "
      f"SiteFAQ +{b} (now "
      f"{SiteFAQ.objects.filter(is_approved=True).count()}/{SiteFAQ.objects.count()})")
