"""Tests verifying translation and description completeness across all appliance catalogs.

Validates that 100% of programs across all supported appliances in the demo database
resolve to localized names and descriptions without falling back to title-casing.
"""

import json
from pathlib import Path

import pytest

from custom_components.candy.client.model import (
    _PROGRAM_NAMES,
    TumbleDryerProgram,
    WashingMachineWashProgram,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "all_appliance_program_names.json"


def _load_all_appliance_programs() -> list[tuple[int, str, str, str]]:
    """Collect (serial, appliance_type, raw_name, model) for every program across washers and dryers."""
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        catalog = json.load(f)
    programs: list[tuple[int, str, str, str]] = []
    for app in catalog:
        serial = app.get("serial", 0)
        app_type = app.get("appliance_type", "")
        model = app.get("model", "")
        for raw_name in app.get("program_names", []):
            programs.append((serial, app_type, raw_name, model))
    return programs


ALL_PROGRAM_ENTRIES = _load_all_appliance_programs()


def test_program_names_catalog_has_entries() -> None:
    """Validate that _PROGRAM_NAMES is populated with authentic Simply-Fi translations."""
    assert len(_PROGRAM_NAMES) > 400
    assert "COTTONS" in _PROGRAM_NAMES
    assert "RESISTANT_COTTONS" in _PROGRAM_NAMES
    assert "HYGIENE_60" in _PROGRAM_NAMES
    assert "OFF" in _PROGRAM_NAMES
    assert "ONE_FI_EXTRA" in _PROGRAM_NAMES


def test_off_position_translations() -> None:
    """Validate that knob position 0 (OFF) translates accurately across locales."""
    off_translations = _PROGRAM_NAMES.get("OFF", {})
    assert off_translations.get("en") == "Off"
    assert off_translations.get("it") == "Off"
    assert off_translations.get("de") == "Aus"
    assert off_translations.get("nl") == "Uit"

    desc = _PROGRAM_NAMES.get("OFF_DESCRIPTION", {})
    assert desc.get("en") == "Appliance powered off"
    assert desc.get("it") == "Elettrodomestico spento"


@pytest.mark.parametrize(
    ("serial", "app_type", "raw_name", "model"),
    ALL_PROGRAM_ENTRIES,
)
def test_all_catalog_programs_have_localization(
    serial: int, app_type: str, raw_name: str, model: str
) -> None:
    """Assert that every single program in the demo database resolves to localized strings."""
    dummy_dict = {"program": {"name": raw_name, "position": 1}}

    if app_type in ("washer", "washer_dryer", "washer-nfc"):
        parsed = WashingMachineWashProgram.from_dict(dummy_dict)
    else:
        parsed = TumbleDryerProgram.from_dict(dummy_dict)

    assert parsed.name in _PROGRAM_NAMES, (
        f"Program '{raw_name}' (parsed as '{parsed.name}') on appliance {serial} "
        f"({app_type} - {model}) missing from _PROGRAM_NAMES."
    )

    en_name = parsed.localized_name("en")
    assert en_name, f"Empty English name for {raw_name} on appliance {serial}"
    # Verify it does not fall back to unstripped raw prefixes
    assert not en_name.startswith("Wa Prog "), f"Bianca prefix leaked: {en_name}"
    assert not en_name.startswith("Nfc Program Name "), f"NFC prefix leaked: {en_name}"
    assert not en_name.startswith("Dual Wm "), f"DualTech prefix leaked: {en_name}"

    it_name = parsed.localized_name("it")
    assert it_name, f"Empty Italian name for {raw_name} on appliance {serial}"

    desc_key = f"{parsed.name}_DESCRIPTION"
    assert desc_key in _PROGRAM_NAMES, (
        f"Description for '{raw_name}' (key '{desc_key}') missing on appliance {serial}."
    )
    en_desc = parsed.localized_description("en")
    assert en_desc is not None and len(en_desc) > 0, (
        f"Empty English description for {raw_name} on appliance {serial}"
    )


def test_bianca_specific_program_mappings() -> None:
    """Validate that Bianca programs with WA_PROG_ prefix map to authentic localized strings."""
    bianca_programs = [
        ("WA_PROG_COTTON", "Cotton", "Cotone"),
        ("WA_PROG_RESISTANT_COTTON", "Resistant Cotton", "Cotone Resistente"),
        (
            "WA_PROG_PERFECT_20_MIX_WASH",
            "Perfect 20° Mix & Wash",
            "Perfect 20° Mix & Wash",
        ),
        ("WA_PROG_HYGIENE_60", "Hygiene 60°", "Igiene 60°"),
        ("WA_PROG_DELICATES", "Delicates", "Delicati"),
        ("WA_PROG_WOOL", "Woolmark", "Lana"),
    ]
    for raw, expected_en, expected_it in bianca_programs:
        prog = WashingMachineWashProgram.from_dict(
            {"program": {"name": raw, "position": 1}}
        )
        assert prog.localized_name("en") == expected_en
        assert prog.localized_name("it") == expected_it
        assert prog.localized_description("en") is not None


def test_nfc_washer_specific_program_mappings() -> None:
    """Validate that NFC washer programs map to clean localized strings without raw prefixes."""
    nfc_programs = [
        ("NFC_PROGRAM_NAME_1D_COTTONS", "Cottons", "Cotone"),
        (
            "NFC_PROGRAM_NAME_2D_RESISTANT_COTTONS",
            "Whites",
            "Cotone Resistente",
        ),
        ("NFC_CARE_AUTO_CLEAN", "Auto-Clean", "Auto-Pulizia"),
    ]
    for raw, expected_en, expected_it in nfc_programs:
        prog = WashingMachineWashProgram.from_dict(
            {"program": {"name": raw, "position": 1}}
        )
        assert prog.localized_name("en") == expected_en
        assert prog.localized_name("it") == expected_it
        assert prog.localized_description("en") is not None
