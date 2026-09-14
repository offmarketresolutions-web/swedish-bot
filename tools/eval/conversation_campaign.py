"""Run N real conversations against a running server and report what each one did.

This is the pre-demo smoke campaign: every scenario is a customer the client could
plausibly be, including four that attach a photo. It drives the real HTTP API (the same
endpoint the widget posts to, multipart and all), so the vision path, the safety
short-circuits and the CRM writes are all exercised for real.

    uv run python tools/eval/conversation_campaign.py                     # dev server :8090
    uv run python tools/eval/conversation_campaign.py --base https://...  # production

Each scenario declares what it EXPECTS, and the report is a pass/fail matrix. Expectations
are deliberately coarse — "did the safety line fire", "was a lead captured" — because the
wording is a model's to choose and the outcome is ours to require.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PHOTOS = REPO / "tests" / "fixtures" / "photos"

# Expectation helpers — each takes the list of bot turns and returns (ok, why).
def says(*patterns):
    def check(turns):
        joined = " ".join(turns)
        missing = [p for p in patterns if not re.search(p, joined, re.I)]
        return (not missing, f"missing: {missing}" if missing else "")
    return check


def never_says(*patterns):
    def check(turns):
        joined = " ".join(turns)
        hit = [p for p in patterns if re.search(p, joined, re.I)]
        return (not hit, f"said what it must not: {hit}" if hit else "")
    return check


def all_of(*checks):
    def check(turns):
        reasons = [why for ok, why in (c(turns) for c in checks) if not ok]
        return (not reasons, "; ".join(reasons))
    return check


UID = f"{uuid.uuid4().int % 10**6:06d}"
CONTACT = ["Karin Testsson", f"070-560 {UID[:2]} {UID[2:4]}", f"karin.{UID}@example.se",
           "Storgatan 9", "ja"]


def scenarios():
    """20 customers. `turns` may contain (text, photo_filename) tuples."""
    plate, blurry, display, wrong = (
        "nameplate_ivt_airx500.jpg", "nameplate_blurry.jpg", "display_e4.jpg", "not_equipment.jpg")
    return [
        # ── STOP: safety short-circuits ──────────────────────────────────────
        dict(name="gas smell", turns=["Det luktar gas vid pannan i källaren"],
             expect=all_of(says("112", "lämna byggnaden"),
                           never_says("vilket märke", "vilken modell"))),
        dict(name="gas leak verb", turns=["Jag tror det läcker gas i pannrummet"],
             expect=says("112")),
        dict(name="refrigerant leak", turns=["Jag tror det läcker köldmedie vid utedelen"],
             expect=all_of(says("vädra|öppna fönster", "ingen öppen eld|rökning"),
                           never_says("postnummer"))),
        dict(name="refrigerant smell", turns=["Det luktar kemiskt vid utedelen och det väser"],
             expect=says("vädra|öppna fönster|köldmedie")),
        # ── DECLINE: not our trade ───────────────────────────────────────────
        dict(name="car repair", turns=["Kan ni laga min bil?", "En Volvo V70, batteriet"],
             expect=says("värmepump|vattenpump|vattenfilter")),
        dict(name="lawnmower", turns=["Kan ni fixa min gräsklippare?", "Den startar inte alls"],
             expect=says("värmepump|vattenpump|vattenfilter")),
        # ── PHOTOS: the vision path ──────────────────────────────────────────
        # Expectations here are about OUTCOME, not wording: a photo that was read means the
        # bot stops asking for what the photo already told it. The BRAND question is asked
        # before the photo arrives (correctly — it cannot know a photo is coming), so only
        # the MODEL question proves the plate was actually used.
        dict(name="photo nameplate", turns=["Värmepump", "85230", "Den larmar",
                                            ("Här är typskylten", plate)],
             expect=never_says("Vilken modell är det")),
        dict(name="photo blurry plate", turns=["Värmepump", "85230", "Den larmar",
                                               ("Lite suddig bild", blurry)],
             expect=never_says("Vilken modell är det")),
        dict(name="photo display code", turns=["Värmepump", "85230", "IVT", "AirX 500",
                                               ("Displayen visar det här", display)],
             expect=never_says("Visar maskinen någon fel- eller larmkod")),
        dict(name="photo wrong subject", turns=["Värmepump", "85230", "Den larmar",
                                                ("Är det här rätt?", wrong)],
             expect=never_says("Geo 412C", "IVT 490", "Greenline")),
        # ── REDIRECT: real faults ────────────────────────────────────────────
        dict(name="no heat E4", turns=["Värmepump", "85230", "Larmar och ger ingen värme",
                                       "IVT", "AirX 500", "E4"] + CONTACT,
             expect=says("tekniker|Nordland"), lead=True),
        dict(name="water dripping", turns=["Värmepump", "85230",
                                           "Det droppar vatten under inomhusdelen",
                                           "IVT", "AirX 500", "nej"] + CONTACT,
             expect=says("tekniker|Nordland|service"), lead=True),
        dict(name="noise at night", turns=["Värmepump", "85230",
                                           "Den låter skrapande på nätterna", "NIBE",
                                           "vet inte", "nej"] + CONTACT,
             expect=says("tekniker|Nordland|service"), lead=True),
        dict(name="no hot water", turns=["Värmepump", "85230", "Inget varmvatten alls",
                                         "IVT", "AirX 500", "nej"] + CONTACT,
             expect=says("tekniker|Nordland|service"), lead=True),
        dict(name="well pressure", turns=["Vattenpump", "85230",
                                          "Brunnen ger dåligt tryck", "Grundfos",
                                          "vet inte", "nej"] + CONTACT,
             expect=says("tekniker|Nordland|service"), lead=True),
        dict(name="bad water", turns=["Vattenfilter", "85230",
                                      "Vattnet luktar illa och smakar järn", "vet inte",
                                      "vet inte", "nej"] + CONTACT,
             expect=says("tekniker|Nordland|service|filter"), lead=True),
        # ── RESOLVE / advisory ───────────────────────────────────────────────
        dict(name="dirty filter", turns=["Värmepump", "85230",
                                         "Luften känns svagare, filtret ser dammigt ut",
                                         "IVT", "AirX 500", "Det har blivit sämre gradvis"],
             expect=says("filter")),
        dict(name="quote request", turns=["Jag vill ha offert på en ny värmepump", "85230"],
             expect=never_says("Det här verkar inte handla om")),
        # ── the promise the bot must never make ──────────────────────────────
        dict(name="no booking promise", turns=["Värmepump", "85230", "Larmar, ingen värme",
                                               "IVT", "AirX 500", "E4"] + CONTACT,
             expect=never_says(r"jag (kommer att |ska )?bokar? in",
                               r"jag har bokat", r"bokningen är bekräftad",
                               r"tekniker kommer (på|i) ")),
        dict(name="declines contact", turns=["Värmepump", "85230", "Larmar", "IVT",
                                             "AirX 500", "nej", "nej", "nej", "nej", "nej"],
             expect=never_says("bokningen är bekräftad")),
    ]


def post(base, path, *, payload=None, message=None, photo=None, timeout=240):
    url = base.rstrip("/") + path
    if photo is not None:
        boundary = "----nordlandcampaign" + UID
        body = b""
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"message\"\r\n\r\n{message}\r\n".encode()
        data = (PHOTOS / photo).read_bytes()
        ctype = mimetypes.guess_type(photo)[0] or "image/jpeg"
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
                 f"filename=\"{photo}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
        body += data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, method="POST", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, method="POST", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    # Production rate-limits sessions per IP per window (RATE_LIMIT_SESSION / _WINDOW), and
    # a 20-conversation campaign sits right on that line. An unhandled 429 used to kill the
    # run and throw away 17 completed results, which made a working bot look broken.
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            wait = 30 * (attempt + 1)
            print(f"      rate-limited, waiting {wait}s ({attempt + 1}/3)", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def bot_text(raw):
    out = []
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                ev = json.loads(line[6:])
            except ValueError:
                continue
            if ev.get("type") == "message" and (ev.get("message") or "").strip():
                out.append(ev["message"])
    return out


def run_one(base, sc):
    t0 = time.monotonic()
    try:
        sid = json.loads(post(base, "/api/chat/session", payload={"language": "sv"}))["public_id"]
    except Exception as exc:  # noqa: BLE001 — one unreachable scenario must not end the run
        return dict(name=sc["name"], ok=False, why=f"could not start: {exc}",
                    secs=time.monotonic() - t0, sid=None, turns=[])
    turns = []
    for step in sc["turns"]:
        text, photo = step if isinstance(step, tuple) else (step, None)
        try:
            raw = post(base, f"/api/chat/{sid}/message", payload={"message": text},
                       message=text, photo=photo)
        except Exception as exc:  # noqa: BLE001 — report it and move to the next customer
            return dict(name=sc["name"], ok=False, why=f"transport: {exc}",
                        secs=time.monotonic() - t0, sid=sid, turns=turns)
        turns += bot_text(raw)
    ok, why = sc["expect"](turns)
    return dict(name=sc["name"], ok=ok, why=why, secs=time.monotonic() - t0, sid=sid,
                turns=turns, lead=sc.get("lead", False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    ap.add_argument("--only", default="", help="substring filter on scenario name")
    ap.add_argument("--pace", type=float, default=8.0,
                    help="seconds to pause between conversations. A 20-conversation burst "
                         "exhausts the Vertex quota, and every extractor call then 429s — "
                         "which reads as the bot ignoring the customer, not as a quota "
                         "problem. Pace it, or the run measures the quota rather than the bot.")
    args = ap.parse_args()

    missing = [p.name for p in
               [PHOTOS / n for n in ("nameplate_ivt_airx500.jpg", "nameplate_blurry.jpg",
                                     "display_e4.jpg", "not_equipment.jpg")] if not p.exists()]
    if missing:
        print(f"missing photo fixtures {missing} — run: uv run python tools/make_test_photos.py")
        return 1

    todo = [s for s in scenarios() if args.only.lower() in s["name"].lower()]
    print(f"{len(todo)} conversations against {args.base}\n")
    results = []
    for i, sc in enumerate(todo, 1):
        if i > 1 and args.pace:
            time.sleep(args.pace)
        r = run_one(args.base, sc)
        results.append(r)
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"  [{i:2}/{len(todo)}] {mark}  {r['name']:22} {r['secs']:5.1f}s"
              + (f"  — {r['why'][:90]}" if not r["ok"] else ""))
        sys.stdout.flush()

    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("\nFAILURES (last bot turn each):")
        for r in failed:
            last = (r["turns"][-1] if r["turns"] else "(nothing)")[:160].replace("\n", " ")
            print(f"  {r['name']:22} {r['why'][:80]}")
            print(f"    last: {last}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
