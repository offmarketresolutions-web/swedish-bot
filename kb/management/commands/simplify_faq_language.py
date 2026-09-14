"""Rewrite FAQ answers into plain, easy Swedish — without changing what they say.

The imported corpus reads like officialese: 76 of the 102 pending answers contain a
14-character-plus compound ("garanti- och reklamationsbedömning", "installationer"), and
the worst run to 23 words in a sentence. A customer with no heating should not have to
parse that.

    python manage.py simplify_faq_language --dry-run          # show before/after, write nothing
    python manage.py simplify_faq_language --limit 5          # do five, review, continue
    python manage.py simplify_faq_language                    # all pending

SAFETY. These answers tell people what they may and may not touch, so a rewrite that
changes what they SAY is worse than a hard sentence. check_rewrite() is the gate; the
original is kept whenever any of these fails:

  * the opening verdict. A production run turned "Ja. Kontrollera att den inte står i
    AUTO…" into "Nej. Kontrollera…" — every other check passed, because the restriction
    count was identical. For a yes/no answer that first word IS the answer.
  * the restrictions. At least as many prohibitions as the original ("endast", "inte",
    "låt en tekniker") — that is where "only if the manual describes it" lives.
  * the numbers. Every temperature, pressure, wait time and code in the original must
    still be there, and none invented.
  * the length, both ways. Much longer means invented steps; much shorter means dropped
    ones (the prompt forbids both, and nothing used to verify the second).
  * professional-only work. The rewrite may repeat what the original said about a safety
    valve or a service menu; it may never introduce one.
  * the deterministic forbidden-term scan (chat.guardrails).

None of this makes an LLM rewrite safe to ship unread — it makes the failures that have
actually happened impossible to store silently. Answers that are already plain are skipped,
so re-running is idempotent: without that the command had no memory of its own work and a
second pass rewrote 78 answers it had already simplified, each a rewrite of a rewrite.

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


# An answer that opens with a verdict is answering a yes/no question, and that first word
# IS the answer. A live run on production turned "Ja. Kontrollera att den inte står i AUTO…"
# into "Nej. Kontrollera att den inte står i…" — the restriction count was identical, every
# other check passed, and the answer now said the opposite thing.
_VERDICT = re.compile(r"^\W*(ja|nej|yes|no)\b", re.I)


def verdict(text: str) -> str | None:
    m = _VERDICT.match(text or "")
    return m.group(1).lower() if m else None


_SENTENCE_END = re.compile(r"[.!?\n]")


def max_sentence_words(text: str) -> int:
    return max((len(s.split()) for s in _SENTENCE_END.split(text or "") if s.strip()),
               default=0)


def needs_simplifying(text: str) -> bool:
    """Is this still officialese? A 14+ character compound, or a sentence over 18 words.

    Without this the command has no memory of its own work: every run re-simplified text it
    had already simplified, so a second pass rewrote 78 answers that were already plain —
    each one a rewrite of a rewrite rather than of the original.
    """
    # A higher bar than the >13 used for before/after reporting. Swedish is built on
    # compounds — "fjärrkontrollen" is 15 characters of everyday vocabulary, and flagging
    # that would send almost every already-plain answer back through the model.
    # "reklamationsbedömning" (21) is the kind of word this is actually looking for.
    return bool(long_words(text, over=16)) or max_sentence_words(text) > 18


def long_words(text: str, over: int = 13) -> int:
    return sum(1 for w in (text or "").split() if len(w.strip(".,;:()")) > over)


# Every number the original states is load-bearing: a temperature, a pressure, a wait time,
# an error code. "sänk till 21 grader" must not come back as "sänk till 12 grader", and a
# number that was never in the original must not appear. Presence, not count, so a rewrite
# is free to repeat one.
_NUMBER = re.compile(r"\d+")


def numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text or ""))


def check_rewrite(original: str, rewritten: str) -> str | None:
    """Return a reason to REJECT the rewrite, or None when it is safe to store."""
    if not rewritten or len(rewritten) < 20:
        return "empty or truncated"
    before_v, after_v = verdict(original), verdict(rewritten)
    if before_v != after_v:
        return f"the answer's verdict changed: {before_v or 'none'} -> {after_v or 'none'}"
    before, after = qualifiers(original), qualifiers(rewritten)
    if after < before:
        return f"weaker than the original — {before} restriction(s) became {after}"
    if len(rewritten.split()) > len(original.split()) * 1.6 + 10:
        return "much longer than the original — likely added content"
    # The prompt says "never remove a step", but nothing verified it: the length check only
    # ever looked at growth, so a rewrite that quietly dropped half the instructions passed.
    if len(rewritten.split()) < len(original.split()) * 0.5:
        return "much shorter than the original — likely dropped a step"
    dropped = numbers(original) - numbers(rewritten)
    if dropped:
        return f"dropped number(s) the original stated: {', '.join(sorted(dropped))}"
    invented = numbers(rewritten) - numbers(original)
    if invented:
        return f"invented number(s) not in the original: {', '.join(sorted(invented))}"
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

        already_simple = [t for t in targets if not needs_simplifying(t[2])]
        targets = [t for t in targets if needs_simplifying(t[2])]
        if opts["limit"]:
            targets = targets[:opts["limit"]]
        self.stdout.write(f"Rewriting {len(targets)} answer(s)"
                          + (" — DRY RUN, nothing is written" if opts["dry_run"] else ""))

        rewritten = refused = 0
        unchanged = len(already_simple)
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
                if opts["dry_run"]:
                    # Show the rejected text too: "kept original" alone gives no way to tell
                    # a gate that is protecting a customer from one that is too strict.
                    self.stdout.write(f"    REJECTED ({len(original.split())} -> "
                                      f"{len(new.split())} words): {new[:400]}")
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
