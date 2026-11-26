"""Tests for the dishwasher remote controls (start/stop/pause/resume and settings)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN, _make_off_status
from custom_components.candy.button import DishwasherMaintResetButton
from custom_components.candy.client import (
    LegacyTouchDishwasherCommandBuilder,
    ModernDishwasherCommandBuilder,
    get_dishwasher_command_builder,
    is_open_door_supported,
)
from custom_components.candy.client.model import (
    DishwasherProgramPhase,
    DishwasherStatus,
    MachineState,
)
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH,
    UNIQUE_ID_DISHWASHER_BUZZER,
    UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON,
    UNIQUE_ID_DISHWASHER_CYCLE_STATUS,
    UNIQUE_ID_DISHWASHER_DELAY_NUMBER,
    UNIQUE_ID_DISHWASHER_DOOR,
    UNIQUE_ID_DISHWASHER_ECO_SWITCH,
    UNIQUE_ID_DISHWASHER_ERROR,
    UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH,
    UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH,
    UNIQUE_ID_DISHWASHER_LIFETIME_CYCLES,
    UNIQUE_ID_DISHWASHER_MAINT_CLEAN,
    UNIQUE_ID_DISHWASHER_OPEN_DOOR_BUTTON,
    UNIQUE_ID_DISHWASHER_PAUSE_BUTTON,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
    UNIQUE_ID_DISHWASHER_REMOTE_CONTROL,
    UNIQUE_ID_DISHWASHER_RESUME_BUTTON,
    UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY,
    UNIQUE_ID_DISHWASHER_SALT_EMPTY,
    UNIQUE_ID_DISHWASHER_START_BUTTON,
    UNIQUE_ID_DISHWASHER_STOP_BUTTON,
    UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH,
    UNIQUE_ID_DISHWASHER_WATER_HARDNESS,
)

from .common import init_integration

_READY = "dishwasher/remote_ready.json"
_RUNNING = "dishwasher/remote_running.json"

_PANEL_START = (
    "DelayStart=0&ExtraDry=0&TreinUno=0&Eco=0&Program=P17"
    "&MetaCarico=0&OpzProg=0&w1=3&StartStop=1"
)


def _fixture(name: str, **overrides: str) -> str:
    data = json.loads(load_fixture(name))
    data["statusDWash"].update(overrides)
    return json.dumps(data)


def _status(name: str, **overrides: str) -> DishwasherStatus:
    return DishwasherStatus.from_json(
        json.loads(_fixture(name, **overrides))["statusDWash"]
    )


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, unique_id.format(entry.entry_id)
    )
    assert entity_id is not None
    return entity_id


def _state(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str:
    state = hass.states.get(_entity_id(hass, entry, domain, unique_id))
    assert state is not None
    return state.state


async def _call(hass: HomeAssistant, domain: str, service: str, data: dict) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)


async def _press_start(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    return await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)


async def _press(hass: HomeAssistant, entry: MockConfigEntry, unique_id: str) -> str:
    with (
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("custom_components.candy.button.asyncio.sleep", new_callable=AsyncMock),
    ):
        await _call(
            hass,
            "button",
            "press",
            {"entity_id": _entity_id(hass, entry, "button", unique_id)},
        )
    mock_send.assert_called_once()
    return mock_send.call_args[0][0]


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


async def test_entities_created_in_read_only_mode(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    for domain, unique_id in [
        ("button", UNIQUE_ID_DISHWASHER_START_BUTTON),
        ("button", UNIQUE_ID_DISHWASHER_STOP_BUTTON),
        ("button", UNIQUE_ID_DISHWASHER_PAUSE_BUTTON),
        ("button", UNIQUE_ID_DISHWASHER_RESUME_BUTTON),
        ("button", UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON),
        ("select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT),
        ("switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH),
        ("switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH),
        ("switch", UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH),
        ("switch", UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH),
        ("number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_SALT_EMPTY),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_DOOR),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_REMOTE_CONTROL),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_MAINT_CLEAN),
        ("sensor", UNIQUE_ID_DISHWASHER_ERROR),
        ("sensor", UNIQUE_ID_DISHWASHER_CYCLE_STATUS),
        ("sensor", UNIQUE_ID_DISHWASHER_WATER_HARDNESS),
        ("sensor", UNIQUE_ID_DISHWASHER_BUZZER),
        ("sensor", UNIQUE_ID_DISHWASHER_LIFETIME_CYCLES),
    ]:
        _entity_id(hass, entry, domain, unique_id)


async def test_status_sensors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(
            _READY,
            MissSalt="1",
            OpenDoor="1",
            CodiceErrore="E4",
            r9="H_1",
            r6="2",
            r7="3",
            r8="120",
        ),
    )

    assert _state(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_SALT_EMPTY) == "on"
    assert (
        _state(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY)
        == "off"
    )
    assert _state(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_DOOR) == "on"
    assert (
        _state(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_REMOTE_CONTROL)
        == "on"
    )
    assert (
        _state(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_MAINT_CLEAN) == "on"
    )
    assert _state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_ERROR) == "E4"
    assert _state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_BUZZER) == "2"
    assert _state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_WATER_HARDNESS) == "3"
    assert _state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_LIFETIME_CYCLES) == "120"


async def test_settings_default_to_panel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, TreinUno="1", MetaCarico="1", ExtraDry="0"),
    )

    assert _state(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT) == "panel"
    assert _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH) == "off"
    assert (
        _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH) == "on"
    )
    assert _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH) == "on"
    assert _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH) == "off"
    assert float(_state(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)) == 0


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


async def test_start_available_when_ready(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) != (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_STOP_BUTTON) == (
        "unavailable"
    )


async def test_start_available_with_stale_delay(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DelayStart keeps its last value after a stop: only StartStop matters."""
    entry = await init_integration(
        hass, aioclient_mock, _fixture(_READY, DelayStart="60")
    )

    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) != (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_STOP_BUTTON) == (
        "unavailable"
    )


async def test_start_available_with_stale_start_stop(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """StartStop can stay 1 on a ready machine: it must not block Start."""
    entry = await init_integration(
        hass, aioclient_mock, _fixture(_READY, StartStop="1", StatoDWash="2", r2="0")
    )

    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) != (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_STOP_BUTTON) == (
        "unavailable"
    )


async def test_cycle_started_from_panel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """A cycle started from the panel reports StartStop=0 while running."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, StatoDWash="3", StartStop="0", r2="2", RemTime="115"),
    )

    assert hass.states.get("sensor.dishwasher").state == "Running"
    assert hass.states.get("sensor.dishwasher_cycle_status").state == "Wash"
    assert hass.states.get("sensor.dishwasher_remaining_time").state == "115"
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) == (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_STOP_BUTTON) != (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_PAUSE_BUTTON) != (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_RESUME_BUTTON) == (
        "unavailable"
    )


async def test_buttons_unavailable_without_remote_control(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass, aioclient_mock, _fixture(_READY, StatoWiFi="0")
    )

    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) == (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_STOP_BUTTON) == (
        "unavailable"
    )
    # Settings can still be prepared before enabling remote control
    assert _state(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT) != (
        "unavailable"
    )


async def test_start_unavailable_when_door_open(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, _fixture(_READY, OpenDoor="1"))

    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) == (
        "unavailable"
    )


async def test_running(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_RUNNING))

    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) == (
        "unavailable"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_STOP_BUTTON) != (
        "unavailable"
    )
    assert _state(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT) == (
        "unavailable"
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def test_start_with_panel_settings(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    assert await _press_start(hass, entry) == _PANEL_START


async def test_start_with_chosen_settings(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, _fixture(_READY, TreinUno="1"))
    select = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    eco = _entity_id(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH)
    three_in_one = _entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH
    )
    delay = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)

    await _call(
        hass, "select", "select_option", {"entity_id": select, "option": "rapid_24"}
    )
    await _call(hass, "switch", "turn_on", {"entity_id": eco})
    await _call(hass, "switch", "turn_off", {"entity_id": three_in_one})
    await _call(hass, "number", "set_value", {"entity_id": delay, "value": 90})

    assert await _press_start(hass, entry) == (
        "DelayStart=90&ExtraDry=0&TreinUno=0&Eco=1&Program=P20"
        "&MetaCarico=0&OpzProg=4&w1=8&StartStop=1"
    )
    assert hass.states.get(select).state == "rapid_24"


async def test_stop_sends_reset(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_RUNNING))

    assert await _press(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON) == "Reset=1"


async def test_pause_and_resume(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, StatoDWash="3", StartStop="1", r2="2"),
    )

    assert await _press(hass, entry, UNIQUE_ID_DISHWASHER_PAUSE_BUTTON) == "Pa=1"

    # Simulate paused status
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        "http://192.168.0.66/http-read.json?encrypted=0",
        text=_fixture(_READY, StatoDWash="4", StartStop="1", r2="2"),
    )
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    await coordinator.async_refresh()

    assert await _press(hass, entry, UNIQUE_ID_DISHWASHER_RESUME_BUTTON) == "Pa=0"


async def test_checkup_button(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    assert (
        await _press(hass, entry, UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON)
        == "StartCheckUp=1"
    )


async def test_open_door_button_on_od_interface(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, StatoDWash="5", r2="5"),
        extra_config_data={"interface_type": "BRAVA_BI_DIGIT_OD"},
    )
    assert _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH) == (
        "off"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_OPEN_DOOR_BUTTON) != (
        "unavailable"
    )
    assert (
        await _press(hass, entry, UNIQUE_ID_DISHWASHER_OPEN_DOOR_BUTTON)
        == "OpenDoorOpt=7"
    )


async def test_failed_command_releases_buttons(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """A failed command is raised, and the buttons are not left blocked."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    with (
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("boom"),
        ),
        patch("custom_components.candy.button.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(aiohttp.ClientError),
    ):
        await _call(
            hass,
            "button",
            "press",
            {
                "entity_id": _entity_id(
                    hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON
                )
            },
        )
    await hass.async_block_till_done()

    assert _state(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON) != (
        "unavailable"
    )


# ---------------------------------------------------------------------------
# Command Builders & Unit Tests
# ---------------------------------------------------------------------------


def test_command_builders_delay_scaling_and_mask():
    assert is_open_door_supported("BRAVA_BI_DIGIT_OD") is True
    assert is_open_door_supported("DW_WIFI_FS") is False
    assert isinstance(
        get_dishwasher_command_builder("BRAVA_BI_DIGIT_OD"),
        ModernDishwasherCommandBuilder,
    )
    assert isinstance(
        get_dishwasher_command_builder("DishwasherInterfaceTypeFSTouch"),
        LegacyTouchDishwasherCommandBuilder,
    )

    modern = ModernDishwasherCommandBuilder(open_door_supported=True)
    # r15 == 0 -> delay in hours (90 min // 60 = 1 hour)
    params_h = modern.build_start(
        program_code="P8",
        position=1,
        delay_minutes=90,
        r15=0,
        three_in_one=True,
        eco=True,
        half_load=True,
        extra_dry=True,
        open_door=True,
    )
    assert params_h["DelayStart"] == 1
    # ExtraDry(1) + MetaCarico(2) + Eco(4) + TreinUno(8) + OpenDoorOpt(16) = 31
    assert params_h["OpzProg"] == 31
    assert params_h["OpenDoorOpt"] == 1
    assert params_h["w1"] == 1

    # r15 > 0 -> delay in minutes
    params_m = modern.build_start(
        program_code="P8",
        position=1,
        delay_minutes=45,
        r15=1,
        three_in_one=False,
        eco=False,
        half_load=False,
        extra_dry=False,
        open_door=False,
    )
    assert params_m["DelayStart"] == 45
    assert params_m["OpzProg"] == 0

    legacy = LegacyTouchDishwasherCommandBuilder(open_door_supported=False)
    legacy_params = legacy.build_start(
        program_code="P1+",
        position=1,
        delay_minutes=60,
        r15=0,
        three_in_one=False,
        eco=False,
        half_load=False,
        extra_dry=False,
        open_door=False,
    )
    assert "w1" not in legacy_params
    assert legacy_params["Program"] == "P1"
    assert legacy_params["OpzProg"] == "p"
    assert legacy.build_pause() == {"StartStop": 0}
    assert legacy.build_resume() == {"StartStop": 1}


# ---------------------------------------------------------------------------
# State & Phase resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "machine_state", "program_phase", "running"),
    [
        ({}, MachineState.IDLE, None, False),
        ({"StatoDWash": "1", "Reset": "1"}, MachineState.IDLE, None, False),
        (
            {"StartStop": "1", "StatoDWash": "3", "r2": "2"},
            MachineState.RUNNING,
            DishwasherProgramPhase.WASH,
            True,
        ),
        (
            {"StartStop": "1", "StatoDWash": "3", "r2": "3"},
            MachineState.RUNNING,
            DishwasherProgramPhase.RINSE,
            True,
        ),
        (
            {"StartStop": "1", "StatoDWash": "3", "r2": "4"},
            MachineState.RUNNING,
            DishwasherProgramPhase.DRYING,
            True,
        ),
        (
            {"StartStop": "1", "StatoDWash": "3", "r2": "0", "DelayStart": "60"},
            MachineState.DELAYED_START_PROGRAMMED,
            None,
            True,
        ),
        (
            {"StartStop": "1", "StatoDWash": "5", "r2": "5", "RemTime": "95"},
            MachineState.FINISHED1,
            DishwasherProgramPhase.FINISHED,
            False,
        ),
        (
            {"StartStop": "1", "StatoDWash": "4", "r2": "2"},
            MachineState.PAUSED,
            DishwasherProgramPhase.WASH,
            False,
        ),
        (
            {"StartStop": "1", "StatoDWash": "6", "CodiceErrore": "E3"},
            MachineState.ERROR,
            None,
            False,
        ),
    ],
)
def test_state_from_phase(
    overrides: dict,
    machine_state: MachineState,
    program_phase: DishwasherProgramPhase | None,
    running: bool,
):
    status = _status(_READY, **overrides)

    assert status.machine_state is machine_state
    assert status.program_phase is program_phase
    assert status.running is running


async def test_dishwasher_checkup_button_diagnostic_category(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify check-up button has DIAGNOSTIC entity category."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    registry = er.async_get(hass)
    btn_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON)

    assert registry.async_get(btn_id).entity_category == EntityCategory.DIAGNOSTIC


async def test_panel_start_resolves_w1_from_catalog(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When starting from panel and program matches catalog, resolve selector position for w1."""
    cat_path = Path(__file__).parent / "fixtures" / "catalog_serial_40_brava_dw.json"
    with open(cat_path, encoding="utf-8") as f:
        catalog = json.load(f)

    # Program 16 (Auto Daily) is at position 5 in catalog serial 40
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, Program="P16", r1="5"),
        extra_config_data={
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
        },
    )
    qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    assert "w1=5" in qs
    assert "Program=P16" in qs


async def test_panel_start_resolves_w1_from_r1_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When starting from panel without catalog, use status.selector_position from r1."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, Program="P99", r1="3"),
    )
    qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    assert "w1=3" in qs
    assert "Program=P99" in qs


async def test_start_masks_disallowed_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When a cycle is selected, options forbidden by available_options bitmask are masked out."""
    cat_path = Path(__file__).parent / "fixtures" / "catalog_serial_40_brava_dw.json"
    with open(cat_path, encoding="utf-8") as f:
        catalog = json.load(f)

    # In catalog serial 40, Program 20 (RAPIDO 24) has available_options: 8 (only 3-in-1)
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        extra_config_data={
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    # Select RAPIDO 24
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Rapid 24' 50°C"},
        blocking=True,
    )
    # Switches that are forbidden for this program become unavailable
    assert (
        _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH)
        == "unavailable"
    )
    assert (
        _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH) == "unavailable"
    )
    three_in_one_id = _entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH
    )

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": three_in_one_id}, blocking=True
    )

    qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    assert "Program=P20" in qs
    assert "w1=8" in qs
    assert "TreinUno=1" in qs
    assert "ExtraDry=0" in qs
    assert "Eco=0" in qs
    assert "MetaCarico=0" in qs
    assert "OpzProg=8" in qs


async def test_checkup_button_hidden_on_legacy_dishwasher(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Legacy Family 1 dishwashers do not have a diagnostic check-up button."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        extra_config_data={CONF_KEY_INTERFACE_TYPE: "DishwasherInterfaceTypeFSTouch"},
    )
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "button", DOMAIN, UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON.format(entry.entry_id)
        )
        is None
    )


def test_checkup_reset_command_builder() -> None:
    """Checkup reset command builder returns Write=1&StartStop=0&Program=11."""
    builder = ModernDishwasherCommandBuilder(open_door_supported=True)
    assert builder.build_checkup() == {"StartCheckUp": 1}
    assert builder.build_checkup_reset() == {"Write": 1, "StartStop": 0, "Program": 11}


async def test_start_with_fallback_program_resolves_selector_position(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Selecting a fallback program option (night_55) resolves w1=3 from DEFAULT_DISHWASHER_PROGRAMS, not w1=17."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "night_55"},
        blocking=True,
    )
    qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    assert "Program=P17" in qs
    assert "w1=3" in qs
    assert "w1=17" not in qs


async def test_dishwasher_reset_maintenance_counter_fallback_to_config_entry(
    hass: HomeAssistant,
) -> None:
    """Verify reset maintenance button falls back to config_entry data when stats are absent."""
    coord = MagicMock()
    stats_coord = MagicMock()
    stats_coord.data = None
    conf_key = "maint_last_full_checkup"
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_reset_btn_entry",
        data={conf_key: 120},
    )
    entry.add_to_hass(hass)

    btn = DishwasherMaintResetButton(
        coord,
        entry,
        stats_coord,
        conf_key,
        "candy_{}_maint_reset_checkup",
        "dishwasher_maint_reset_checkup",
        "mdi:history",
    )
    btn.hass = hass

    with patch(
        "custom_components.candy.button.restore_last_known_statistics",
        return_value=None,
    ):
        await btn.async_press()

    assert entry.data[conf_key] == 120
    stats_coord.async_update_listeners.assert_called_once()


async def test_dishwasher_start_wash_button_corrupt_number_and_unknown_switches(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify start wash button handles corrupted delay number and unknown switch states."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    delay_id = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)
    eco_id = _entity_id(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH)

    # Set delay state to a non-numeric string to trigger ValueError/TypeError fallback
    hass.states.async_set(delay_id, "corrupt_number")
    # Set eco switch state to 'unknown' to trigger default fallback
    hass.states.async_set(eco_id, "unknown")

    qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    assert "DelayStart=0" in qs
    assert "Eco=0" in qs


async def test_dishwasher_start_wash_button_missing_registry_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify start wash button handles missing select and number entity registrations."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    registry = er.async_get(hass)
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    number_id = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)
    registry.async_remove(select_id)
    registry.async_remove(number_id)

    qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    assert "DelayStart=0" in qs
    assert "StartStop=1" in qs


async def test_dishwasher_start_wash_button_direct_dishwasher_programs_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify start button resolves program code from DISHWASHER_PROGRAMS when not in parsed list."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    hass.states.async_set(select_id, "intensive_75")

    with patch(
        "custom_components.candy.button.find_dishwasher_program",
        return_value=None,
    ):
        qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)

    assert "Program=P2" in qs
    assert "w1=2" in qs


async def test_dishwasher_start_wash_button_status_program_parse_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify start button parses status.program when selector_position is None and no program matches."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, Program="P5", PrCode="P5"),
    )
    coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    status = coord.data
    status.selector_position = None

    with patch(
        "custom_components.candy.button.find_dishwasher_program",
        return_value=None,
    ):
        qs = await _press(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)

    assert "Program=P5" in qs
    assert "w1=5" in qs


async def test_dishwasher_buttons_unavailable_when_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify start, check-up, and remote control become unavailable/off when _make_off_status runs."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    start_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON)
    checkup_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON)
    assert hass.states.get(start_id).state != "unavailable"
    assert hass.states.get(checkup_id).state != "unavailable"

    off_status = _make_off_status(coord.data)
    coord.async_set_updated_data(off_status)
    await hass.async_block_till_done()

    assert off_status.remote_control is False
    assert hass.states.get(start_id).state == "unavailable"
    assert hass.states.get(checkup_id).state == "unavailable"


async def test_dishwasher_checkup_button_unavailable_when_door_open(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify check-up button is unavailable when the dishwasher door is open."""
    entry = await init_integration(hass, aioclient_mock, _fixture(_READY, OpenDoor="1"))
    checkup_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON)
    assert hass.states.get(checkup_id).state == "unavailable"


def test_dishwasher_status_missing_open_door_and_eco_default_false() -> None:
    """Verify missing OpenDoor or Eco keys default to False instead of True."""
    status = DishwasherStatus.from_json({"StatoDWash": "2"})
    assert status.door_open is False
    assert status.eco_mode is False
