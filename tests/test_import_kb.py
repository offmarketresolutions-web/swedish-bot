"""KB import mapping (V2 §D) — pure unit test over the real 31 IVT filenames."""
from collections import Counter

from kb.management.commands.import_kb import classify, plan_machines, token_of

FILENAMES = [
    "Anvandarmanual_Aero500.pdf", "Anvandarmanual_Aero600-1.pdf",
    "Anvandarmanual_Aero_Fjarrkontroll (1).pdf",
    "Anvandarmanual_AirX400-400S_AirBoxE (1).pdf",
    "Anvandarmanual_AirX400-400S_AirBoxE_Design (1).pdf",
    "Anvandarmanual_AirX400-400S_AirBoxS (1).pdf",
    "Anvandarmanual_AirX400-400S_AirModule (1).pdf",
    "Anvandarmanual_AirX500-AirBox (3).pdf", "Anvandarmanual_AirX500-AirModule (2).pdf",
    "Anvandarmanual_Geo312C (1).pdf", "Anvandarmanual_Geo412C (1).pdf",
    "Anvandarmanual_Geo500C (1).pdf", "Anvandarmanual_Geo500E (1).pdf",
    "Anvandarmanual_Geo600C.pdf", "Anvandarmanual_Geo600E.pdf",
    "Anvandarmanual_Geo700_C-E.pdf", "Anvandarmanual_GreenlineHEC-E (1).pdf",
    "Anvandarmanual_GreenlineHTPlus (3).pdf", "Anvandarmanual_NordicInverterDR-N (1).pdf",
    "Anvandarmanual_NordicInverterFR-N_GR-N (1).pdf", "Anvandarmanual_NordicInverterHR-N (1).pdf",
    "Anvandarmanual_NordicInverterJHR-N (1).pdf", "Anvandarmanual_NordicInverterKHR-N (1).pdf",
    "Anvandarmanual_NordicInverterLR-N (1).pdf", "Anvandarmanual_NordicInverterPHR-N (1).pdf",
    "Anvandarmanual_NordicInverterPR-N (1).pdf", "Anvandarmanual_NordicInverterTHR-N (1).pdf",
    "Anvandarmanual_PremiumLineHQ.pdf", "Anvandarmanual_Vent202.pdf",
    "Anvandarmanual_Vent302.pdf", "Anvandarmanual_Vent402 (1).pdf",
]


def test_31_files_map_to_27_machines():
    plan = plan_machines(FILENAMES)
    assert len(plan) == 27


def test_category_breakdown():
    plan = plan_machines(FILENAMES)
    counts = Counter(m["category"] for m in plan.values())
    assert counts["air_to_air"] == 12      # 3 Aero + 9 NordicInverter
    assert counts["air_to_water"] == 2     # AirX 400/400S + AirX 500
    assert counts["water_to_water"] == 10  # 7 Geo + 2 Greenline + 1 PremiumLine
    assert counts["exhaust_air"] == 3      # Vent 202/302/402


def test_variant_grouping():
    plan = plan_machines(FILENAMES)
    assert len(plan["airx-400-400s"]["files"]) == 4   # AirBoxE/E-Design/S/AirModule
    assert len(plan["airx-500"]["files"]) == 2
    assert "geo-600c" in plan and plan["geo-600c"]["category"] == "water_to_water"


def test_token_and_aliases():
    assert token_of("Anvandarmanual_Geo600C.pdf") == "Geo600C"
    assert token_of("Anvandarmanual_Aero600-1.pdf") == "Aero600"   # dedup suffix stripped
    cat, name, slug, aliases = classify("NordicInverterPHR-N")
    assert cat == "air_to_air" and "phr-n" in aliases and slug == "nordicinverter-phr-n"
