"""Tests for custom_components.candy.client.model helpers not covered elsewhere."""

from __future__ import annotations

import pytest

from custom_components.candy.client.model import (
    DownloadableProgram,
    MachineState,
    WashingMachineWashProgram,
    load_downloadable_programs,
)

# ---------------------------------------------------------------------------
# StatusCode.from_code
# ---------------------------------------------------------------------------


def test_from_code_raises_for_unrecognized_code():
    with pytest.raises(ValueError, match="Unrecognized code"):
        MachineState.from_code(999)


# ---------------------------------------------------------------------------
# WashingMachineWashProgram.display_name
# ---------------------------------------------------------------------------


def test_display_name_returns_english_localized_name():
    program = WashingMachineWashProgram(
        position=16,
        selector_position=14,
        name="RESISTANT_COTTONS",
        pr_code=65,
        max_temperature=90,
        default_temperature=60,
        max_spin_speed=1200,
        default_spin_speed=1200,
        min_soil_level=1,
        max_soil_level=3,
        default_soil_level=3,
        steam=True,
        steam_type="C",
        default_duration=169,
        duration_soil_max=169,
        duration_soil_medium=131,
        duration_soil_min=96,
        liquid_detergent_dose=4,
        powder_detergent_dose=4,
        max_cycle_capacity=None,
        available_options=251,
    )
    assert program.display_name == program.localized_name("en")


def test_display_name_falls_back_to_title_case_for_unknown_program():
    program = WashingMachineWashProgram(
        position=1,
        selector_position=1,
        name="TOTALLY_UNKNOWN_PROGRAM",
        pr_code=1,
        max_temperature=0,
        default_temperature=0,
        max_spin_speed=0,
        default_spin_speed=0,
        min_soil_level=0,
        max_soil_level=0,
        default_soil_level=0,
        steam=False,
        steam_type="",
        default_duration=0,
        duration_soil_max=0,
        duration_soil_medium=0,
        duration_soil_min=0,
        liquid_detergent_dose=None,
        powder_detergent_dose=None,
        max_cycle_capacity=None,
        available_options=0,
    )
    assert program.display_name == "Totally Unknown Program"


# ---------------------------------------------------------------------------
# load_downloadable_programs
# ---------------------------------------------------------------------------


def test_load_downloadable_programs_parses_known_entry():
    raw = [
        {
            "position": "42",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "3",
            "temperature": "20",
            "spin_speed": "600",
            "soil_level": "0",
            "options": "0",
            "steam": "0",
        }
    ]
    result = load_downloadable_programs(raw)

    assert len(result) == 1
    program = result[0]
    assert program.position == 42
    assert program.parent == 3
    assert program.temperature == 20
    assert program.spin_speed == 600
    assert program.soil_level == 0
    assert program.recipe_id == "D_42"
    assert program.display_name("en") == "Cashmere"


def test_load_downloadable_programs_skips_unrecognized_name():
    """Entries not present in the NFC allowlist (dry-only programs) are skipped."""
    raw = [
        {
            "position": "10",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_SOME_DRY_ONLY_PROGRAM",
            "parent": "1",
            "temperature": "30",
            "spin_speed": "600",
            "soil_level": "1",
            "options": "0",
            "steam": "0",
        }
    ]
    result = load_downloadable_programs(raw)
    assert result == []


def test_load_downloadable_programs_skips_invalid_position():
    raw = [
        {
            "position": "not-a-number",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "3",
        }
    ]
    result = load_downloadable_programs(raw)
    assert result == []


def test_load_downloadable_programs_max_spin_speed_becomes_none():
    raw = [
        {
            "position": "42",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "3",
            "temperature": "20",
            "spin_speed": "MAX",
            "soil_level": "0",
            "options": "0",
            "steam": "0",
        }
    ]
    result = load_downloadable_programs(raw)
    assert result[0].spin_speed is None


def test_load_downloadable_programs_invalid_spin_speed_becomes_none():
    raw = [
        {
            "position": "42",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "3",
            "temperature": "20",
            "spin_speed": "garbage",
            "soil_level": "0",
            "options": "0",
            "steam": "0",
        }
    ]
    result = load_downloadable_programs(raw)
    assert result[0].spin_speed is None


def test_load_downloadable_programs_handles_empty_string_fields():
    raw = [
        {
            "position": "42",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "",
            "temperature": "",
            "spin_speed": "",
            "soil_level": "",
            "options": "",
            "steam": "",
        }
    ]
    result = load_downloadable_programs(raw)
    assert len(result) == 1
    prog = result[0]
    assert prog.position == 42
    assert prog.recipe_id == "D_42"
    assert prog.parent == 0
    assert prog.temperature == 0
    assert prog.spin_speed is None
    assert prog.soil_level == 0
    assert prog.options == 0
    assert prog.steam == 0


def test_load_downloadable_programs_handles_none_and_invalid_fields():
    raw = [
        {
            "position": "42",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": None,
            "temperature": "invalid",
            "spin_speed": None,
            "soil_level": {},
            "options": None,
            "steam": [],
        }
    ]
    result = load_downloadable_programs(raw)
    assert len(result) == 1
    prog = result[0]
    assert prog.parent == 0
    assert prog.temperature == 0
    assert prog.soil_level == 0
    assert prog.options == 0
    assert prog.steam == 0


def test_duration_for_soil_variable_soil():
    program = WashingMachineWashProgram(
        position=16,
        selector_position=14,
        name="RESISTANT_COTTONS",
        pr_code=65,
        max_temperature=90,
        default_temperature=60,
        max_spin_speed=1200,
        default_spin_speed=1200,
        min_soil_level=1,
        max_soil_level=3,
        default_soil_level=3,
        steam=True,
        steam_type="C",
        default_duration=169,
        duration_soil_max=169,
        duration_soil_medium=131,
        duration_soil_min=96,
        liquid_detergent_dose=4,
        powder_detergent_dose=4,
        max_cycle_capacity=None,
        available_options=251,
    )
    assert program.duration_for_soil(1) == 96
    assert program.duration_for_soil(2) == 131
    assert program.duration_for_soil(3) == 169
    assert program.duration_for_soil(0) == 96
    assert program.duration_for_soil(4) == 169


def test_duration_for_soil_fixed_soil():
    program = WashingMachineWashProgram(
        position=9,
        selector_position=7,
        name="RAPID_44_MIN",
        pr_code=103,
        max_temperature=40,
        default_temperature=40,
        max_spin_speed=1000,
        default_spin_speed=800,
        min_soil_level=3,
        max_soil_level=3,
        default_soil_level=9,
        steam=False,
        steam_type="",
        default_duration=44,
        duration_soil_max=0,
        duration_soil_medium=0,
        duration_soil_min=0,
        liquid_detergent_dose=None,
        powder_detergent_dose=None,
        max_cycle_capacity=None,
        available_options=0,
    )
    assert program.duration_for_soil(1) == 44
    assert program.duration_for_soil(2) == 44
    assert program.duration_for_soil(3) == 44


def test_resolve_soil_target():
    base_variable = WashingMachineWashProgram(
        position=16,
        selector_position=14,
        name="RESISTANT_COTTONS",
        pr_code=65,
        max_temperature=90,
        default_temperature=60,
        max_spin_speed=1200,
        default_spin_speed=1200,
        min_soil_level=1,
        max_soil_level=3,
        default_soil_level=3,
        steam=True,
        steam_type="C",
        default_duration=169,
        duration_soil_max=169,
        duration_soil_medium=131,
        duration_soil_min=96,
        liquid_detergent_dose=4,
        powder_detergent_dose=4,
        max_cycle_capacity=None,
        available_options=251,
    )
    base_fixed = WashingMachineWashProgram(
        position=9,
        selector_position=7,
        name="RAPID_44_MIN",
        pr_code=103,
        max_temperature=40,
        default_temperature=40,
        max_spin_speed=1000,
        default_spin_speed=800,
        min_soil_level=3,
        max_soil_level=3,
        default_soil_level=9,
        steam=False,
        steam_type="",
        default_duration=44,
        duration_soil_max=0,
        duration_soil_medium=0,
        duration_soil_min=0,
        liquid_detergent_dose=None,
        powder_detergent_dose=None,
        max_cycle_capacity=None,
        available_options=0,
    )
    nfc_valid = DownloadableProgram(
        position=56,
        name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_BATHROBE",
        parent=1,
        temperature=40,
        spin_speed=1000,
        soil_level=2,
        options=16,
        steam=0,
        translations={"en": "Bathrobe"},
        category_translations={"en": "Home Care"},
        description_translations={"en": "Wash your bathrobe."},
    )
    assert nfc_valid.resolve_soil_target(base_variable) == 2

    nfc_zero = DownloadableProgram(
        position=37,
        name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_GYM_FIT",
        parent=1,
        temperature=30,
        spin_speed=1000,
        soil_level=0,
        options=0,
        steam=0,
        translations={"en": "Gym Fit"},
        category_translations={"en": "Special"},
        description_translations={"en": "Wash gym clothes."},
    )
    assert nfc_zero.resolve_soil_target(base_variable) == 3
    assert nfc_zero.resolve_soil_target(base_fixed) == 3
