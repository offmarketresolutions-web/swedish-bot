"""Populate kb.Embedding for every role declared IN (kb.corpus.ROLE_CORPUS) —
idempotent + incremental: a row is only (re-)embedded when its text actually
changed (content_hash mismatch) or --force is given.

    python manage.py build_embeddings                # all included roles
    python manage.py build_embeddings --scope heat_pump_specialist
    python manage.py build_embeddings --force         # re-embed everything

Uses RETRIEVAL_DOCUMENT task_type (corpus side of the asymmetry; queries embed
with RETRIEVAL_QUERY at request time in kb/semantic.py). Safe to run on every
deploy; wire into post_deploy once a schedule for it exists.
"""
from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand

from core.services import gemini
from kb import corpus
from kb.models import Embedding


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Command(BaseCommand):
    help = "Embed registry-declared (kb.corpus) rows into kb.Embedding, incrementally."

    def add_arguments(self, parser):
        parser.add_argument("--scope", default=None,
                             help="Only this role (must be an included ROLE_CORPUS entry). "
                                  "Default: every included role.")
        parser.add_argument("--force", action="store_true",
                             help="Re-embed every row even if its content_hash is unchanged.")

    def handle(self, *args, **opts):
        force = opts["force"]
        requested = opts["scope"]
        roles = [requested] if requested else [
            r for r, s in corpus.ROLE_CORPUS.items() if s.included
        ]

        total_new, total_unchanged, total_roles = 0, 0, 0
        for role in roles:
            scope = corpus.get_corpus_for_role(role)
            if not scope.included:
                self.stdout.write(self.style.WARNING(f"{role}: excluded ({scope.reason}); skipped"))
                continue
            rows = list(corpus.embeddable_rows(role))
            if not rows:
                self.stdout.write(f"{role}: 0 embeddable rows")
                total_roles += 1
                continue

            existing = {
                (e.source_model, e.object_id, e.lang): e
                for e in Embedding.objects.filter(scope=role)
            }
            to_embed = []  # (source_model, pk, lang, text, hash)
            for source_model, pk, lang, text in rows:
                h = _hash(text)
                cur = existing.get((source_model, pk, lang))
                if not force and cur is not None and cur.content_hash == h:
                    total_unchanged += 1
                    continue
                to_embed.append((source_model, pk, lang, text, h))

            if to_embed:
                vecs = gemini.embed(
                    [t for *_, t, _h in to_embed], task_type="RETRIEVAL_DOCUMENT")
                model_name = gemini.active_embedding_model()
                for (source_model, pk, lang, _text, h), vec in zip(to_embed, vecs):
                    Embedding.objects.update_or_create(
                        source_model=source_model, object_id=pk, lang=lang, scope=role,
                        defaults={"content_hash": h, "vector": vec, "model_name": model_name},
                    )
            total_new += len(to_embed)
            total_roles += 1
            self.stdout.write(
                f"{role}: {len(to_embed)} embedded, {len(rows) - len(to_embed)} unchanged "
                f"(of {len(rows)} declared rows)")

        self.stdout.write(self.style.SUCCESS(
            f"build_embeddings complete: {total_roles} role(s), {total_new} embedded, "
            f"{total_unchanged} unchanged."))
