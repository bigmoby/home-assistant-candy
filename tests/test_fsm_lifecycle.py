"""Finite State Machine (FSM) Lifecycle and Trajectory Simulator.

Simulates end-to-end temporal lifecycles across washing machines and tumble dryers,
validating entity states, availability gating, and monotonic duration adjustments across:
1. Standard Wash Cycle: IDLE -> RUNNING (Prewash -> Wash -> Rinse -> Spin) -> FINISHED -> OFF
2. Delayed Start: IDLE -> Delay programmed -> Countdown ticking -> Auto-transition to RUNNING -> FINISHED
3. Pause & Resume: RUNNING -> PAUSED (door open/user pause) -> RUNNING
4. Good Night Rinse Hold: RUNNING -> PrPh=9 (Rinse Hold) -> Good Night Resume pressed -> Spin -> FINISHED
5. Tumble Dryer DualTech: IDLE -> RUNNING -> Cool-down -> Anti-crease hold -> FINISHED
"""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.client.model import (
    CheckUpResult,
    CheckUpState,
    DryerProgramState,
    MachineState,
    WasherDryerDryTarget,
    WashingMachineStatus,
    WashProgramState,
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
    UNIQUE_ID_TUMBLE_CYCLE_STATUS,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_TUMBLE_REMAINING_TIME,
    UNIQUE_ID_WASH_CYCLE_STATUS,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_REMAINING_TIME,
    UNIQUE_ID_WASH_RESUME_BUTTON,
    UNIQUE_ID_WASH_RESUME_GOOD_NIGHT,
    UNIQUE_ID_WASH_SCHEDULED_FINISH,
    UNIQUE_ID_WASH_SCHEDULED_START,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STOP_BUTTON,
    UNIQUE_ID_WASHING_MACHINE,
)

from .common import TEST_IP, init_integration

_COTTON: dict[str, Any] = {
    "program": {
        "position": 1,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "pr_code", "validation": "136"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "90"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1400"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "steam", "validation": "5"}},
            {"command_parameter": {"name": "steam_type", "validation": "C"}},
            {"command_parameter": {"name": "default_duration", "validation": "90"}},
            {
                "command_parameter": {
                    "name": "remaining_time_soil_max",
                    "validation": "120",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_medium",
                    "validation": "90",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_min",
                    "validation": "60",
                }
            },
        ],
    }
}

_DRYER_COTTON: dict[str, Any] = {
    "program": {
        "position": 1,
        "name": "TD_PROGRAM_NAME_COTTON",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "default_drying_level", "validation": "2"}},
            {"command_parameter": {"name": "duration", "validation": "120"}},
        ],
    }
}

_PROGRAMS_LIST = [_COTTON]
_DRYER_PROGRAMS_LIST = [_DRYER_COTTON]

_STATS_MOCK = '{"statusCounters": {"Program1": "10"}}'


def _build_status(
    machine_state: MachineState,
    program_state: WashProgramState,
    remaining_minutes: int,
    fill_percent: int,
    delay_value: int | None = None,
    remote_control: bool = True,
) -> WashingMachineStatus:
    """Build a deterministic WashingMachineStatus instance."""
    return WashingMachineStatus(
        machine_state=machine_state,
        program_state=program_state,
        program=1,
        program_code=136,
        temp=40,
        spin_speed=1000,
        remaining_minutes=remaining_minutes,
        remote_control=remote_control,
        fill_percent=fill_percent,
        error=0,
        delay_value=delay_value,
        ntc_water=25,
        ntc_drum=24,
        motor_speed_freq=50,
        motor_state=0,
        unbalance_fault=0,
        unbalance_count=0,
        fault_count=0,
        dis_test_res=CheckUpResult.OK,
        checkup_state=CheckUpState.IDLE,
        soil_level=2,
        recipe_id=None,
        dry_target=WasherDryerDryTarget.NO_DRY,
        detergent_on=True,
        softener_on=True,
        detergent_empty=False,
        softener_empty=False,
        detergent_reserve=False,
        softener_reserve=False,
        detergent_cycles_remaining=25,
        softener_cycles_remaining=20,
        water_hardness=2,
        extra_dose_active=False,
    )


def _get_entity_state(hass: HomeAssistant, unique_id: str):
    """Retrieve Home Assistant entity state by unique ID."""
    registry = er.async_get(hass)
    for entity_id in hass.states.async_entity_ids():
        entry = registry.async_get(entity_id)
        if entry is not None and entry.unique_id == unique_id:
            return hass.states.get(entity_id)
    return None


async def _setup_washer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    """Set up a Full Control washing machine with Rapido interface."""
    return await init_integration(
        hass,
        aioclient_mock,
        status_response='{"statusLavatrice": {"WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0", "Temp": "40", "SpinSp": "10", "RemTime": "0"}}',
        statistics_response=_STATS_MOCK,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "RAPIDO_4DIG_STM_NEL",
            CONF_KEY_IS_WASHER_DRYER: False,
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_PROGRAMS: _PROGRAMS_LIST,
        },
    )


# ---------------------------------------------------------------------------
# Test 1: Standard Wash Cycle Trajectory
# ---------------------------------------------------------------------------


async def test_standard_wash_cycle_trajectory(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Simulate a complete wash cycle from IDLE to RUNNING (4 phases), FINISHED, and OFF."""
    entry = await _setup_washer(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    cid = entry.entry_id

    def get_st(uid_tmpl: str) -> str:
        s = _get_entity_state(hass, uid_tmpl.format(cid))
        return s.state if s is not None else "missing"

    # Step 0: IDLE
    st0 = _build_status(MachineState.IDLE, WashProgramState.STOPPED, 0, 0)
    coordinator.async_set_updated_data(st0)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Idle"
    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Stopped"
    assert get_st(UNIQUE_ID_WASH_REMAINING_TIME) == "0"
    assert get_st(UNIQUE_ID_WASH_START_BUTTON) != "unavailable"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) == "unavailable"
    assert get_st(UNIQUE_ID_WASH_STOP_BUTTON) == "unavailable"

    # Step 1: Pre-wash Phase (MachMode=2, PrPh=1, RemTime=70)
    st1 = _build_status(MachineState.RUNNING, WashProgramState.PRE_WASH, 70, 30)
    coordinator.async_set_updated_data(st1)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Running"
    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Pre-wash"
    assert get_st(UNIQUE_ID_WASH_REMAINING_TIME) == "70"
    assert get_st(UNIQUE_ID_WASH_START_BUTTON) == "unavailable"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) != "unavailable"
    assert get_st(UNIQUE_ID_WASH_STOP_BUTTON) != "unavailable"
    assert get_st(UNIQUE_ID_WASH_SCHEDULED_FINISH) != "unavailable"

    # Step 2: Main Wash Phase (PrPh=2, RemTime=45)
    st2 = _build_status(MachineState.RUNNING, WashProgramState.WASH, 45, 55)
    coordinator.async_set_updated_data(st2)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Wash"
    assert get_st(UNIQUE_ID_WASH_REMAINING_TIME) == "45"

    # Step 3: Rinse Phase (PrPh=3, RemTime=20)
    st3 = _build_status(MachineState.RUNNING, WashProgramState.RINSE, 20, 80)
    coordinator.async_set_updated_data(st3)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Rinse"
    assert get_st(UNIQUE_ID_WASH_REMAINING_TIME) == "20"

    # Step 4: Final Spin Phase (PrPh=10, RemTime=8)
    st4 = _build_status(MachineState.RUNNING, WashProgramState.SPIN, 8, 0)
    coordinator.async_set_updated_data(st4)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Spin"
    assert get_st(UNIQUE_ID_WASH_REMAINING_TIME) == "8"

    # Step 5: Cycle Finished (MachMode=7 FINISHED1, PrPh=5 END, RemTime=0)
    st5 = _build_status(MachineState.FINISHED1, WashProgramState.END, 0, 0)
    coordinator.async_set_updated_data(st5)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Finished"
    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "End"
    assert get_st(UNIQUE_ID_WASH_REMAINING_TIME) == "0"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) == "unavailable"
    assert get_st(UNIQUE_ID_WASH_STOP_BUTTON) != "unavailable"

    # Step 6: Power Off (MachMode=0 OFF)
    st6 = _build_status(MachineState.OFF, WashProgramState.STOPPED, 0, 0)
    coordinator.async_set_updated_data(st6)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Off"
    assert get_st(UNIQUE_ID_WASH_START_BUTTON) == "unavailable"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) == "unavailable"
    assert get_st(UNIQUE_ID_WASH_STOP_BUTTON) == "unavailable"


# ---------------------------------------------------------------------------
# Test 2: Delayed Start Countdown Trajectory
# ---------------------------------------------------------------------------


async def test_delayed_start_trajectory(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Validate delayed start countdown ticking, scheduled timestamps, and auto-transition to running."""
    entry = await _setup_washer(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    cid = entry.entry_id

    def get_st(uid_tmpl: str) -> str:
        s = _get_entity_state(hass, uid_tmpl.format(cid))
        return s.state if s is not None else "missing"

    # Step 0: User sets delay on HA number entity
    delay_ent = _get_entity_state(hass, UNIQUE_ID_WASH_DELAY_NUMBER.format(cid))
    assert delay_ent is not None
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_ent.entity_id, "value": 120},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Step 1: Programmed delay (MachMode=5, DelVal=120, RemTime=0)
    st1 = _build_status(
        MachineState.DELAYED_START_PROGRAMMED,
        WashProgramState.STOPPED,
        0,
        0,
        delay_value=120,
    )
    coordinator.async_set_updated_data(st1)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Delayed start programmed"
    assert get_st(UNIQUE_ID_WASH_SCHEDULED_START) != "unavailable"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) == "unavailable"
    assert get_st(UNIQUE_ID_WASH_STOP_BUTTON) != "unavailable"

    # Step 2: Delay countdown advances (DelVal=60)
    st2 = _build_status(
        MachineState.DELAYED_START_PROGRAMMED,
        WashProgramState.STOPPED,
        0,
        0,
        delay_value=60,
    )
    coordinator.async_set_updated_data(st2)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASH_SCHEDULED_START) != "unavailable"

    # Step 3: Delay reaches 0, machine automatically begins washing
    st3 = _build_status(
        MachineState.RUNNING, WashProgramState.WASH, 60, 50, delay_value=0
    )
    coordinator.async_set_updated_data(st3)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Running"
    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Wash"
    assert get_st(UNIQUE_ID_WASH_REMAINING_TIME) == "60"
    assert get_st(UNIQUE_ID_WASH_SCHEDULED_START) == "unavailable"


# ---------------------------------------------------------------------------
# Test 3: Pause and Resume Trajectory
# ---------------------------------------------------------------------------


async def test_pause_and_resume_trajectory(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Validate entity availability transitions across RUNNING -> PAUSED -> RUNNING."""
    entry = await _setup_washer(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    cid = entry.entry_id

    def get_st(uid_tmpl: str) -> str:
        s = _get_entity_state(hass, uid_tmpl.format(cid))
        return s.state if s is not None else "missing"

    # Step 1: Active Running
    st1 = _build_status(MachineState.RUNNING, WashProgramState.WASH, 40, 50)
    coordinator.async_set_updated_data(st1)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Running"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) != "unavailable"
    assert get_st(UNIQUE_ID_WASH_RESUME_BUTTON) == "unavailable"

    # Step 2: Machine paused (door open or user pressed pause)
    st2 = _build_status(MachineState.PAUSED, WashProgramState.WASH, 40, 50)
    coordinator.async_set_updated_data(st2)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Paused"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) == "unavailable"
    assert get_st(UNIQUE_ID_WASH_RESUME_BUTTON) != "unavailable"

    # Step 3: Resumed back to running
    st3 = _build_status(MachineState.RUNNING, WashProgramState.WASH, 39, 50)
    coordinator.async_set_updated_data(st3)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASHING_MACHINE) == "Running"
    assert get_st(UNIQUE_ID_WASH_PAUSE_BUTTON) != "unavailable"
    assert get_st(UNIQUE_ID_WASH_RESUME_BUTTON) == "unavailable"


# ---------------------------------------------------------------------------
# Test 4: Good Night Rinse Hold Trajectory
# ---------------------------------------------------------------------------


async def test_good_night_rinse_hold_trajectory(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Validate Rinse Hold detection (PrPh=9) and dedicated resume button availability."""
    entry = await _setup_washer(hass, aioclient_mock)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    cid = entry.entry_id

    def get_st(uid_tmpl: str) -> str:
        s = _get_entity_state(hass, uid_tmpl.format(cid))
        return s.state if s is not None else "missing"

    # Step 1: Wash progresses into Rinse Hold phase (PrPh=9, MachMode=2)
    st1 = _build_status(MachineState.RUNNING, WashProgramState.GOOD_NIGHT, 15, 80)
    coordinator.async_set_updated_data(st1)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Good Night rinse hold"
    assert get_st(UNIQUE_ID_WASH_RESUME_GOOD_NIGHT) != "unavailable"
    # Standard resume button is unavailable because machine state is RUNNING, not PAUSED
    assert get_st(UNIQUE_ID_WASH_RESUME_BUTTON) == "unavailable"

    # Step 2: Good Night Resume triggered, machine finishes drain and spin
    st2 = _build_status(MachineState.RUNNING, WashProgramState.SPIN, 8, 0)
    coordinator.async_set_updated_data(st2)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_WASH_CYCLE_STATUS) == "Spin"
    assert get_st(UNIQUE_ID_WASH_RESUME_GOOD_NIGHT) == "unavailable"


# ---------------------------------------------------------------------------
# Test 5: Tumble Dryer DualTech Trajectory
# ---------------------------------------------------------------------------


async def test_tumble_dryer_dualtech_trajectory(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Validate complete tumble dryer trajectory from IDLE -> RUNNING -> Cool-down -> Finished."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-td-trajectory",
        data={
            "ip_address": TEST_IP,
            "use_encryption": False,
            "password": "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "TD_DIGIT_HP_DOOR",
            CONF_KEY_PROGRAMS: _DRYER_PROGRAMS_LIST,
        },
    )

    idle_td_json = """{
      "statusTD": {
        "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
        "RemTime": "120", "DryLev": "2", "Time": "0", "Rapido": "0",
        "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
        "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
      }
    }"""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=idle_td_json
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    cid = entry.entry_id

    def get_st(uid_tmpl: str) -> str:
        s = _get_entity_state(hass, uid_tmpl.format(cid))
        return s.state if s is not None else "missing"

    # Step 0: IDLE
    assert get_st(UNIQUE_ID_TUMBLE_DRYER) == "Idle"
    assert get_st(UNIQUE_ID_TUMBLE_CYCLE_STATUS) == "Hang Dry"

    # Step 1: Active Drying (StatoTD=2, PrPh=2, RemTime=85)
    td1 = copy.copy(coordinator.data)
    td1.machine_state = MachineState.RUNNING
    td1.program_state = DryerProgramState.RUNNING
    td1.remaining_minutes = 85
    coordinator.async_set_updated_data(td1)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_TUMBLE_DRYER) == "Running"
    assert get_st(UNIQUE_ID_TUMBLE_CYCLE_STATUS) == "Running"
    assert get_st(UNIQUE_ID_TUMBLE_REMAINING_TIME) == "85"

    # Step 2: Cool-down Phase (StatoTD=6, PrPh=2, RemTime=10)
    td2 = copy.copy(td1)
    td2.remaining_minutes = 10
    coordinator.async_set_updated_data(td2)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_TUMBLE_REMAINING_TIME) == "10"

    # Step 3: Anti-Crease Phase (StatoTD=2, PrPh=3, RemTime=0)
    td3 = copy.copy(td1)
    td3.program_state = DryerProgramState.END
    td3.remaining_minutes = 0
    coordinator.async_set_updated_data(td3)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_TUMBLE_CYCLE_STATUS) == "End"
    assert get_st(UNIQUE_ID_TUMBLE_REMAINING_TIME) == "0"

    # Step 4: Finished (StatoTD=8 FINISHED1)
    td4 = copy.copy(td3)
    td4.machine_state = MachineState.FINISHED1
    coordinator.async_set_updated_data(td4)
    await hass.async_block_till_done()

    assert get_st(UNIQUE_ID_TUMBLE_DRYER) == "Finished"
