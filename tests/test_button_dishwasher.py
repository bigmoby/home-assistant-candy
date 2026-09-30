"""Tests for the dishwasher remote controls (start/stop and next-start settings)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.client.model import DishwasherState, DishwasherStatus
from custom_components.candy.const import (
    UNIQUE_ID_DISHWASHER_DELAY_NUMBER,
    UNIQUE_ID_DISHWASHER_DOOR,
    UNIQUE_ID_DISHWASHER_ECO_SWITCH,
    UNIQUE_ID_DISHWASHER_ERROR,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
    UNIQUE_ID_DISHWASHER_REMOTE_CONTROL,
    UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY,
    UNIQUE_ID_DISHWASHER_SALT_EMPTY,
    UNIQUE_ID_DISHWASHER_START_BUTTON,
    UNIQUE_ID_DISHWASHER_STOP_BUTTON,
    UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH,
)
from custom_components.candy.dishwasher import (
    DishwasherStartOptions,
    dishwasher_start_command,
)

from .common import init_integration

_READY = "dishwasher/remote_ready.json"
_RUNNING = "dishwasher/remote_running.json"

_PANEL_START = (
    "DelayStart=0&ExtraDry=0&OpenDoorOpt=0&TreinUno=0&Eco=0&Program=P17"
    "&MetaCarico=0&OpzProg=0&w1=1&StartStop=1"
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
        patch(
            "custom_components.candy.dishwasher.asyncio.sleep", new_callable=AsyncMock
        ),
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
        ("select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT),
        ("switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH),
        ("switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH),
        ("number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_SALT_EMPTY),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_DOOR),
        ("binary_sensor", UNIQUE_ID_DISHWASHER_REMOTE_CONTROL),
        ("sensor", UNIQUE_ID_DISHWASHER_ERROR),
    ]:
        _entity_id(hass, entry, domain, unique_id)


async def test_status_sensors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    entry = await init_integration(
        hass,
        aioclient_mock,
        _fixture(_READY, MissSalt="1", OpenDoor="1", CodiceErrore="E4"),
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
    assert _state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_ERROR) == "E4"


async def test_settings_default_to_panel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, _fixture(_READY, TreinUno="1"))

    assert _state(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT) == "panel"
    assert _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH) == "off"
    assert (
        _state(hass, entry, "switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH) == "on"
    )
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
        "DelayStart=3&ExtraDry=0&OpenDoorOpt=0&TreinUno=0&Eco=1&Program=P20"
        "&MetaCarico=0&OpzProg=0&w1=1&StartStop=1"
    )
    # The delay is used once; the other settings are kept for the next start
    assert float(hass.states.get(delay).state) == 0
    assert hass.states.get(select).state == "rapid_24"


async def test_stop_sends_reset(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_RUNNING))

    assert await _press(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON) == "Reset=1"


def test_start_command_keeps_other_panel_options():
    status = _status(_READY, MetaCarico="1", ExtraDry="1", OpenDoorOpt="1")

    query_string = dishwasher_start_command(status, DishwasherStartOptions())

    assert "ExtraDry=1" in query_string
    assert "OpenDoorOpt=1" in query_string
    assert "MetaCarico=1" in query_string


def test_start_command_program_modifier():
    options = DishwasherStartOptions()
    assert "Program=P2&MetaCarico=0&OpzProg=p" in dishwasher_start_command(
        _status(_READY, Program="P2", OpzProg="p"), options
    )
    assert "Program=P2&MetaCarico=0&OpzProg=m" in dishwasher_start_command(
        _status(_READY, Program="P2", OpzProg="m"), options
    )


def test_start_command_delay_rounds_to_steps():
    options = DishwasherStartOptions(delay_minutes=45)

    assert "DelayStart=1&" in dishwasher_start_command(_status(_READY), options)


# ---------------------------------------------------------------------------
# State, from a full cycle logged on a CDIN 1D360PB (phase in r2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "state", "running"),
    [
        ({}, DishwasherState.IDLE, False),
        ({"StatoDWash": "1", "Reset": "1"}, DishwasherState.IDLE, False),
        ({"StartStop": "1", "StatoDWash": "3", "r2": "2"}, DishwasherState.WASH, True),
        ({"StartStop": "1", "StatoDWash": "3", "r2": "3"}, DishwasherState.RINSE, True),
        (
            {"StartStop": "1", "StatoDWash": "3", "r2": "4"},
            DishwasherState.DRYING,
            True,
        ),
        (
            {"StartStop": "1", "StatoDWash": "3", "r2": "0", "DelayStart": "60"},
            DishwasherState.DELAYED_START,
            True,
        ),
        (
            {"StartStop": "1", "StatoDWash": "5", "r2": "5", "RemTime": "95"},
            DishwasherState.FINISHED,
            False,
        ),
    ],
)
def test_state_from_phase(overrides: dict, state: DishwasherState, running: bool):
    status = _status(_READY, **overrides)

    assert status.machine_state is state
    assert status.running is running


def test_state_without_phase_uses_stato_dwash():
    data = json.loads(load_fixture(_READY))["statusDWash"]
    del data["r2"]

    assert DishwasherStatus.from_json(data).machine_state is DishwasherState.WASH


async def test_finished_cycle(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    """StartStop stays 1 after the end: the machine is not running any more."""
    await init_integration(
        hass,
        aioclient_mock,
        _fixture(_RUNNING, StatoDWash="5", r2="5", RemTime="95"),
    )

    assert hass.states.get("sensor.dishwasher").state == "Finished"
    assert hass.states.get("sensor.dishwasher_remaining_time").state == "0"
    assert hass.states.get("button.start_dishwasher").state != "unavailable"
    assert hass.states.get("button.stop_dishwasher").state == "unavailable"


async def test_running_cycle_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, _fixture(_RUNNING, r2="3", RemTime="55")
    )

    assert hass.states.get("sensor.dishwasher").state == "Rinse"
    assert hass.states.get("sensor.dishwasher_remaining_time").state == "55"


async def test_ready_remaining_time(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """RemTime is the program duration while ready, not a remaining time."""
    await init_integration(hass, aioclient_mock, load_fixture(_READY))

    assert hass.states.get("sensor.dishwasher").state == "Idle"
    assert hass.states.get("sensor.dishwasher_remaining_time").state == "0"
