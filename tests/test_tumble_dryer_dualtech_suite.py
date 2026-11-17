"""Comprehensive dedicated test suite for Standalone Tumble Dryer DualTech interfaces.

Authoritative coverage for:
1. End-to-End FSM state machine transitions:
   - IDLE -> DELAYED_START -> CANCEL DELAY -> IDLE
   - IDLE -> RUNNING -> PAUSED -> RESUMED -> FINISHED / ANTI-CREASE -> IDLE
2. Diagnostic Clever Check-Up lifecycle & automatic hardware reset:
   - IDLE dispatch (Write=1&CheckUpState=1)
   - Running telemetry verification
   - Completion auto-reset dispatch (Write=1&CheckUpState=0) & notification
   - Door open safety gating
3. Hardware maintenance warnings & microswitch alerts:
   - CleanFilter ("1") alert, binary sensor, persistent notification
   - WaterTankFull ("1") alert, binary sensor, persistent notification
   - ResetWarnings button dispatch (Write=1&ResetWarnings=1)
   - Automatic notification dismissal when flags clear
4. Fault codes & diagnostic sensors:
   - Error code normalization & localized attribute description (E03, E05, E07, E08, E10, E13, E14)
   - Persistent notification creation and dismissal
5. Program combinations, timed dry vs dry level exclusivity, fixed cycles:
   - Timed start wire grammar (Time=XX, no DryLev)
   - Standard dry level wire grammar (DryLev=X, no Time)
   - Delayed start wire grammar (DelMd=1&DelVl=XX, no StSt)
   - Fixed program fallback (Wool with no settable dry level/time)
   - Timed-only program gating (Antiallergy with set_time_level=1, set_dry_level=0)
6. Safety & Remote Control invariants:
   - Door open gating
   - Remote control disabled gating
   - DualTech command settling delay (15 seconds)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client import parse_dryer_programs
from custom_components.candy.client.model import TumbleDryerProgram, TumbleDryerStatus
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_TUMBLE_DRYER,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
    NOTIF_ID_DRYER_ERROR,
    NOTIF_ID_DRYER_FILTER,
    NOTIF_ID_DRYER_WATER_TANK,
    NOTIF_ID_FULL_CHECKUP,
    UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON,
    UNIQUE_ID_TUMBLE_CHECKUP_BUTTON,
    UNIQUE_ID_TUMBLE_CHECKUP_STATE,
    UNIQUE_ID_TUMBLE_CLEAN_FILTER,
    UNIQUE_ID_TUMBLE_DELAY,
    UNIQUE_ID_TUMBLE_DELAY_NUMBER,
    UNIQUE_ID_TUMBLE_DOOR,
    UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_TUMBLE_ERROR,
    UNIQUE_ID_TUMBLE_PAUSE_BUTTON,
    UNIQUE_ID_TUMBLE_PROGRAM_SELECT,
    UNIQUE_ID_TUMBLE_RAPID_SELECT,
    UNIQUE_ID_TUMBLE_REMAINING_TIME,
    UNIQUE_ID_TUMBLE_REMOTE_CONTROL,
    UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON,
    UNIQUE_ID_TUMBLE_RESUME_BUTTON,
    UNIQUE_ID_TUMBLE_START_BUTTON,
    UNIQUE_ID_TUMBLE_STOP_BUTTON,
    UNIQUE_ID_TUMBLE_TIME_SELECT,
    UNIQUE_ID_TUMBLE_WATER_TANK,
)
from custom_components.candy.helpers import command_settling_delay, is_dualtech_dryer

from .common import TEST_IP

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_serial_35_catalog() -> dict:
    with open(
        _FIXTURES_DIR / "catalog_serial_35_tumble_dryer.json", encoding="utf-8"
    ) as f:
        return json.load(f)


def _build_status_td(
    stato_td: str = "1",
    pr_ph: str = "0",
    pr: str = "1",
    rem_time: str = "150",
    dry_lev: str = "3",
    dm_level: str = "3",
    time: str = "0",
    rapido: str = "0",
    refresh: str = "0",
    clean_filter: str = "0",
    water_tank: str = "0",
    door: str = "1",
    wifi: str = "1",
    error: str = "0",
    del_val: str = "0",
    checkup: str = "0",
    recipe_id: str = "NULL",
) -> str:
    payload = {
        "statusTD": {
            "StatoWiFi": wifi,
            "StatoTD": stato_td,
            "CodiceErrore": error,
            "Pr": pr,
            "PrPh": pr_ph,
            "RemTime": rem_time,
            "DryLev": dry_lev,
            "Time": time,
            "Rapido": rapido,
            "Refresh": refresh,
            "CleanFilter": clean_filter,
            "WaterTankFull": water_tank,
            "DryingManagerLevel": dm_level,
            "DelVal": del_val,
            "DoorState": door,
            "RecipeId": recipe_id,
            "CheckUpState": checkup,
        }
    }
    return json.dumps(payload)


async def _setup_dualtech_dryer(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    interface_type: str = "TD_DIGIT_HP_DOOR",
) -> tuple[MockConfigEntry, list[TumbleDryerProgram]]:
    catalog = _load_serial_35_catalog()
    programs = catalog["programs"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-standalone-tumble-dryer-dualtech",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: programs,
            CONF_KEY_INTERFACE_TYPE: interface_type,
            CONF_KEY_IS_TUMBLE_DRYER: True,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    parsed = parse_dryer_programs(programs)
    return entry, parsed


def _get_entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, template: str
) -> str:
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id(
        platform, DOMAIN, template.format(entry.entry_id)
    )
    assert eid is not None, f"Could not find entity {platform}.{template}"
    return eid


def _update_coordinator_status(
    hass: HomeAssistant, entry: MockConfigEntry, status_json: str
) -> None:
    data = json.loads(status_json)["statusTD"]
    status = TumbleDryerStatus.from_json(data)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    coordinator.async_set_updated_data(status)


# ===========================================================================
# 1. Full FSM State Machine Lifecycle & Delayed Start Cancellation
# ===========================================================================


async def test_dualtech_dryer_fsm_lifecycle_and_delay_cancellation(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify complete FSM progression: Idle -> Delayed -> Cancel Delay -> Running -> Pause -> Resume -> Finish -> Anti-Crease."""
    init_json = _build_status_td(stato_td="1", pr_ph="0", rem_time="150")
    entry, _ = await _setup_dualtech_dryer(hass, aioclient_mock, init_json)

    start_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_START_BUTTON)
    stop_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_STOP_BUTTON)
    pause_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_PAUSE_BUTTON)
    resume_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_RESUME_BUTTON)
    anticrease_eid = _get_entity_id(
        hass, entry, "button", UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON
    )
    delay_eid = _get_entity_id(hass, entry, "number", UNIQUE_ID_TUMBLE_DELAY_NUMBER)
    sensor_eid = _get_entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_DRYER)
    rem_eid = _get_entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_REMAINING_TIME)

    # 1. Initial IDLE state
    assert hass.states.get(sensor_eid).state == "Idle"
    assert hass.states.get(start_eid).state != "unavailable"
    assert hass.states.get(stop_eid).state == "unavailable"
    assert hass.states.get(pause_eid).state == "unavailable"
    assert hass.states.get(resume_eid).state == "unavailable"
    assert hass.states.get(anticrease_eid).state == "unavailable"

    # 2. Schedule Delayed Start: Delay 120 minutes
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid, "value": 120}, blocking=True
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params["Write"] == "1"
    assert params["DelMd"] == "1"
    assert params["DelVl"] == "120"
    assert params["PrNm"] == "1"
    assert "StSt" not in params

    # 3. Hardware transitions to DELAYED_START_PROGRAMMED (StatoTD: 5)
    delayed_json = _build_status_td(stato_td="5", pr_ph="0", del_val="120")
    _update_coordinator_status(hass, entry, delayed_json)
    await hass.async_block_till_done()

    assert hass.states.get(sensor_eid).state == "Delayed start programmed"
    assert hass.states.get(rem_eid).state == "0"
    assert hass.states.get(start_eid).state == "unavailable"
    assert hass.states.get(stop_eid).state != "unavailable"
    delay_sensor_eid = _get_entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_DELAY)
    assert hass.states.get(delay_sensor_eid).state == "120"
    assert hass.states.get(sensor_eid).attributes.get("delay_value") == 120

    # 4. Cancel Delayed Start via Stop button
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": stop_eid}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    stop_params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert stop_params["Write"] == "1"
    assert stop_params["StSt"] == "0"
    assert stop_params["DelMd"] == "0"
    assert stop_params["PrNm"] == "1"

    # 5. Dryer starts Running (StatoTD: 2, PrPh: 2)
    running_json = _build_status_td(stato_td="2", pr_ph="2", rem_time="115")
    _update_coordinator_status(hass, entry, running_json)
    await hass.async_block_till_done()

    assert hass.states.get(sensor_eid).state == "Running"
    assert hass.states.get(rem_eid).state == "115"
    assert hass.states.get(start_eid).state == "unavailable"
    assert hass.states.get(stop_eid).state != "unavailable"
    assert hass.states.get(pause_eid).state != "unavailable"
    assert hass.states.get(resume_eid).state == "unavailable"

    # 6. Pause cycle
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": pause_eid}, blocking=True
        )

    assert mock_send.called
    assert "SetPauseDryMgr=1" in mock_send.call_args[0][0]

    # Hardware transitions to PAUSED (StatoTD: 3)
    paused_json = _build_status_td(stato_td="3", pr_ph="2", rem_time="115")
    _update_coordinator_status(hass, entry, paused_json)
    await hass.async_block_till_done()

    assert hass.states.get(sensor_eid).state == "Paused"
    assert hass.states.get(pause_eid).state == "unavailable"
    assert hass.states.get(resume_eid).state != "unavailable"

    # 7. Resume cycle
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": resume_eid}, blocking=True
        )

    assert mock_send.called
    assert "SetRestartDryMgr=1" in mock_send.call_args[0][0]

    # 8. Cycle Completes -> FINISHED with Anti-Crease Active (StatoTD: 8, PrPh: 3, Refresh: 1)
    finished_json = _build_status_td(stato_td="8", pr_ph="3", rem_time="0", refresh="1")
    _update_coordinator_status(hass, entry, finished_json)
    await hass.async_block_till_done()

    assert hass.states.get(sensor_eid).state == "Finished"
    assert hass.states.get(anticrease_eid).state != "unavailable"

    # 9. Cancel Anti-Crease tumbling
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": anticrease_eid}, blocking=True
        )

    assert mock_send.called
    assert "DontTumbling=1" in mock_send.call_args[0][0]


# ===========================================================================
# 2. Clever Check-Up Diagnostic Lifecycle & Auto Hardware Reset
# ===========================================================================


async def test_dualtech_dryer_checkup_lifecycle_and_auto_reset(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify diagnostic checkup dispatch, running telemetry, and auto-reset Write=1&CheckUpState=0 on completion."""
    init_json = _build_status_td(stato_td="1", checkup="0")
    entry, _ = await _setup_dualtech_dryer(hass, aioclient_mock, init_json)

    checkup_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_CHECKUP_BUTTON)
    checkup_state_eid = _get_entity_id(
        hass, entry, "sensor", UNIQUE_ID_TUMBLE_CHECKUP_STATE
    )

    # 1. Start Check-Up
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": checkup_eid}, blocking=True
        )

    assert mock_send.called
    assert "CheckUpState=1" in mock_send.call_args[0][0]

    # 2. Check-Up Running in Telemetry (StatoTD: 6, CheckUpState: 1)
    running_checkup_json = _build_status_td(stato_td="6", checkup="1")
    _update_coordinator_status(hass, entry, running_checkup_json)
    await hass.async_block_till_done()

    assert hass.states.get(checkup_state_eid).state == "Running"

    # 3. Check-Up Finished (CheckUpState: 2) -> HA listener must notify and send CheckUpState=0
    completed_checkup_json = _build_status_td(stato_td="1", checkup="2")
    with (
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_reset_send,
        patch("custom_components.candy.pn_async_create") as mock_notif,
    ):
        _update_coordinator_status(hass, entry, completed_checkup_json)
        await hass.async_block_till_done()
        await asyncio.sleep(0.01)

    assert mock_notif.called
    notif_id = mock_notif.call_args[1].get("notification_id")
    assert notif_id == NOTIF_ID_FULL_CHECKUP.format(entry.entry_id)

    assert mock_reset_send.called
    assert "CheckUpState=0" in mock_reset_send.call_args[0][0]


async def test_dualtech_dryer_checkup_door_open_safety_gating(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Check-Up button must be unavailable when the door is open."""
    door_open_json = _build_status_td(stato_td="1", door="0")
    entry, _ = await _setup_dualtech_dryer(hass, aioclient_mock, door_open_json)

    checkup_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_CHECKUP_BUTTON)
    door_bin_eid = _get_entity_id(hass, entry, "binary_sensor", UNIQUE_ID_TUMBLE_DOOR)

    assert hass.states.get(door_bin_eid).state == "on"
    assert hass.states.get(checkup_eid).state == "unavailable"


# ===========================================================================
# 3. Hardware Warnings (CleanFilter, WaterTankFull) & Persistent Notifications
# ===========================================================================


async def test_dualtech_dryer_warning_notifications_and_reset_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify CleanFilter and WaterTankFull triggers create notifications and enable Reset Warnings button."""
    clean_json = _build_status_td(clean_filter="0", water_tank="0")
    entry, _ = await _setup_dualtech_dryer(hass, aioclient_mock, clean_json)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    reset_eid = _get_entity_id(
        hass, entry, "button", UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON
    )
    filter_bin_eid = _get_entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_TUMBLE_CLEAN_FILTER
    )
    tank_bin_eid = _get_entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_TUMBLE_WATER_TANK
    )

    # Initial: healthy
    assert hass.states.get(reset_eid).state == "unavailable"
    assert hass.states.get(filter_bin_eid).state == "off"
    assert hass.states.get(tank_bin_eid).state == "off"

    # Both warnings active via coordinator refresh
    warn_json = _build_status_td(clean_filter="1", water_tank="1")
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=warn_json)
    with patch("custom_components.candy.pn_async_create") as mock_notif:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert mock_notif.call_count == 2
    created_notifs = {c[1]["notification_id"] for c in mock_notif.call_args_list}
    assert NOTIF_ID_DRYER_FILTER.format(entry.entry_id) in created_notifs
    assert NOTIF_ID_DRYER_WATER_TANK.format(entry.entry_id) in created_notifs

    assert hass.states.get(reset_eid).state != "unavailable"
    assert hass.states.get(filter_bin_eid).state == "on"
    assert hass.states.get(tank_bin_eid).state == "on"

    # Press Reset Warnings
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": reset_eid}, blocking=True
        )

    assert mock_send.called
    assert "ResetWarnings=1" in mock_send.call_args[0][0]

    # Hardware clears warnings -> Notifications dismissed
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=clean_json)
    with patch("custom_components.candy.pn_async_dismiss") as mock_dismiss:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert mock_dismiss.call_count == 2
    dismissed_ids = {c[0][1] for c in mock_dismiss.call_args_list}
    assert NOTIF_ID_DRYER_FILTER.format(entry.entry_id) in dismissed_ids
    assert NOTIF_ID_DRYER_WATER_TANK.format(entry.entry_id) in dismissed_ids

    assert hass.states.get(reset_eid).state == "unavailable"


# ===========================================================================
# 4. Fault Code Diagnostics & Error Description Attributes
# ===========================================================================


@pytest.mark.parametrize(
    ("error_code", "expected_code_str"),
    [
        ("E03", "E03"),
        ("E05", "E05"),
        ("E07", "E07"),
        ("E08", "E08"),
        ("E10", "E10"),
        ("E13", "E13"),
        ("E14", "E14"),
    ],
)
async def test_dualtech_dryer_error_codes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    error_code: str,
    expected_code_str: str,
) -> None:
    """Verify fault codes report to diagnostic error sensor with localized description and error notification."""
    init_json = _build_status_td(error="0")
    entry, _ = await _setup_dualtech_dryer(hass, aioclient_mock, init_json)

    error_eid = _get_entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_ERROR)
    main_eid = _get_entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_DRYER)

    err_json = _build_status_td(stato_td="7", error=error_code)
    with patch("custom_components.candy.pn_async_create") as mock_notif:
        _update_coordinator_status(hass, entry, err_json)
        await hass.async_block_till_done()

    assert hass.states.get(main_eid).state == "Error"
    err_state = hass.states.get(error_eid)
    assert err_state.state == expected_code_str
    assert "description" in err_state.attributes
    assert len(err_state.attributes["description"]) > 0

    assert mock_notif.called
    assert mock_notif.call_args[1]["notification_id"] == NOTIF_ID_DRYER_ERROR.format(
        entry.entry_id
    )


# ===========================================================================
# 5. Program Combinations: Fixed Cycles, Timed-only, & Exclusivity
# ===========================================================================


async def test_dualtech_dryer_fixed_cycle_wool_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify fixed programs with set_dry_level=0 & set_time_level=0 (Wool) default gracefully and send standard start."""
    init_json = _build_status_td(stato_td="1")
    entry, programs = await _setup_dualtech_dryer(hass, aioclient_mock, init_json)

    wool = next(p for p in programs if "WOOL" in p.name.upper())
    assert not wool.set_dry_level
    assert not wool.set_time_level

    prog_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
    level_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT)
    time_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_TIME_SELECT)
    start_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_START_BUTTON)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": wool.localized_name("en")},
        blocking=True,
    )

    # Both dry level and time selects must be unavailable for Wool
    assert hass.states.get(level_eid).state == "unavailable"
    assert hass.states.get(time_eid).state == "unavailable"

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params["Write"] == "1"
    assert params["PrNm"] == str(wool.selector_position)
    assert params["StSt"] == "1"
    # Fallback dry level (1) dispatched when both are unconfigurable
    assert params["DryLev"] == "1"
    assert "Time" not in params


async def test_dualtech_dryer_timed_only_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify timed-only program (Antiallergy) omits 'off' and dispatches timed start."""
    init_json = _build_status_td(stato_td="1")
    entry, programs = await _setup_dualtech_dryer(hass, aioclient_mock, init_json)

    antiallergy = next(p for p in programs if "ANTIALLERGY" in p.name.upper())
    assert not antiallergy.set_dry_level
    assert antiallergy.set_time_level

    prog_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
    level_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT)
    time_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_TIME_SELECT)
    start_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_START_BUTTON)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": antiallergy.localized_name("en")},
        blocking=True,
    )

    assert hass.states.get(level_eid).state == "unavailable"
    time_state = hass.states.get(time_eid)
    assert time_state.state not in ("unavailable", "unknown")
    assert "off" not in time_state.attributes.get("options", [])

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": time_eid, "option": "45"},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params["Write"] == "1"
    assert params["PrNm"] == str(antiallergy.selector_position)
    assert params["Time"] == "45"
    assert params["StSt"] == "1"
    assert "DryLev" not in params


# ===========================================================================
# 6. Safety, Protocol & Settling Delay Invariants
# ===========================================================================


def test_dualtech_dryer_settling_delay_and_interface_detection() -> None:
    """Verify settling delay is strictly 15s across all DualTech dryer interface families."""
    for iface in (
        "TD_DIGIT_HP_DOOR",
        "TD_DIGIT_HY_DOOR",
        "TD_DIGIT_TC_DOOR",
        "TD_DIGIT_1",
        "TD_LED_3",
        "3D_DUAL",
    ):
        assert is_dualtech_dryer(iface) is True
        assert command_settling_delay(iface) == 15

    for non_dryer_iface in ("RAPIDO_4DIG_STM", "BIANCA_TOUCH", "UNKNOWN"):
        assert is_dualtech_dryer(non_dryer_iface) is False


async def test_dualtech_dryer_remote_control_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When StatoWiFi is 0 (local manual dial or remote off), all write entities are unavailable."""
    remote_off_json = _build_status_td(wifi="0")
    entry, _ = await _setup_dualtech_dryer(hass, aioclient_mock, remote_off_json)

    remote_bin_eid = _get_entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_TUMBLE_REMOTE_CONTROL
    )
    assert hass.states.get(remote_bin_eid).state == "off"

    for platform, tpl in (
        ("button", UNIQUE_ID_TUMBLE_START_BUTTON),
        ("button", UNIQUE_ID_TUMBLE_STOP_BUTTON),
        ("button", UNIQUE_ID_TUMBLE_PAUSE_BUTTON),
        ("button", UNIQUE_ID_TUMBLE_RESUME_BUTTON),
        ("button", UNIQUE_ID_TUMBLE_CHECKUP_BUTTON),
        ("button", UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON),
        ("select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT),
        ("select", UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT),
        ("select", UNIQUE_ID_TUMBLE_TIME_SELECT),
        ("number", UNIQUE_ID_TUMBLE_DELAY_NUMBER),
    ):
        eid = _get_entity_id(hass, entry, platform, tpl)
        assert hass.states.get(eid).state == "unavailable"


async def test_dualtech_dryer_sensor_telemetry_attributes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify delay_value, time, and recipe_id attributes and delay sensor entity."""
    status_json = _build_status_td(
        stato_td="2",
        pr_ph="2",
        time="60",
        del_val="0",
        recipe_id="D_123",
    )
    entry, _ = await _setup_dualtech_dryer(hass, aioclient_mock, status_json)

    sensor_eid = _get_entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_DRYER)
    delay_eid = _get_entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_DELAY)

    attrs = hass.states.get(sensor_eid).attributes
    assert attrs.get("time") == 60
    assert attrs.get("recipe_id") == "D_123"
    assert attrs.get("delay_value") == 0

    assert hass.states.get(delay_eid).state == "0"
    assert hass.states.get(delay_eid).attributes.get("unit_of_measurement") == "min"
    assert hass.states.get(delay_eid).attributes.get("device_class") == "duration"


async def test_dualtech_dryer_rapid_dry_capability_and_commands(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Rapid Dry select entity availability, option filtering, and start dispatch."""
    init_json = _build_status_td(stato_td="1")
    entry, programs = await _setup_dualtech_dryer(hass, aioclient_mock, init_json)

    prog_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
    rapid_eid = _get_entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_RAPID_SELECT)
    start_eid = _get_entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_START_BUTTON)
    delay_eid = _get_entity_id(hass, entry, "number", UNIQUE_ID_TUMBLE_DELAY_NUMBER)

    # 1. Whites program (selector_position 1): supports rapid dry (set_rapido: 1)
    whites = next(p for p in programs if p.selector_position == 1)
    assert whites.set_rapido is True

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": whites.localized_name("en")},
        blocking=True,
    )

    rapid_state = hass.states.get(rapid_eid)
    assert rapid_state.state == "off"
    assert rapid_state.attributes.get("options") == ["off", "30", "45", "59"]

    # 2. Select 45 minutes rapid dry and start
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": rapid_eid, "option": "45"},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params["Write"] == "1"
    assert params["PrNm"] == "1"
    assert params["Rapido"] == "2"
    assert params["StSt"] == "1"
    assert "DryLev" not in params
    assert "Time" not in params

    # 3. Rapid dry with Delayed Start (120 minutes)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid, "value": 120}, blocking=True
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params["Write"] == "1"
    assert params["PrNm"] == "1"
    assert params["Rapido"] == "2"
    assert params["DelMd"] == "1"
    assert params["DelVl"] == "120"
    assert "StSt" not in params

    # 4. Switch to Wool program (selector_position 11): set_rapido is False
    wool = next(p for p in programs if "WOOL" in p.name.upper())
    assert wool.set_rapido is False

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": wool.localized_name("en")},
        blocking=True,
    )

    assert hass.states.get(rapid_eid).state == "unavailable"
