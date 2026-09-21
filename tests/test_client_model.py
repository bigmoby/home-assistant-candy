"""Tests for custom_components.candy.client.model helpers not covered elsewhere."""

from __future__ import annotations

import pytest

from custom_components.candy.client.model import (
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
        position=1,
        selector_position=1,
        name="RESISTANT_COTTONS",
        pr_code=136,
        max_temperature=90,
        default_temperature=40,
        max_spin_speed=1400,
        default_spin_speed=800,
        min_soil_level=0,
        max_soil_level=3,
        default_soil_level=1,
        steam=False,
        steam_type="",
        default_duration=120,
        duration_soil_max=150,
        duration_soil_medium=120,
        duration_soil_min=90,
        liquid_detergent_dose=None,
        powder_detergent_dose=None,
        max_cycle_capacity=None,
        available_options=0,
        selector_position_dry=None,
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
        selector_position_dry=None,
    )
    assert program.display_name == "Totally Unknown Program"


# ---------------------------------------------------------------------------
# load_downloadable_programs
# ---------------------------------------------------------------------------


def test_load_downloadable_programs_parses_known_entry():
    raw = [
        {
            "position": "56",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "1",
            "temperature": "30",
            "spin_speed": "600",
            "soil_level": "1",
            "options": "0",
            "steam": "0",
        }
    ]
    result = load_downloadable_programs(raw)

    assert len(result) == 1
    program = result[0]
    assert program.position == 56
    assert program.parent == 1
    assert program.temperature == 30
    assert program.spin_speed == 600
    assert program.soil_level == 1
    assert program.recipe_id == "D_56"
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
            "parent": "1",
        }
    ]
    result = load_downloadable_programs(raw)
    assert result == []


def test_load_downloadable_programs_max_spin_speed_becomes_none():
    raw = [
        {
            "position": "56",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "1",
            "temperature": "30",
            "spin_speed": "MAX",
            "soil_level": "1",
            "options": "0",
            "steam": "0",
        }
    ]
    result = load_downloadable_programs(raw)
    assert result[0].spin_speed is None


def test_load_downloadable_programs_invalid_spin_speed_becomes_none():
    raw = [
        {
            "position": "56",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            "parent": "1",
            "temperature": "30",
            "spin_speed": "garbage",
            "soil_level": "1",
            "options": "0",
            "steam": "0",
        }
    ]
    result = load_downloadable_programs(raw)
    assert result[0].spin_speed is None


# ---------------------------------------------------------------------------
# WashingMachineWashProgram.from_dict - selector_position_dry
# ---------------------------------------------------------------------------


def test_from_dict_parses_selector_position_dry_when_present():
    raw = {
        "program": {
            "position": 1,
            "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "9",
                    }
                },
                {
                    "command_parameter": {
                        "name": "selector_position_dry",
                        "validation": "1",
                    }
                },
            ],
        }
    }
    program = WashingMachineWashProgram.from_dict(raw)
    assert program.selector_position_dry == 1


def test_from_dict_selector_position_dry_none_when_absent():
    raw = {
        "program": {
            "position": 2,
            "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_30_MIN",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "16",
                    }
                },
            ],
        }
    }
    program = WashingMachineWashProgram.from_dict(raw)
    assert program.selector_position_dry is None
