"""Guardrail backstop tests (plan §6.4) + per-agent editable guardrails (add-only)."""
import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from chat import guardrails, prompts
from kb.models import AgentGuardrail

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def test_keyword_veto_catches_forbidden_classes():
    bad = [
        "You should rewire the compressor terminals",
        "Just top up the refrigerant yourself",
        "Open the electrical panel and replace the heating element",
        "You can re-pressurize the system to 1.5 bar",
        "Adjust the pressure switch a little",
        # electrical/control panel + deep disassembly — fail closed → escalate.
        "Unscrew the casing to reach the board",
        "Just open up the unit and have a look",
        "You can dismantle the housing yourself",
        "Remove the electrical panel first",
        "Take off the control panel to reach the board",
    ]
    for t in bad:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert unsafe, f"should be unsafe: {t!r}"
        assert hit


def test_keyword_allows_safe_envelope():
    ok = [
        "Note the alarm code shown on the display",
        "Check the breaker hasn't tripped — just look, don't touch",
        "Close the visible stop valve to limit the leak",
        "Make sure the isolation valve is open",   # operating a visible valve is allowed
        "Read the pressure gauge and tell me the number",
        # owner filter maintenance: removing a front cover/grille to reach the filter is OK
        # (the context-aware safety agent still catches 'open the cover to reach the board')
        "Open the front cover and pull out the filter to rinse it, then refit the cover",
        "Switch it off, take off the cover, clean the particle filter, and put it back",
        "Lift open the front panel and slide out the air filter to wash it",  # split-unit filter
    ]
    for t in ok:
        unsafe, _ = guardrails.keyword_unsafe(t)
        assert not unsafe, f"should be safe: {t!r}"


# ── S4 water-domain safety pairs (instruction blocked, mention survives) — en + sv ──

# Each pair: an INSTRUCTION to do the professional task (must veto) and a mention/observation
# of the same regulated thing (must survive to the LLM layer → keyword_unsafe False).
WATER_INSTRUCTION_EN = [
    "Adjust the pressure switch up to 3 bar",
    "Pull up the well pump and check the impeller",
    "Open the hydrofor and inspect the bladder",
    "Set the precharge to 1.5 bar on the pressure tank",
    "Replace the filter media in the softener",
    "Adjust the dosing pump to add more chemical",
    "Bypass the dry-run protection so it keeps running",
    "Enter the installer menu and change the limit",
]
WATER_INSTRUCTION_SV = [
    "Justera pressostaten till 3 bar",
    "Dra upp brunnspumpen och kolla pumphjulet",
    "Öppna hydroforen och titta på blåsan",
    "Ställ in förtrycket på tryckkärlet",
    "Byt filtermassan i avhärdaren",
    "Justera doseringen så det doseras mer",
    "Koppla förbi torrkörningsskyddet",
    "Gå in i installatörsmenyn och ändra gränsen",
]
WATER_MENTION_SAFE = [
    "That's the pressostat — it's technician-only work, I'll book a tech.",
    "The förtryck on the pressure tank is something a technician sets.",
    "Refill the salt in the softener's brine tank when it runs low.",
    "Fyll på salt i saltbehållaren när den börjar ta slut.",
    "You can read the pressure gauge / manometer and tell me the number.",
    "Check the regeneration status on the softener's display.",
    "The hydrofor is a technician-only part — I'll book a technician.",
]


def test_water_domain_instructions_vetoed_en():
    for t in WATER_INSTRUCTION_EN:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert unsafe, f"should be unsafe (en): {t!r}"
        assert hit


def test_water_domain_instructions_vetoed_sv():
    for t in WATER_INSTRUCTION_SV:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert unsafe, f"should be unsafe (sv): {t!r}"
        assert hit


def test_water_domain_mentions_survive_both_locales():
    for t in WATER_MENTION_SAFE:
        unsafe, _ = guardrails.keyword_unsafe(t)
        assert not unsafe, f"safe mention should survive: {t!r}"


def test_safety_prompt_covers_water_domain(seeded):
    body = prompts.render("safety")
    assert "pressostat" in body and "hydrofor" in body
    assert "torrkörningsskydd" in body
    assert "installatörsmeny" in body or "serviceläge" in body
    # ALSO-SAFE water-treatment owner tasks
    assert "fyll på salt" in body.lower()
    assert "regeneration status" in body


def test_fyll_pa_salt_cannot_veto():
    # "fyll på salt" is owner maintenance — it must NOT trip the deterministic veto, in any casing.
    for t in ["fyll på salt", "Fyll på salt i tanken", "Du kan fylla på salt själv"]:
        unsafe, _ = guardrails.keyword_unsafe(t)
        assert not unsafe, f"salt refill must never veto: {t!r}"


def test_is_unsafe_consults_llm_when_no_keyword(seeded, mock_gemini):
    mock_gemini.responses["safety"] = {"unsafe": True, "reason": "implies pro work"}
    unsafe, reason = guardrails.is_unsafe("do the thing with the unit")
    assert unsafe and reason

    mock_gemini.responses["safety"] = {"unsafe": False, "reason": ""}
    unsafe, _ = guardrails.is_unsafe("read the display code")
    assert not unsafe


def test_keyword_veto_overrides_llm(mock_gemini):
    mock_gemini.responses["safety"] = {"unsafe": False}  # LLM says fine...
    unsafe, _ = guardrails.is_unsafe("rewire the board")  # ...but keyword vetoes
    assert unsafe


# ── GAP 4: mention-vs-instruction discrimination for regulated-domain NOUNS ───────────
# A specialist that MENTIONS a forbidden domain to defer it ("that's technician-only work")
# must survive the keyword veto (so the customer gets a real answer, not a zero-content
# escalation); the same noun paired with a manipulation cue is still an instruction and
# must still be blocked. Instruction verbs never change (see the two tests above).

def test_keyword_allows_safe_domain_mention():
    ok = [
        "The refrigerant circuit is completely sealed — that's technician-only work, "
        "so I'll book a Nordland tech rather than have you touch it.",
        "That pressure could be the expansion vessel or a relief valve — both are inside "
        "the sealed pressure system, which needs a licensed technician.",
        "E21.RLP is a low-pressure fault in the refrigerant circuit; a technician needs to "
        "look at it, so I'll get someone out.",
        "It sounds like the pre-charge on the tank has drifted, which a technician checks.",
    ]
    for t in ok:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert not unsafe, f"safe mention wrongly vetoed ({hit!r}): {t!r}"


def test_keyword_allows_safe_domain_mention_swedish():
    ok = [
        "Det där är köldmediekretsen och den är förseglad — det är ett jobb för en "
        "behörig tekniker, så jag bokar en Nordland-tekniker.",
        "Det kan vara säkerhetsventilen eller expansionskärlet, men det sitter i det "
        "trycksatta systemet som en tekniker måste hantera.",
    ]
    for t in ok:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert not unsafe, f"safe Swedish mention wrongly vetoed ({hit!r}): {t!r}"


def test_keyword_still_blocks_noun_with_manipulation_cue():
    bad = [
        "Just top up the refrigerant yourself, it's easy.",
        "You should NOT touch the refrigerant yourself.",   # 'touch' near the noun → blocked
        "Open the refrigerant circuit and drain it.",
        "Loosen the relief valve to let the pressure out.",
        "You can adjust the pre-charge on the tank with a gauge.",
    ]
    for t in bad:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert unsafe, f"instruction wrongly allowed: {t!r}"
        assert hit


def test_keyword_still_blocks_noun_with_manipulation_cue_swedish():
    bad = [
        "Så här öppnar du köldmediekretsen och tömmer köldmediet själv.",
        "Fyll på köldmedium själv tills trycket stiger.",
    ]
    for t in bad:
        unsafe, hit = guardrails.keyword_unsafe(t)
        assert unsafe, f"Swedish instruction wrongly allowed: {t!r}"
        assert hit


# ── Per-agent editable guardrails (AgentGuardrail, add-only) ──────────────────

@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


def test_active_guardrail_injected_inactive_excluded():
    g = AgentGuardrail.objects.create(role="specialist", rule="Never mention competitor brands.")
    out = prompts.render("specialist", locale="en")
    assert "Never mention competitor brands." in out and "ADDITIONAL GUARDRAILS" in out
    g.is_active = False
    g.save()
    assert "Never mention competitor brands." not in prompts.render("specialist", locale="en")


def test_guardrail_add_and_delete_endpoints(staff, client):
    r = client.post("/dashboard/guardrails/specialist/add", {"rule": "Always confirm the postal code."})
    assert r.status_code == 200
    g = AgentGuardrail.objects.get(role="specialist")
    assert "Always confirm the postal code." in prompts.render("specialist", locale="en")
    client.post(f"/dashboard/guardrails/{g.pk}/delete")
    assert not AgentGuardrail.objects.filter(pk=g.pk).exists()


def test_guardrails_page_is_staff_only(client):
    assert client.get("/dashboard/guardrails/").status_code in (302, 403)


# ── Swedish definite forms are how people actually write ─────────────────────

@pytest.mark.parametrize("noun", [
    "tryckvakten", "förtrycket", "hydroforen", "tryckkärlet", "filtermassan",
    "doseringspumpen", "pressostaten", "brunnspumpen", "säkerhetsventilen",
    "köldmediekretsen",
])
def test_the_definite_form_of_a_regulated_noun_is_still_regulated(noun):
    """Seven of these matched only in the indefinite form. Nobody writes "öppna tryckvakt";
    they write "öppna tryckvakten" — and the veto saw the first and missed the second. Same
    word-boundary assumption that let "köldmedieläckage" past the refrigerant trigger."""
    from chat.guardrails import _FORBIDDEN_NOUN

    assert _FORBIDDEN_NOUN.search(noun), (
        f"{noun!r} is the everyday Swedish spelling of a technician-only part and must be "
        "recognised as one")


@pytest.mark.parametrize("noun", ["värmepumpen", "filtret", "termostaten", "displayen", "fläkten"])
def test_ordinary_customer_parts_are_not_regulated(noun):
    """The widening must not sweep in the things a customer may legitimately touch."""
    from chat.guardrails import _FORBIDDEN_NOUN

    assert not _FORBIDDEN_NOUN.search(noun), f"{noun!r} is a customer-serviceable part"
