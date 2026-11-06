"""Fuzzing and mutation test suite for appliance telemetry schemas and HA entities.

Validates parser resilience against:
- Missing mandatory and optional telemetry registers
- Corrupted types (strings, null, booleans, negative numbers, floats)
- Out-of-bounds boundary values and unknown enum codes
- Safe entity rendering across all registered HA platforms without uncaught exceptions
"""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.client.model import (
    CheckUpResult,
    CheckUpState,
    DishwasherState,
    DishwasherStatus,
    DryerCycleState,
    DryerProgramState,
    MachineState,
    OvenState,
    OvenStatus,
    TumbleDryerStatus,
    WasherDryerDryTarget,
    WashingMachineStatus,
    WashProgramState,
    WineCoolerProgram,
    WineCoolerState,
    WineCoolerStatus,
)
from custom_components.candy.const import (
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
)

from .common import init_integration

# ---------------------------------------------------------------------------
# Base Telemetry Payloads
# ---------------------------------------------------------------------------

BASE_WASH_JSON: dict[str, Any] = {
    "WiFiStatus": "1",
    "Err": "0",
    "MachMd": "1",
    "Pr": "1",
    "PrPh": "0",
    "PrCode": "136",
    "SLevel": "2",
    "Temp": "40",
    "SpinSp": "10",
    "DelVal": "0",
    "RemTime": "3600",
    "FillR": "50",
    "NtcW": "25",
    "NtcD": "24",
    "APSfreq": "50",
    "motS": "0",
    "unbF": "0",
    "unbC": "0",
    "numF": "0",
    "DisTestRes": "1",
    "CheckUpState": "0",
    "RecipeId": "NULL",
    "DryT": "0",
    "Det": "1",
    "Soft": "1",
    "DetWarn": "0",
    "SoftWarn": "0",
    "DetPreW": "0",
    "SoftPreW": "0",
    "DPrgCnt": "20",
    "SPrgCnt": "18",
    "WaterHard": "2",
    "rED": "0",
}

BASE_DRYER_JSON: dict[str, Any] = {
    "StatoWiFi": "1",
    "StatoTD": "1",
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
    "DryingManagerLevel": "1",
    "DelVal": "0",
    "DoorState": "1",
    "RecipeId": "NULL",
    "CheckUpState": "0",
}

BASE_DISHWASHER_JSON: dict[str, Any] = {
    "StatoWiFi": "1",
    "StatoDWash": "0",
    "CodiceErrore": "0",
    "Program": "P1",
    "OpzProg": "0",
    "RemTime": "90",
    "DelayStart": "0",
    "OpenDoor": "0",
    "OpenDoorOpt": "0",
    "Eco": "0",
    "MissSalt": "0",
    "MissRinse": "0",
}

BASE_OVEN_JSON: dict[str, Any] = {
    "StatoWiFi": "1",
    "StartStop": "0",
    "Program": "1",
    "Selettore": "1",
    "TempRead": "212",
    "TempSetRaggiunta": "0",
    "TimeProgr": "60",
}

BASE_WINE_COOLER_JSON: dict[str, Any] = {
    "r1": "1",
    "r2": "E0",
    "r3": "1",
    "r4": "12",
    "r5": "2",
    "r10": "0",
}


# ---------------------------------------------------------------------------
# Unit Parser Fuzzing: WashingMachineStatus.from_json
# ---------------------------------------------------------------------------


def test_wash_parser_valid_base() -> None:
    """Validate that the baseline payload parses completely with expected types."""
    status = WashingMachineStatus.from_json(BASE_WASH_JSON)
    assert status.machine_state == MachineState.IDLE
    assert status.program_state == WashProgramState.STOPPED
    assert status.program == 1
    assert status.temp == 40
    assert status.spin_speed == 1000
    assert status.remaining_minutes == 60
    assert status.remote_control is True
    assert status.detergent_on is True
    assert status.softener_on is True
    assert status.detergent_empty is False
    assert status.softener_empty is False
    assert status.detergent_cycles_remaining == 20
    assert status.softener_cycles_remaining == 18


def test_wash_parser_missing_optional_registers() -> None:
    """Optional telemetry keys omitted by older firmware must default to None."""
    payload = {
        "WiFiStatus": "1",
        "MachMd": "1",
        "Pr": "1",
        "PrPh": "0",
        "Temp": "40",
        "SpinSp": "10",
        "RemTime": "3600",
    }
    status = WashingMachineStatus.from_json(payload)
    assert status.machine_state == MachineState.IDLE
    assert status.fill_percent is None
    assert status.error is None
    assert status.delay_value is None
    assert status.soil_level is None
    assert status.dry_target is None
    assert status.detergent_on is None
    assert status.detergent_cycles_remaining is None


@pytest.mark.parametrize(
    "missing_key",
    ["MachMd", "PrPh", "Temp", "SpinSp", "RemTime", "WiFiStatus"],
)
def test_wash_parser_missing_mandatory_keys_raises(missing_key: str) -> None:
    """Missing mandatory registers must raise KeyError rather than corrupting model."""
    payload = copy.deepcopy(BASE_WASH_JSON)
    del payload[missing_key]
    with pytest.raises(KeyError):
        WashingMachineStatus.from_json(payload)


@pytest.mark.parametrize(
    "bad_mach_md",
    [-1, 99, "invalid", "", None],
)
def test_wash_parser_corrupted_machine_state(bad_mach_md: Any) -> None:
    """Unknown or malformed MachMd values must raise ValueError or TypeError."""
    payload = copy.deepcopy(BASE_WASH_JSON)
    payload["MachMd"] = bad_mach_md
    with pytest.raises((ValueError, TypeError)):
        WashingMachineStatus.from_json(payload)


@pytest.mark.parametrize(
    "bad_pr_ph",
    [-1, 99, "invalid", "", None],
)
def test_wash_parser_corrupted_program_phase(bad_pr_ph: Any) -> None:
    """Unknown or malformed PrPh values must raise ValueError or TypeError."""
    payload = copy.deepcopy(BASE_WASH_JSON)
    payload["PrPh"] = bad_pr_ph
    with pytest.raises((ValueError, TypeError)):
        WashingMachineStatus.from_json(payload)


def test_wash_parser_sentinel_soil_level() -> None:
    """Soil level sentinel value 9 reported by real machines must parse without crash."""
    payload = copy.deepcopy(BASE_WASH_JSON)
    payload["SLevel"] = "9"
    status = WashingMachineStatus.from_json(payload)
    assert status.soil_level == 9


def test_wash_parser_autodose_string_resilience() -> None:
    """Autodose remaining cycles formatted as non-digits must safely evaluate to None."""
    payload = copy.deepcopy(BASE_WASH_JSON)
    payload["DPrgCnt"] = "null"
    payload["SPrgCnt"] = ""
    payload["WaterHard"] = "INVALID"
    status = WashingMachineStatus.from_json(payload)
    assert status.detergent_cycles_remaining is None
    assert status.softener_cycles_remaining is None
    assert status.water_hardness is None


@pytest.mark.parametrize(
    "corrupted_dry_t",
    ["", "   ", "null", "N/A", "-1", None, "255", 255, 99, 45, "invalid"],
)
def test_wash_parser_dry_target_resilience(corrupted_dry_t: Any) -> None:
    """DryT register formatted as empty, non-digit, or unmapped sentinel must evaluate to None."""
    payload = copy.deepcopy(BASE_WASH_JSON)
    payload["DryT"] = corrupted_dry_t
    status = WashingMachineStatus.from_json(payload)
    assert status.dry_target is None


# ---------------------------------------------------------------------------
# Unit Parser Fuzzing: TumbleDryerStatus.from_json
# ---------------------------------------------------------------------------


def test_dryer_parser_valid_base() -> None:
    """Validate baseline tumble dryer telemetry parsing."""
    status = TumbleDryerStatus.from_json(BASE_DRYER_JSON)
    assert status.machine_state == MachineState.IDLE
    assert status.program_state == DryerProgramState.STOPPED
    assert status.cycle_state == DryerCycleState.LEVEL_HANG
    assert status.remaining_minutes == 120
    assert status.remote_control is True
    assert status.error is None
    assert status.error_code == 0


@pytest.mark.parametrize(
    ("error_raw", "expected_code"),
    [
        ("0", 0),
        ("E0", 0),
        ("", 0),
        ("E03", 3),
        ("3", 3),
        ("E18", 18),
        ("NULL", None),
        ("E99", 99),
    ],
)
def test_dryer_parser_error_code_resilience(
    error_raw: str, expected_code: int | None
) -> None:
    """Error strings of varying formats must map cleanly to integer error_code."""
    payload = copy.deepcopy(BASE_DRYER_JSON)
    payload["CodiceErrore"] = error_raw
    status = TumbleDryerStatus.from_json(payload)
    assert status.error_code == expected_code


@pytest.mark.parametrize("bad_stato_td", [-1, 9, 99, "abc", ""])
def test_dryer_parser_corrupted_stato_td(bad_stato_td: Any) -> None:
    """Unmapped or non-numeric StatoTD codes must raise ValueError."""
    payload = copy.deepcopy(BASE_DRYER_JSON)
    payload["StatoTD"] = bad_stato_td
    with pytest.raises(ValueError):
        TumbleDryerStatus.from_json(payload)


# ---------------------------------------------------------------------------
# Unit Parser Fuzzing: Other Appliances
# ---------------------------------------------------------------------------


def test_dishwasher_parser_resilience() -> None:
    """Dishwasher parser must handle variations in OpzProg and non-numeric fields."""
    payload = copy.deepcopy(BASE_DISHWASHER_JSON)
    status_base = DishwasherStatus.from_json(payload)
    assert status_base.machine_state == DishwasherState.IDLE
    assert status_base.program == "P1"

    payload["OpzProg"] = "p"
    assert DishwasherStatus.from_json(payload).program == "P1+"
    payload["OpzProg"] = "m"
    assert DishwasherStatus.from_json(payload).program == "P1-"
    del payload["OpzProg"]
    assert DishwasherStatus.from_json(payload).program == "P1"


def test_oven_parser_resilience() -> None:
    """Oven parser must convert Fahrenheit to Celsius without error."""
    payload = copy.deepcopy(BASE_OVEN_JSON)
    status = OvenStatus.from_json(payload)
    assert status.machine_state == OvenState.IDLE
    assert status.temp == 100.0  # 212 F == 100 C


def test_wine_cooler_parser_resilience() -> None:
    """Wine cooler parser must handle valid and invalid program codes."""
    payload = copy.deepcopy(BASE_WINE_COOLER_JSON)
    status = WineCoolerStatus.from_json(payload)
    assert status.machine_state == WineCoolerState.ON
    assert status.program == WineCoolerProgram.RED_WINE

    payload["r3"] = "99"
    with pytest.raises(ValueError):
        WineCoolerStatus.from_json(payload)


# ---------------------------------------------------------------------------
# End-to-End Entity Rendering Fuzzing (Home Assistant State Verification)
# ---------------------------------------------------------------------------

_STATS_MOCK = '{"statusCounters": {"Program1": "10"}}'


def _build_status_obj(
    machine_state: MachineState,
    program_state: WashProgramState,
    rem_time: int,
    soil_level: int | None,
    error: int | None,
    delay: int | None,
    temp: int,
    spin: int,
    dry_target: WasherDryerDryTarget | None,
    detergent_cycles: int | None,
) -> WashingMachineStatus:
    """Construct a clean WashingMachineStatus object with explicit parameters."""
    return WashingMachineStatus(
        machine_state=machine_state,
        program_state=program_state,
        program=1,
        program_code=136,
        temp=temp,
        spin_speed=spin,
        remaining_minutes=rem_time,
        remote_control=True,
        fill_percent=50,
        error=error,
        delay_value=delay,
        ntc_water=25,
        ntc_drum=24,
        motor_speed_freq=50,
        motor_state=0,
        unbalance_fault=0,
        unbalance_count=0,
        fault_count=0,
        dis_test_res=CheckUpResult.OK,
        checkup_state=CheckUpState.IDLE,
        soil_level=soil_level,
        recipe_id=None,
        dry_target=dry_target,
        detergent_on=True,
        softener_on=True,
        detergent_empty=False,
        softener_empty=False,
        detergent_reserve=False,
        softener_reserve=False,
        detergent_cycles_remaining=detergent_cycles,
        softener_cycles_remaining=15,
        water_hardness=2,
        extra_dose_active=False,
    )


async def test_entity_rendering_across_fuzzed_states(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Ensure no entity property crashes when coordinator pushes extreme edge-case status objects."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        status_response='{"statusLavatrice": {"WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0", "Temp": "40", "SpinSp": "10", "RemTime": "60"}}',
        statistics_response=_STATS_MOCK,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "RAPIDO_4DIG_STM_NEL_ad",
            CONF_KEY_IS_WASHER_DRYER: True,
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_PROGRAMS: (
                '[{"program": {"name": "Cotton", "parameters": ['
                '{"name": "PrCode", "validation": 136},'
                '{"name": "Pr", "validation": 1},'
                '{"name": "Temp", "validation": 90},'
                '{"name": "SpinSp", "validation": 14},'
                '{"name": "SLevel", "validation": 3},'
                '{"name": "FillR", "validation": 100},'
                '{"name": "DelVal", "validation": 1440},'
                '{"name": "RemTime", "validation": 180}'
                "]}}]"
            ),
        },
    )

    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Matrix of boundary conditions and sentinel values
    test_cases = [
        # 1. Negative remaining time and sentinel soil level 9
        _build_status_obj(
            machine_state=MachineState.RUNNING,
            program_state=WashProgramState.WASH,
            rem_time=-5,
            soil_level=9,
            error=0,
            delay=None,
            temp=40,
            spin=1000,
            dry_target=None,
            detergent_cycles=None,
        ),
        # 2. Huge uncataloged error code and maximum spin
        _build_status_obj(
            machine_state=MachineState.ERROR,
            program_state=WashProgramState.ERROR,
            rem_time=0,
            soil_level=0,
            error=999,
            delay=None,
            temp=0,
            spin=25500,
            dry_target=WasherDryerDryTarget.EXTRA_DRY,
            detergent_cycles=0,
        ),
        # 3. Delayed start with high delay and cold temperature
        _build_status_obj(
            machine_state=MachineState.DELAYED_START_PROGRAMMED,
            program_state=WashProgramState.STOPPED,
            rem_time=120,
            soil_level=1,
            error=0,
            delay=1440,
            temp=0,
            spin=0,
            dry_target=WasherDryerDryTarget.NO_DRY,
            detergent_cycles=999,
        ),
        # 4. Finished state with all optional values None
        _build_status_obj(
            machine_state=MachineState.FINISHED1,
            program_state=WashProgramState.END,
            rem_time=0,
            soil_level=None,
            error=None,
            delay=None,
            temp=40,
            spin=800,
            dry_target=None,
            detergent_cycles=None,
        ),
        # 5. Good Night rinse hold phase
        _build_status_obj(
            machine_state=MachineState.RUNNING,
            program_state=WashProgramState.GOOD_NIGHT,
            rem_time=25,
            soil_level=2,
            error=0,
            delay=None,
            temp=60,
            spin=1200,
            dry_target=None,
            detergent_cycles=5,
        ),
        # 6. Synthetic OFF state
        _build_status_obj(
            machine_state=MachineState.OFF,
            program_state=WashProgramState.STOPPED,
            rem_time=0,
            soil_level=None,
            error=None,
            delay=None,
            temp=0,
            spin=0,
            dry_target=None,
            detergent_cycles=None,
        ),
    ]

    for status_obj in test_cases:
        coordinator.async_set_updated_data(status_obj)
        await hass.async_block_till_done()

        # Assert all entities in the integration render safely without throwing
        for entity_id in hass.states.async_entity_ids():
            state = hass.states.get(entity_id)
            assert state is not None, f"Entity {entity_id} state is unexpectedly None"
            assert isinstance(state.state, str), (
                f"Entity {entity_id} state must be string, got {type(state.state)}"
            )
            assert isinstance(state.attributes, dict), (
                f"Entity {entity_id} attributes must be dict"
            )
