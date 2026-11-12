"""Tests for tumble dryer command builders."""

import pytest

from custom_components.candy.client.dryer_commands import (
    DualTechDryerCommandBuilder,
    get_dryer_command_builder,
    is_dualtech_dryer_interface,
)


def test_dualtech_standard_start() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_standard_start(selector_position=2, dry_level=3)
    assert params == {
        "Write": 1,
        "Pa": 0,
        "Sel": 0,
        "PrNm": 2,
        "DryLev": 3,
        "StSt": 1,
    }


def test_dualtech_timed_start() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_timed_start(selector_position=5, time_minutes=60)
    assert params == {
        "Write": 1,
        "Pa": 0,
        "Sel": 0,
        "PrNm": 5,
        "Time": 60,
        "StSt": 1,
    }


def test_dualtech_rapid_start() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_rapid_start(selector_position=3, rapid_level=2)
    assert params == {
        "Write": 1,
        "Pa": 0,
        "Sel": 0,
        "PrNm": 3,
        "Rapido": 2,
        "StSt": 1,
    }


def test_dualtech_delay_start() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_delay_start(
        selector_position=1, dry_level=4, delay_minutes=180
    )
    assert params == {
        "Write": 1,
        "Pa": 0,
        "Sel": 0,
        "PrNm": 1,
        "DryLev": 4,
        "DelMd": 1,
        "DelVl": 180,
    }


def test_dualtech_timed_delay_start() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_timed_delay_start(
        selector_position=3, time_minutes=45, delay_minutes=60
    )
    assert params == {
        "Write": 1,
        "Pa": 0,
        "Sel": 0,
        "PrNm": 3,
        "Time": 45,
        "DelMd": 1,
        "DelVl": 60,
    }


def test_dualtech_stop() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_stop(current_program=4)
    assert params == {
        "Write": 1,
        "StSt": 0,
        "DelMd": 0,
        "PrNm": 4,
    }


def test_dualtech_pause() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_pause()
    assert params == {
        "Write": 1,
        "SetPauseDryMgr": 1,
    }


def test_dualtech_resume() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_resume()
    assert params == {
        "Write": 1,
        "SetRestartDryMgr": 1,
    }


def test_dualtech_cancel_anticrease() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_cancel_anticrease()
    assert params == {
        "Write": 1,
        "DontTumbling": 1,
    }


def test_dualtech_checkup_start() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_checkup_start()
    assert params == {
        "Write": 1,
        "CheckUpState": 1,
    }


def test_dualtech_checkup_reset() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_checkup_reset()
    assert params == {
        "Write": 1,
        "CheckUpState": 0,
    }


def test_dualtech_reset_warnings() -> None:
    builder = DualTechDryerCommandBuilder()
    params = builder.build_reset_warnings()
    assert params == {
        "Write": 1,
        "ResetWarnings": 1,
    }


def test_is_dualtech_dryer_interface() -> None:
    assert is_dualtech_dryer_interface("TD_DIGIT_1") is True
    assert is_dualtech_dryer_interface("td_digit_pro") is True
    assert is_dualtech_dryer_interface("TD_LED_3") is True
    assert is_dualtech_dryer_interface("3D_DUAL") is True
    assert is_dualtech_dryer_interface("BIANCA") is False
    assert is_dualtech_dryer_interface("RAPIDO") is False
    assert is_dualtech_dryer_interface("") is False
    assert is_dualtech_dryer_interface(None) is False


def test_get_dryer_command_builder() -> None:
    builder = get_dryer_command_builder("TD_DIGIT_1")
    assert isinstance(builder, DualTechDryerCommandBuilder)

    with pytest.raises(ValueError, match="Unsupported tumble dryer"):
        get_dryer_command_builder("UNKNOWN_INTERFACE")
