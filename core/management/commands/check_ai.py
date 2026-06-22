"""Live check that the Gemini LLM + embedding engine are configured and reachable.

    python manage.py check_ai

Does one real generation call and one real embedding call (multilingual sv↔en
similarity) so a green run proves the whole AI stack is wired end-to-end.
"""
from django.core.management.base import BaseCommand

from core import constants
from core.services import gemini


class Command(BaseCommand):
    help = "Live verify Gemini LLM generation + embedding engine."

    def handle(self, *args, **opts):
        h = gemini.health_check()
        self.stdout.write(
            f"Auth: mode={h['mode']} ready={h['ready']} "
            f"project={h['project']} location={h['location']}")
        if not h["ready"]:
            self.stderr.write(self.style.ERROR(f"Gemini not ready: {h['reason']}"))
            return

        # 1) LLM
        r = gemini.generate("Reply with the single word: OK",
                            model=constants.MODELS["flash_lite"],
                            max_output_tokens=10, temperature=0)
        self.stdout.write(self.style.SUCCESS(
            f"LLM   {r.model}: {r.text!r} (in={r.prompt_tokens} out={r.completion_tokens} "
            f"${r.cost_usd:.6f})"))

        # 2) Embedding engine (prove multilingual: Swedish ↔ English should be close)
        sv = "IVT Geo 600C värmepump ger ingen värme"
        en = "the IVT Geo 600C heat pump gives no heat"
        un = "how to bake sourdough bread at home"
        vs = gemini.embed([sv, en, un], task_type="RETRIEVAL_DOCUMENT")
        sim = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731 (vectors are L2-normalized)
        pref, active = constants.MODELS["embedding"], gemini.active_embedding_model()
        tag = active if active == pref else f"{active} (fallback from {pref})"
        self.stdout.write(self.style.SUCCESS(
            f"EMBED {tag}: dim={len(vs[0])}  "
            f"sv↔en={sim(vs[0], vs[1]):.3f}  sv↔unrelated={sim(vs[0], vs[2]):.3f}"))
        self.stdout.write(self.style.SUCCESS("AI stack OK — LLM + embedding engine reachable."))
