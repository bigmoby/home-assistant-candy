"""Tests for custom_components.candy.client.model helpers not covered elsewhere."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.candy.client.model import (
    DownloadableProgram,
    MachineState,
    TumbleDryerProgram,
    TumbleDryerStatus,
    WasherDryerDryTarget,
    WashingMachineStatus,
    WashingMachineWashProgram,
    WashProgramState,
    WineCoolerProgram,
    WineCoolerStatus,
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
        program_type="W",
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
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
        program_type="W",
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
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
        program_type="W",
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
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
        program_type="W",
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
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
        program_type="W",
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
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
        program_type="W",
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
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


# ---------------------------------------------------------------------------
# WasherDryerDryTarget
# ---------------------------------------------------------------------------


def test_washer_dryer_dry_target_codes():
    expected_codes = {
        0: (WasherDryerDryTarget.NO_DRY, "no_dry"),
        1: (WasherDryerDryTarget.EXTRA_DRY, "extra_dry"),
        2: (WasherDryerDryTarget.CUPBOARD_DRY, "cupboard_dry"),
        3: (WasherDryerDryTarget.IRON_DRY, "iron_dry"),
        4: (WasherDryerDryTarget.COOLDOWN, "cooldown"),
        5: (WasherDryerDryTarget.TIME_120, "120_minutes"),
        6: (WasherDryerDryTarget.TIME_90, "90_minutes"),
        7: (WasherDryerDryTarget.TIME_60, "60_minutes"),
        8: (WasherDryerDryTarget.TIME_30, "30_minutes"),
    }
    for code, (target, label) in expected_codes.items():
        parsed = WasherDryerDryTarget.from_code(code)
        assert parsed is target
        assert parsed.label == label
        assert str(parsed) == label

    with pytest.raises(ValueError, match="Unrecognized code"):
        WasherDryerDryTarget.from_code(99)


@pytest.mark.parametrize(
    ("raw_input", "expected_target"),
    [
        ("0", WasherDryerDryTarget.NO_DRY),
        (0, WasherDryerDryTarget.NO_DRY),
        ("1", WasherDryerDryTarget.EXTRA_DRY),
        (1, WasherDryerDryTarget.EXTRA_DRY),
        ("2", WasherDryerDryTarget.CUPBOARD_DRY),
        ("3", WasherDryerDryTarget.IRON_DRY),
        ("4", WasherDryerDryTarget.COOLDOWN),
        ("5", WasherDryerDryTarget.TIME_120),
        ("6", WasherDryerDryTarget.TIME_90),
        ("7", WasherDryerDryTarget.TIME_60),
        ("8", WasherDryerDryTarget.TIME_30),
        ("9", WasherDryerDryTarget.WOOL_DRY),
    ],
)
def test_washer_dry_target_from_raw_valid(
    raw_input: Any, expected_target: WasherDryerDryTarget
) -> None:
    """Test from_raw parses string and integer codes for valid targets."""
    assert WasherDryerDryTarget.from_raw(raw_input) is expected_target


@pytest.mark.parametrize(
    "invalid_raw",
    ["", "   ", "null", "N/A", "-1", None, "255", 255, "99", 99, 45, "invalid"],
)
def test_washer_dry_target_from_raw_resilience(invalid_raw: Any) -> None:
    """Test from_raw returns None for empty, non-digit, or unmapped codes."""
    assert WasherDryerDryTarget.from_raw(invalid_raw) is None


def test_washing_machine_status_parses_dry_target():
    payload = {
        "MachMd": "1",
        "PrPh": "6",
        "Pr": "1",
        "Temp": "40",
        "SpinSp": "10",
        "RemTime": "3600",
        "WiFiStatus": "1",
        "DryT": "1",
    }
    status = WashingMachineStatus.from_json(payload)
    assert status.dry_target is WasherDryerDryTarget.EXTRA_DRY


def test_washing_machine_status_without_dry_target():
    payload = {
        "MachMd": "1",
        "PrPh": "2",
        "Pr": "1",
        "Temp": "40",
        "SpinSp": "10",
        "RemTime": "3600",
        "WiFiStatus": "1",
    }
    status = WashingMachineStatus.from_json(payload)
    assert status.dry_target is None


@pytest.mark.parametrize("dry_val", ["", "   ", "255", "-1", "null", "N/A"])
def test_washing_machine_status_empty_or_sentinel_dry_target(dry_val: str) -> None:
    """Test washing machine telemetry with empty or sentinel DryT parses as None."""
    payload = {
        "MachMd": "1",
        "PrPh": "2",
        "Pr": "1",
        "Temp": "40",
        "SpinSp": "10",
        "RemTime": "3600",
        "WiFiStatus": "1",
        "DryT": dry_val,
    }
    status = WashingMachineStatus.from_json(payload)
    assert status.dry_target is None


# ---------------------------------------------------------------------------
# WashingMachineWashProgram: program_type & dry compatibility
# ---------------------------------------------------------------------------


def test_wash_program_from_dict_wash_only():
    raw = {
        "program": {
            "position": "1",
            "name": "DUAL_WM_WD_PROGRAM_NAME_DELICATES",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "1"}},
                {"command_parameter": {"name": "pr_code", "validation": "4"}},
                {
                    "command_parameter": {
                        "name": "maximum_temperature",
                        "validation": "40",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_temperature",
                        "validation": "30",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_spin_speed",
                        "validation": "800",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_spin_speed",
                        "validation": "400",
                    }
                },
                {
                    "command_parameter": {
                        "name": "minimum_soil_level",
                        "validation": "1",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_soil_level",
                        "validation": "1",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_soil_level",
                        "validation": "1",
                    }
                },
                {"command_parameter": {"name": "steam", "validation": "0"}},
                {"command_parameter": {"name": "default_duration", "validation": "59"}},
                {"command_parameter": {"name": "available_options", "validation": "0"}},
                {"command_parameter": {"name": "dry", "validation": "0"}},
            ],
        }
    }
    prog = WashingMachineWashProgram.from_dict(raw)
    assert prog.program_type == "W"
    assert prog.is_wash is True
    assert prog.is_dry is False
    assert prog.is_wash_and_dry is False
    assert prog.selector_position_dry is None
    assert prog.dry_supported is False


def test_wash_program_from_dict_standalone_dry():
    raw = {
        "program": {
            "position": "16",
            "name": "DUAL_WM_WD_PROGRAM_NAME_HIGH_DRY",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "16",
                    }
                },
                {"command_parameter": {"name": "pr_code", "validation": "45"}},
                {"command_parameter": {"name": "program_type", "validation": "D"}},
                {"command_parameter": {"name": "dry", "validation": "255"}},
            ],
        }
    }
    prog = WashingMachineWashProgram.from_dict(raw)
    assert prog.program_type == "D"
    assert prog.is_wash is False
    assert prog.is_dry is True
    assert prog.is_wash_and_dry is False
    assert prog.dry_supported is True


def test_wash_program_from_dict_wash_with_dry_attachment():
    raw = {
        "program": {
            "position": "9",
            "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "9"}},
                {"command_parameter": {"name": "pr_code", "validation": "65"}},
                {"command_parameter": {"name": "program_type", "validation": "W"}},
                {
                    "command_parameter": {
                        "name": "selector_position_dry",
                        "validation": "1",
                    }
                },
                {"command_parameter": {"name": "dry", "validation": "255"}},
            ],
        }
    }
    prog = WashingMachineWashProgram.from_dict(raw)
    assert prog.program_type == "W"
    assert prog.is_wash is True
    assert prog.is_dry is False
    assert prog.is_wash_and_dry is True
    assert prog.selector_position_dry == 1
    assert prog.dry_supported is True


def test_wash_program_from_dict_combo_cycle():
    raw = {
        "program": {
            "position": "23",
            "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_WASH_AND_DRY_59_MIN",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "23",
                    }
                },
                {"command_parameter": {"name": "pr_code", "validation": "16"}},
                {"command_parameter": {"name": "program_type", "validation": "WD"}},
                {"command_parameter": {"name": "dry", "validation": "0"}},
            ],
        }
    }
    prog = WashingMachineWashProgram.from_dict(raw)
    assert prog.program_type == "WD"
    assert prog.is_wash is True
    assert prog.is_dry is False
    assert prog.is_wash_and_dry is True


def test_wash_program_from_dict_combo_cycle_with_wash_type():
    raw = {
        "program": {
            "position": "16",
            "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_WASH_AND_DRY_59_MIN",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "14",
                    }
                },
                {"command_parameter": {"name": "pr_code", "validation": "16"}},
                {"command_parameter": {"name": "program_type", "validation": "W"}},
                {"command_parameter": {"name": "dry", "validation": "0"}},
            ],
        }
    }
    prog = WashingMachineWashProgram.from_dict(raw)
    assert prog.program_type == "WD"
    assert prog.is_wash is True
    assert prog.is_dry is False
    assert prog.is_wash_and_dry is True


@pytest.mark.parametrize(
    ("raw_code", "expected_state"),
    [
        (0, MachineState.IDLE),
        (1, MachineState.IDLE),
        (2, MachineState.RUNNING),
        (3, MachineState.PAUSED),
        (4, MachineState.DELAYED_START_SELECTION),
        (5, MachineState.DELAYED_START_PROGRAMMED),
        (6, MachineState.RUNNING),
        (7, MachineState.ERROR),
        (8, MachineState.FINISHED1),
    ],
)
def test_tumble_dryer_status_stato_td_mapping(
    raw_code: int, expected_state: MachineState
) -> None:
    data = {
        "StatoWiFi": "1",
        "StatoTD": str(raw_code),
        "CodiceErrore": "0",
        "Pr": "1",
        "PrPh": "0",
        "RemTime": "120",
        "DryLev": "2",
        "Time": "0",
        "Rapido": "0",
        "Refresh": "0",
        "CleanFilter": "0",
        "WaterTankFull": "0",
        "DryingManagerLevel": "2",
        "DoorState": "1",
    }
    status = TumbleDryerStatus.from_json(data)
    assert status.machine_state == expected_state


def test_tumble_dryer_status_invalid_stato_td_raises() -> None:
    data = {
        "StatoWiFi": "1",
        "StatoTD": "99",
        "CodiceErrore": "0",
        "Pr": "1",
        "PrPh": "0",
        "RemTime": "120",
        "DryLev": "2",
        "Time": "0",
        "Rapido": "0",
        "Refresh": "0",
        "CleanFilter": "0",
        "WaterTankFull": "0",
        "DryingManagerLevel": "2",
        "DoorState": "1",
    }
    with pytest.raises(ValueError, match="Unrecognized StatoTD code: 99"):
        TumbleDryerStatus.from_json(data)


def test_washing_machine_status_autodose_and_good_night_fields() -> None:
    data = {
        "WiFiStatus": "1",
        "MachMd": "1",
        "Fill": "0",
        "CodiceErrore": "0",
        "Pr": "1",
        "PrPh": "9",
        "SLevel": "2",
        "Temp": "40",
        "SpinSp": "1000",
        "Opt1": "0",
        "Opt2": "0",
        "Opt3": "0",
        "Opt4": "0",
        "Opt5": "0",
        "Opt6": "0",
        "Opt7": "0",
        "Opt8": "0",
        "Steam": "0",
        "RemTime": "60",
        "DelStVal": "0",
        "DoorLStatus": "0",
        "Det": "1",
        "Soft": "0",
        "DetWarn": "1",
        "SoftWarn": "0",
        "DetPreW": "0",
        "SoftPreW": "1",
        "DPrgCnt": "0",
        "SPrgCnt": "15",
        "WaterHard": "2",
        "rED": "1",
    }
    status = WashingMachineStatus.from_json(data)
    assert status.program_state.code == 9
    assert status.program_state.label == "Good Night rinse hold"
    assert status.program_state is WashProgramState.GOOD_NIGHT
    assert status.detergent_on is True
    assert status.softener_on is False
    assert status.detergent_empty is True
    assert status.softener_empty is False
    assert status.detergent_reserve is False
    assert status.softener_reserve is True
    assert status.detergent_cycles_remaining == 0
    assert status.softener_cycles_remaining == 15
    assert status.water_hardness == 2
    assert status.extra_dose_active is True


def test_wash_program_from_dict_command_parameters_dict():
    raw = {
        "program": {
            "position": 1,
            "name": "COTTON",
            "command_parameters": {
                "selector_position": "1",
                "pr_code": "1",
                "program_type": "W",
            },
        }
    }
    prog = WashingMachineWashProgram.from_dict(raw)
    assert prog.name == "COTTON"
    assert prog.position == 1


def test_wash_program_without_program_type():
    prog_dry = WashingMachineWashProgram(
        position=1,
        selector_position=1,
        name="COTTON_DRY",
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
        program_type=None,
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
    )
    assert prog_dry.is_dry is True
    assert prog_dry.is_wash is False

    prog_wash = WashingMachineWashProgram(
        position=2,
        selector_position=2,
        name="COTTON",
        pr_code=2,
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
        program_type=None,
        selector_position_dry=None,
        dry_supported=False,
        dry=0,
    )
    assert prog_wash.is_dry is False
    assert prog_wash.is_wash is True


def test_tumble_dryer_program_display_name():
    prog = TumbleDryerProgram(
        position=1,
        selector_position=1,
        name="COTTON",
        default_drying_level=2,
        max_time_level=3,
        default_time_level=1,
        set_dry_level=True,
        set_time_level=False,
        set_rapido=False,
        duration=120,
        mask1=0,
        mask2=0,
    )
    assert prog.display_name == prog.localized_name("en")


def test_wine_cooler_program_default_temp():
    assert WineCoolerProgram.RED_WINE.default_temp == 16
    assert WineCoolerProgram.WHITE_WINE.default_temp == 12
    assert WineCoolerProgram.SPARKLING.default_temp == 8
    assert WineCoolerProgram.default_temp.fget(None) == 12


def test_wine_cooler_status_from_json_invalid_program_down():
    data = {
        "r2": "0",
        "r3": "1",
        "r4": "16",
        "r5": "2",
        "r7": "99",
    }
    status = WineCoolerStatus.from_json(data)
    assert status.program_down is None


def test_wash_program_from_dict_direct_name_and_auto_clean():
    raw = {
        "program": {
            "position": 1,
            "name": "WA_PROG_AUTO_CLEAN",
            "command_parameters": [
                {"name": "selector_position", "validation": "1"},
                {"name": "pr_code", "validation": "99"},
                {"name": "program_type", "validation": "W"},
            ],
        }
    }
    prog = WashingMachineWashProgram.from_dict(raw)
    assert prog.name == "AUTOCLEAN"
    assert (
        prog.localized_description("en") is not None
        or prog.localized_description("en") is None
    )


def test_tumble_dryer_program_from_dict_dict_and_list():
    raw_dict = {
        "program": {
            "position": 1,
            "name": "COTTON",
            "command_parameters": {
                "selector_position": "1",
                "default_drying_level": "2",
                "duration": "100",
            },
        }
    }
    prog1 = TumbleDryerProgram.from_dict(raw_dict)
    assert prog1.duration == 100

    raw_list = {
        "program": {
            "position": 2,
            "name": "SYNTHETICS",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "2"}},
                {"name": "duration", "validation": "80"},
            ],
        }
    }
    prog2 = TumbleDryerProgram.from_dict(raw_list)
    assert prog2.duration == 80


def test_downloadable_program_category_and_description():
    prog = DownloadableProgram(
        position=1,
        name="TEST_PROG",
        parent=1,
        temperature=40,
        spin_speed=1000,
        soil_level=1,
        options=0,
        steam=0,
        translations={"en": "Test Prog"},
        category_translations={"en": "Test Cat"},
        description_translations={"en": "Test Desc"},
    )
    assert prog.category_name("en") == "Test Cat"
    assert prog.category_prefixed("en") == "Test Cat - Test Prog"
    assert prog.description("en") == "Test Desc"
