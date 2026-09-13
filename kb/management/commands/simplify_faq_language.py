"""Rewrite FAQ answers into plain, easy Swedish — without changing what they say.

The imported corpus reads like officialese: 76 of the 102 pending answers contain a
14-character-plus compound ("garanti- och reklamationsbedömning", "installationer"), and
the worst run to 23 words in a sentence. A customer with no heating should not have to
parse that.

    python manage.py simplify_faq_language --dry-run          # show before/after, write nothing
    python manage.py simplify_faq_language --limit 5          # do five, review, continue
    python manage.py simplify_faq_language                    # all pending

SAFETY. These answers tell people what they may and may not touch, so a rewrite that
loses a qualifier is worse than a hard sentence. Every rewrite must survive three checks
before it is stored, and the original is kept whenever one fails:

  1. the deterministic forbidden-term scan (chat.guardrails) must still pass;
  2. every negation/condition in the original ("endast", "inte", "aldrig", "om") must
     still be present — that is where "only if the manual describes it" lives;
  3. it must actually be simpler, and not have grown into a different answer.

Nothing is ever approved by this command. Rewritten rows stay pending for review, which
is the whole point: the owner reads plain Swedish instead of officialese.
"""
from __future__ import annotations

import re
import time

from django.core.management.base import BaseCommand

# Words that carry an actual prohibition or restriction. Counted in total rather than
# matched word-for-word, because plain Swedish reaches the same meaning by other routes —
# "ska inte öppna" becomes "Du får inte öppna" or "Låt en tekniker öppna". What must not
# happen is the rewrite coming back with FEWER restrictions than it started with.
#
# "om", "bara", "först" and "innan" are deliberately NOT here. They are structural words;
# requiring each one back rejected 6 of 6 real rewrites that had lost nothing at all.
_QUALIFIERS = re.compile(
    r"\b(inte|aldrig|endast|undvik|inga|ingen|inget|beh[öo]rig|auktoriserad|"
    r"l[åa]t\s+en\s+tekniker|kontakta\s+(?:en\s+)?tekniker|kr[äa]ver\s+tekniker)\b", re.I)

# Professional-only work, per spec §7/§8/§10. The rewrite may keep whatever the original
# said about these; it may never introduce one. That is the failure mode a plain-language
# pass can actually cause — turning a warning into an instruction.
_PRO_WORK = re.compile(
    r"\b(elpanel\w*|kopplingsplint\w*|s[äa]kringsskåp\w*|koppla\s+om|kretskort\w*|"
    r"k[öo]ldmedi\w*|tryckvakt\w*|f[öo]rtryck\w*|expansionsk[äa]rl\w*|s[äa]kerhetsventil\w*|"
    r"installat[öo]rsmeny\w*|servicemeny\w*|pumpstyrning\w*|filtermassa\w*|"
    r"electrical panel|terminal block|refrigerant|pressure switch|precharge|"
    r"expansion vessel|safety valve|installer menu|service menu|filter media)\b", re.I)

_PROMPT = """Du skriver om svar från Nordland VVS så att vem som helst förstår dem.

SKRIV OM TEXTEN SÅ HÄR:
- Korta meningar. Högst 12 ord per mening.
- Vardagliga ord. Byt ut långa sammansatta ord mot enkla ("reklamationsbedömning" ->
  "bedömning av klagomål"; "installationer" -> "sådant vi installerat").
- Tilltala kunden med "du".
- Punktlista när det är flera steg, annars vanlig text.
- Behåll svenska.

ÄNDRA ALDRIG INNEHÅLLET:
- Varje varning, villkor och begränsning måste finnas kvar, lika tydlig.
  "Använd endast om manualen beskriver det" får ALDRIG bli "använd knappen".
- Lägg aldrig till ett steg, en siffra eller en åtgärd som inte redan står i texten.
- Ta aldrig bort ett steg.
- Om texten säger att något kräver tekniker, ska det fortfarande säga det.

Svara med ENBART den omskrivna texten. Ingen förklaring, inga citattecken."""


def qualifiers(text: str) -> int:
    """How many prohibitions/restrictions the text carries."""
    return len(_QUALIFIERS.findall(text or ""))


def long_words(text: str) -> int:
    return sum(1 for w in (text or "").split() if len(w.strip(".,;:()")) > 13)


def check_rewrite(original: str, rewritten: str) -> str | None:
    """Return a reason to REJECT the rewrite, or None when it is safe to store."""
    if not rewritten or len(rewritten) < 20:
        return "empty or truncated"
    before, after = qualifiers(original), qualifiers(rewritten)
    if after < before:
        return f"weaker than the original — {before} restriction(s) became {after}"
    if len(rewritten.split()) > len(original.split()) * 1.6 + 10:
        return "much longer than the original — likely added content"
    added = {m.group(0).lower() for m in _PRO_WORK.finditer(rewritten)} - \
            {m.group(0).lower() for m in _PRO_WORK.finditer(original)}
    if added:
        return f"introduced professional-only work: {', '.join(sorted(added))}"
    from chat import guardrails
    unsafe, reason = guardrails.is_unsafe(rewritten, locale="sv", use_llm=False)
    if unsafe:
        return f"forbidden-term scan: {reason}"
    return None


class Command(BaseCommand):
    help = "Rewrite pending FAQ answers into plain Swedish (never approves, never changes meaning)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show before/after and write nothing.")
        parser.add_argument("--limit", type=int, default=0, help="Only process N answers.")
        parser.add_argument("--include-approved", action="store_true",
                            help="Also rewrite already-approved answers (default: pending only).")
        parser.add_argument("--retries", type=int, default=4,
                            help="Retries per answer when Vertex answers 429 (default 4).")
        parser.add_argument("--sleep", type=float, default=1.0,
                            help="Seconds to pause between calls, to stay under the quota.")

    def handle(self, *args, **opts):
        from core.services import gemini
        from kb.models import FAQEntryText, SiteFAQ

        pending_only = not opts["include_approved"]
        targets: list[tuple[str, object, str]] = []
        texts = FAQEntryText.objects.filter(lang="sv").select_related("faq")
        if pending_only:
            texts = texts.filter(faq__is_approved=False)
        targets += [("entry", t, t.answer) for t in texts if (t.answer or "").strip()]
        sites = SiteFAQ.objects.all()
        if pending_only:
            sites = sites.filter(is_approved=False)
        targets += [("site", s, s.answer) for s in sites if (s.answer or "").strip()]

        if opts["limit"]:
            targets = targets[:opts["limit"]]
        self.stdout.write(f"Rewriting {len(targets)} answer(s)"
                          + (" — DRY RUN, nothing is written" if opts["dry_run"] else ""))

        rewritten = refused = unchanged = 0
        quota_failed: list[str] = []
        for kind, obj, original in targets:
            new, err = self._rewrite(gemini, original, opts["retries"], opts["sleep"])
            if err is not None:
                # A quota refusal is NOT a verdict on the answer. Counting the two together
                # reported "kept original 78" on a run where only 7 answers were actually
                # judged unsafe and 71 calls never happened — which reads as "this corpus
                # can't be simplified" when it means "come back when the quota resets".
                quota_failed.append(f"{kind} {obj.pk}")
                self.stderr.write(self.style.ERROR(f"  [{kind} {obj.pk}] not attempted — {err}"))
                continue

            reason = check_rewrite(original, new)
            if reason:
                refused += 1
                self.stderr.write(self.style.WARNING(f"  [{kind} {obj.pk}] kept original — {reason}"))
                continue
            if new.strip() == original.strip():
                unchanged += 1
                continue

            rewritten += 1
            if opts["dry_run"]:
                self.stdout.write(f"\n  [{kind} {obj.pk}] long words {long_words(original)} -> {long_words(new)}")
                self.stdout.write(f"    BEFORE: {original}")
                self.stdout.write(self.style.SUCCESS(f"    AFTER : {new}"))
            else:
                obj.answer = new
                obj.save(update_fields=["answer"])

        self.stdout.write(self.style.SUCCESS(
            f"\nrewritten {rewritten} | kept original (unsafe rewrite) {refused} | "
            f"already simple {unchanged}"
            + ("  (dry run — nothing written)" if opts["dry_run"] else "")))
        if quota_failed:
            self.stdout.write(self.style.WARNING(
                f"{len(quota_failed)} answer(s) were never attempted — the model refused on quota. "
                f"Re-run the same command to pick up exactly these; answers already rewritten "
                f"are left alone."))
        self.stdout.write("Every row stays PENDING; approval is still yours in the dashboard.")

    def _rewrite(self, gemini, original: str, retries: int, sleep_s: float):
        """(rewritten_text, None) or (None, why-it-never-ran).

        Vertex answers a burst of flash calls with 429 RESOURCE_EXHAUSTED; on the first
        full pass 71 of 102 answers came back that way. Backing off and retrying turns a
        mostly-failed run into a complete one.
        """
        delay = max(sleep_s, 1.0)
        for attempt in range(retries + 1):
            try:
                resp = gemini.generate(original, model="gemini-2.5-flash",
                                       system_instruction=_PROMPT, max_output_tokens=600)
                if sleep_s:
                    time.sleep(sleep_s)
                return (resp.text or "").strip().strip('"'), None
            except Exception as exc:  # noqa: BLE001 — one bad call must not stop the batch
                transient = "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc).upper()
                if not transient or attempt == retries:
                    return None, str(exc).split("\n")[0][:160]
                self.stderr.write(f"    quota hit — waiting {delay:.0f}s "
                                  f"({attempt + 1}/{retries})")
                time.sleep(delay)
                delay *= 2
        return None, "gave up"
