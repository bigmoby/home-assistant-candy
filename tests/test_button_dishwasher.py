"""Tests for the dishwasher remote Start / Stop buttons."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.button import dishwasher_start_command
from custom_components.candy.client.model import DishwasherStatus
from custom_components.candy.const import (
    UNIQUE_ID_DISHWASHER_START_BUTTON,
    UNIQUE_ID_DISHWASHER_STOP_BUTTON,
)

from .common import init_integration

_READY = "dishwasher/remote_ready.json"
_RUNNING = "dishwasher/remote_running.json"


def _fixture(name: str, **overrides: str) -> str:
    data = json.loads(load_fixture(name))
    data["statusDWash"].update(overrides)
    return json.dumps(data)


def _status(name: str, **overrides: str) -> DishwasherStatus:
    return DishwasherStatus.from_json(
        json.loads(_fixture(name, **overrides))["statusDWash"]
    )


def _entity_id(hass: HomeAssistant, entry: MockConfigEntry, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, unique_id.format(entry.entry_id)
    )
    assert entity_id is not None
    return entity_id


def _state(hass: HomeAssistant, entry: MockConfigEntry, unique_id: str) -> str:
    state = hass.states.get(_entity_id(hass, entry, unique_id))
    assert state is not None
    return state.state


async def _press(hass: HomeAssistant, entity_id: str) -> str:
    with (
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("custom_components.candy.button.asyncio.sleep", new_callable=AsyncMock),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )
    mock_send.assert_called_once()
    return mock_send.call_args[0][0]


async def test_buttons_created_in_read_only_mode(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    _entity_id(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    _entity_id(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON)
    assert hass.states.get("button.start_dishwasher") is not None


async def test_start_available_when_ready(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON) != "unavailable"
    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON) == "unavailable"


async def test_buttons_unavailable_without_remote_control(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass, aioclient_mock, _fixture(_READY, StatoWiFi="0")
    )

    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON) == "unavailable"
    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON) == "unavailable"


async def test_start_unavailable_when_door_open(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, _fixture(_READY, OpenDoor="1"))

    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON) == "unavailable"


async def test_running_state(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_RUNNING))

    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON) == "unavailable"
    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON) != "unavailable"


async def test_stop_available_with_delayed_start(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass, aioclient_mock, _fixture(_READY, DelayStart="3")
    )

    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON) == "unavailable"
    assert _state(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON) != "unavailable"


async def test_start_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    query_string = await _press(
        hass, _entity_id(hass, entry, UNIQUE_ID_DISHWASHER_START_BUTTON)
    )

    assert query_string == (
        "DelayStart=0&ExtraDry=0&OpenDoorOpt=0&TreinUno=0&Program=P17"
        "&MetaCarico=0&OpzProg=0&w1=1&StartStop=1"
    )


async def test_stop_sends_reset(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(hass, aioclient_mock, load_fixture(_RUNNING))

    query_string = await _press(
        hass, _entity_id(hass, entry, UNIQUE_ID_DISHWASHER_STOP_BUTTON)
    )

    assert query_string == "Reset=1"


def test_start_command_keeps_panel_options():
    status = _status(
        _READY, MetaCarico="1", ExtraDry="1", TreinUno="1", OpenDoorOpt="1"
    )

    query_string = dishwasher_start_command(status)

    assert "ExtraDry=1" in query_string
    assert "OpenDoorOpt=1" in query_string
    assert "TreinUno=1" in query_string
    assert "MetaCarico=1" in query_string


def test_start_command_program_modifier():
    assert "Program=P2&MetaCarico=0&OpzProg=p" in dishwasher_start_command(
        _status(_READY, Program="P2", OpzProg="p")
    )
    assert "Program=P2&MetaCarico=0&OpzProg=m" in dishwasher_start_command(
        _status(_READY, Program="P2", OpzProg="m")
    )
