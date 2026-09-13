"""A customer who types the exact model must never be asked to pick it from a list.

Live production, 2026-09-13: the bot offered "AirX 500" as a chip, the customer tapped it,
and the reply was "Do you mean Aero 500 or Geo 500C or Geo 500E or AirX 500?". The per-slot
extractor had stored model="500" — it reads "AirX" as the series and keeps only the number —
so the identification query was "IVT 500", which trigram-matches all four equally.
"""
from __future__ import annotations

import pytest
from django.core.management import call_command

from chat import orchestrator as orch
from kb.identification import machine_named_in

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    """The real "500" ambiguity family, copied from the production catalog: four IVT
    machines whose names all end in 500, which is exactly why a bare "500" is useless."""
    call_command("seed_kb")
    from kb.models import Category, Machine, Vendor

    ivt = Vendor.objects.get(name="IVT")
    for mn, cat, aliases in (
            ("Aero 500", "air_to_air", ["aero 500", "aero500"]),
            ("AirX 500", "air_to_water", ["air x 500", "airx 500", "airx500"]),
            ("Geo 500C", "water_to_water", ["500c", "geo 500c", "geo500c"]),
            ("Geo 500E", "water_to_water", ["500e", "geo 500e", "geo500e"])):
        Machine.objects.get_or_create(
            vendor=ivt, model_name=mn,
            defaults=dict(category=Category.objects.get(slug=cat), is_supported=True,
                          slug=mn.lower().replace(" ", "-"), aliases=aliases))
    return {"ivt": ivt}


def test_the_exact_reply_names_the_machine(seeded):
    machine, span = machine_named_in("AirX 500", vendor=seeded["ivt"])
    assert machine.model_name == "AirX 500"
    assert span == "AirX 500", "the customer's own words are what gets stored"


def test_the_model_is_found_inside_a_sentence(seeded):
    machine, span = machine_named_in("it's an AirX 500 I think", vendor=seeded["ivt"])
    assert machine.model_name == "AirX 500"
    assert span == "AirX 500"


def test_the_longest_name_wins_over_a_bare_number(seeded):
    """"AirX 500" must resolve to AirX 500, never to Aero 500 or Geo 500C on the "500"."""
    assert machine_named_in("AirX 500", vendor=seeded["ivt"])[0].model_name == "AirX 500"
    assert machine_named_in("Geo 500C", vendor=seeded["ivt"])[0].model_name == "Geo 500C"


def test_text_naming_no_machine_binds_nothing(seeded):
    assert machine_named_in("I don't know", vendor=seeded["ivt"]) is None
    assert machine_named_in("", vendor=seeded["ivt"]) is None
    # A partial that names a FAMILY rather than a unit stays ambiguous on purpose (S3).
    assert machine_named_in("Geo 500", vendor=seeded["ivt"]) is None


def test_the_extractors_narrowed_value_is_repaired(seeded):
    """The production case, end to end: extractor said "500", customer said "AirX 500"."""
    cs = {"slots": {"brand": "IVT", "model": "500", "category": "heat_pump"}}
    orch._repair_model_slot(cs, "AirX 500")
    assert cs["slots"]["model"] == "AirX 500"


def test_a_good_answer_is_never_downgraded_to_the_catalog_name(seeded):
    """The seeded name for one Bosch unit is "Bosch Compress 7000i" and one of its aliases
    is the bare "7000i". A customer who typed "Compress 7000i" already said more than that
    alias, so their wording must survive untouched."""
    from kb.models import Category, Machine, Vendor

    bosch, _ = Vendor.objects.get_or_create(name="Bosch")
    Machine.objects.get_or_create(
        vendor=bosch, model_name="Bosch Compress 7000i",
        defaults=dict(category=Category.objects.get(slug="air_to_water"), is_supported=True,
                      slug="bosch-compress-7000i", aliases=["compress 7000", "7000i"]))

    cs = {"slots": {"brand": "Bosch", "model": "Compress 7000i", "category": "heat_pump"}}
    orch._repair_model_slot(cs, "Compress 7000i")
    assert cs["slots"]["model"] == "Compress 7000i"


def test_nothing_happens_when_the_reply_names_no_machine(seeded):
    cs = {"slots": {"brand": "IVT", "model": "500", "category": "heat_pump"}}
    orch._repair_model_slot(cs, "I really don't know")
    assert cs["slots"]["model"] == "500", "an unmatched reply must leave the slot alone"


def test_a_repaired_model_binds_instead_of_disambiguating(seeded):
    """The customer-visible symptom: _resolve_machine must bind, not ask again."""
    cs = {"slots": {"brand": "IVT", "model": "500", "category": "heat_pump",
                    "ocr_text": None, "subtype": None},
          "asked": {}, "questions_asked": 0}
    assert orch._resolve_machine(cs, "en") is not None, "unrepaired '500' should disambiguate"

    cs2 = {"slots": {"brand": "IVT", "model": "500", "category": "heat_pump",
                     "ocr_text": None, "subtype": None},
           "asked": {}, "questions_asked": 0}
    orch._repair_model_slot(cs2, "AirX 500")
    assert orch._resolve_machine(cs2, "en") is None, "an exactly-named model must bind silently"
    assert cs2.get("machine_id"), "the machine should be bound"


def test_the_brand_never_leaks_into_the_model_slot(seeded):
    """"IVT Geo 412C" normalises to the same thing as vendor+model, so a whole-reply match
    would store the brand inside the model slot — which is the brand slot's job, and what
    three scenario tests caught."""
    machine, span = machine_named_in("IVT AirX 500", vendor=seeded["ivt"])
    assert machine.model_name == "AirX 500"
    assert span == "AirX 500", f"the brand must stay out of the model slot, got {span!r}"

    cs = {"slots": {"brand": "IVT", "model": "AirX 500", "category": "heat_pump"}}
    orch._repair_model_slot(cs, "it's an IVT AirX 500")
    assert cs["slots"]["model"] == "AirX 500"
