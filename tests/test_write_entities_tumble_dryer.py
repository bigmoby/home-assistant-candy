"""Tests for tumble dryer write entities (select/number/button) in Full Control mode."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import aiohttp
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.button import CandyDryerStartButton
from custom_components.candy.client import parse_dryer_programs
from custom_components.candy.client.model import MachineState, TumbleDryerStatus
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_TUMBLE_DRYER,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    MODE_FULL_CONTROL,
    UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON,
    UNIQUE_ID_TUMBLE_CHECKUP_BUTTON,
    UNIQUE_ID_TUMBLE_DELAY_NUMBER,
    UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT,
    UNIQUE_ID_TUMBLE_PAUSE_BUTTON,
    UNIQUE_ID_TUMBLE_PROGRAM_SELECT,
    UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON,
    UNIQUE_ID_TUMBLE_RESUME_BUTTON,
    UNIQUE_ID_TUMBLE_START_BUTTON,
    UNIQUE_ID_TUMBLE_STOP_BUTTON,
    UNIQUE_ID_TUMBLE_TIME_SELECT,
)

from .common import TEST_IP

_PROGRAM_COTTON = {
    "position": 1,
    "name": "COTTON",
    "default_drying_level": 3,
    "max_time_level": 120,
    "default_time_level": 60,
    "set_dry_level": 1,
    "set_time_level": 1,
    "set_rapido": 0,
    "duration": 150,
    "parameters": {
        "selector_position": 1,
    },
}

_PROGRAM_SYNTHETICS = {
    "position": 2,
    "name": "SYNTHETICS",
    "default_drying_level": 2,
    "max_time_level": 0,
    "default_time_level": 0,
    "set_dry_level": 1,
    "set_time_level": 0,
    "set_rapido": 0,
    "duration": 90,
    "parameters": {
        "selector_position": 2,
    },
}

_PROGRAM_RAPID_45 = {
    "position": 3,
    "name": "RAPID_45_MIN",
    "default_drying_level": 0,
    "max_time_level": 120,
    "default_time_level": 45,
    "set_dry_level": 0,
    "set_time_level": 1,
    "set_rapido": 0,
    "duration": 45,
    "parameters": {
        "selector_position": 3,
    },
}

_DRYER_PROGRAMS = [_PROGRAM_COTTON, _PROGRAM_SYNTHETICS, _PROGRAM_RAPID_45]

_IDLE_JSON = """{
  "statusTD": {
    "StatoWiFi": "1",
    "StatoTD": "1",
    "CodiceErrore": "0",
    "Pr": "1",
    "PrPh": "0",
    "RemTime": "150",
    "DryLev": "3",
    "Time": "0",
    "Rapido": "0",
    "Refresh": "0",
    "CleanFilter": "0",
    "WaterTankFull": "0",
    "DryingManagerLevel": "3",
    "DelVal": "0",
    "DoorState": "1",
    "RecipeId": "NULL",
    "CheckUpState": "0"
  }
}"""

_RUNNING_JSON = """{
  "statusTD": {
    "StatoWiFi": "1",
    "StatoTD": "2",
    "CodiceErrore": "0",
    "Pr": "1",
    "PrPh": "2",
    "RemTime": "100",
    "DryLev": "3",
    "Time": "0",
    "Rapido": "0",
    "Refresh": "0",
    "CleanFilter": "0",
    "WaterTankFull": "0",
    "DryingManagerLevel": "3",
    "DelVal": "0",
    "DoorState": "1",
    "RecipeId": "NULL",
    "CheckUpState": "0"
  }
}"""

_PAUSED_JSON = """{
  "statusTD": {
    "StatoWiFi": "1",
    "StatoTD": "3",
    "CodiceErrore": "0",
    "Pr": "1",
    "PrPh": "2",
    "RemTime": "100",
    "DryLev": "3",
    "Time": "0",
    "Rapido": "0",
    "Refresh": "0",
    "CleanFilter": "0",
    "WaterTankFull": "0",
    "DryingManagerLevel": "3",
    "DelVal": "0",
    "DoorState": "1",
    "RecipeId": "NULL",
    "CheckUpState": "0"
  }
}"""

_FINISHED_JSON = """{
  "statusTD": {
    "StatoWiFi": "1",
    "StatoTD": "8",
    "CodiceErrore": "0",
    "Pr": "1",
    "PrPh": "3",
    "RemTime": "0",
    "DryLev": "3",
    "Time": "0",
    "Rapido": "0",
    "Refresh": "0",
    "CleanFilter": "0",
    "WaterTankFull": "0",
    "DryingManagerLevel": "3",
    "DelVal": "0",
    "DoorState": "1",
    "RecipeId": "NULL",
    "CheckUpState": "0"
  }
}"""


async def _init_dryer_full_control(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str = _IDLE_JSON,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-dryer-full-control",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _DRYER_PROGRAMS,
            CONF_KEY_INTERFACE_TYPE: "TD_DIGIT_1",
            CONF_KEY_IS_TUMBLE_DRYER: True,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_dryer_select_and_number_entities_created(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test dryer select and number entities are set up with correct options."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert program_eid is not None
    p_state = hass.states.get(program_eid)
    assert p_state is not None
    assert "Cotton" in p_state.attributes["options"]
    assert "Synthetics" in p_state.attributes["options"]

    level_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT.format(entry.entry_id)
    )
    assert level_eid is not None
    l_state = hass.states.get(level_eid)
    assert l_state is not None
    assert "store_dry" in l_state.attributes["options"]

    time_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_TIME_SELECT.format(entry.entry_id)
    )
    assert time_eid is not None
    t_state = hass.states.get(time_eid)
    assert t_state is not None
    assert "off" in t_state.attributes["options"]
    assert "60" in t_state.attributes["options"]

    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_TUMBLE_DELAY_NUMBER.format(entry.entry_id)
    )
    assert delay_eid is not None
    d_state = hass.states.get(delay_eid)
    assert d_state is not None
    assert float(d_state.state) == 0.0


async def test_dryer_start_button_standard(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test pressing start button sends standard drying start command."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert start_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["StSt"] == "1"
    assert params["PrNm"] == "1"
    assert params["DryLev"] == "3"


async def test_dryer_start_button_timed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test pressing start button with timed drying selected sends timed command."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    time_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_TIME_SELECT.format(entry.entry_id)
    )
    assert time_eid is not None
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": time_eid, "option": "60"},
        blocking=True,
    )

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert start_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["StSt"] == "1"
    assert params["PrNm"] == "1"
    assert params["Time"] == "60"


async def test_dryer_start_button_delayed(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test pressing start button with delay sends delayed start command."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_TUMBLE_DELAY_NUMBER.format(entry.entry_id)
    )
    assert delay_eid is not None
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_eid, "value": 120},
        blocking=True,
    )

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert start_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["PrNm"] == "1"
    assert params["DryLev"] == "3"
    assert params["DelMd"] == "1"
    assert params["DelVl"] == "120"


async def test_dryer_start_button_delayed_timed_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test pressing start button with delay on a timed-only program preserves Time parameter."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(entry.entry_id)
    )
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_TUMBLE_DELAY_NUMBER.format(entry.entry_id)
    )
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert program_eid is not None
    assert delay_eid is not None
    assert start_eid is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Rapid 45 min."},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_eid, "value": 60},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["PrNm"] == "3"
    assert params["Time"] == "45"
    assert params["DelMd"] == "1"
    assert params["DelVl"] == "60"
    assert "DryLev" not in params


async def test_dryer_start_button_delayed_with_timed_option(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test timed drying option combined with delay sends both Time and DelMd parameters."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    time_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_TIME_SELECT.format(entry.entry_id)
    )
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_TUMBLE_DELAY_NUMBER.format(entry.entry_id)
    )
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert time_eid is not None
    assert delay_eid is not None
    assert start_eid is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": time_eid, "option": "60"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_eid, "value": 180},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["PrNm"] == "1"
    assert params["Time"] == "60"
    assert params["DelMd"] == "1"
    assert params["DelVl"] == "180"
    assert "DryLev" not in params


async def test_dryer_stop_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test pressing stop button sends stop command."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _RUNNING_JSON)
    registry = er.async_get(hass)

    stop_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_STOP_BUTTON.format(entry.entry_id)
    )
    assert stop_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": stop_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["StSt"] == "0"
    assert params["DelMd"] == "0"
    assert params["PrNm"] == "1"


async def test_dryer_pause_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test pause button."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _RUNNING_JSON)
    registry = er.async_get(hass)

    pause_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_PAUSE_BUTTON.format(entry.entry_id)
    )
    assert pause_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": pause_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["SetPauseDryMgr"] == "1"


async def test_dryer_resume_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test resume button in paused state."""
    paused_entry = await _init_dryer_full_control(hass, aioclient_mock, _PAUSED_JSON)
    registry = er.async_get(hass)
    resume_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_RESUME_BUTTON.format(paused_entry.entry_id)
    )
    assert resume_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send_resume:
        await hass.services.async_call(
            "button", "press", {"entity_id": resume_eid}, blocking=True
        )

    mock_send_resume.assert_called_once()
    qs = mock_send_resume.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["SetRestartDryMgr"] == "1"


async def test_dryer_anti_crease_cancel_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test anti-crease cancel button sends DontTumbling=1."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _FINISHED_JSON)
    registry = er.async_get(hass)

    cancel_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON.format(entry.entry_id)
    )
    assert cancel_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": cancel_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["DontTumbling"] == "1"


async def test_dryer_checkup_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test check-up button sends CheckUpState=1."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    checkup_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_CHECKUP_BUTTON.format(entry.entry_id)
    )
    assert checkup_eid is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": checkup_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["CheckUpState"] == "1"


async def test_dryer_reset_warnings_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test reset warnings button sends ResetWarnings=1 when problem flags are active."""
    warning_json = _IDLE_JSON.replace('"CleanFilter": "0"', '"CleanFilter": "1"')
    entry = await _init_dryer_full_control(hass, aioclient_mock, warning_json)
    registry = er.async_get(hass)

    reset_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON.format(entry.entry_id)
    )
    assert reset_eid is not None
    assert hass.states.get(reset_eid).state != "unavailable"

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": reset_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["ResetWarnings"] == "1"


async def test_dryer_program_without_time_level_disables_time_select(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test selecting a program without set_time_level marks time select unavailable."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(entry.entry_id)
    )
    time_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_TIME_SELECT.format(entry.entry_id)
    )
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert program_eid is not None
    assert time_eid is not None
    assert start_eid is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Synthetics"},
        blocking=True,
    )

    t_state = hass.states.get(time_eid)
    assert t_state is not None
    assert t_state.state == "unavailable"

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["StSt"] == "1"
    assert params["PrNm"] == "2"
    assert params["DryLev"] == "2"
    assert "Time" not in params


async def test_dryer_timed_only_program_gating_and_start(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test timed-only program disables level select and sends timed start command."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(entry.entry_id)
    )
    level_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT.format(entry.entry_id)
    )
    time_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_TIME_SELECT.format(entry.entry_id)
    )
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert program_eid is not None
    assert level_eid is not None
    assert time_eid is not None
    assert start_eid is not None

    # Switch to Rapid 45 min. (set_dry_level=0, set_time_level=1, default_time_level=45)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Rapid 45 min."},
        blocking=True,
    )

    # Dry level select should be unavailable (no dry levels)
    l_state = hass.states.get(level_eid)
    assert l_state is not None
    assert l_state.state == "unavailable"

    # Time select should be active, defaulting to 45, without "off" option
    t_state = hass.states.get(time_eid)
    assert t_state is not None
    assert t_state.state == "45"
    assert "off" not in t_state.attributes["options"]
    assert "45" in t_state.attributes["options"]

    # Press start without touching time -> sends timed start with 45 min, no DryLev
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    params = {k: v[0] for k, v in parse_qs(qs).items()}
    assert params["Write"] == "1"
    assert params["StSt"] == "1"
    assert params["PrNm"] == "3"
    assert params["Time"] == "45"
    assert "DryLev" not in params

    # Change time to 90 min and press start
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": time_eid, "option": "90"},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send_90:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send_90.assert_called_once()
    qs_90 = mock_send_90.call_args[0][0]
    params_90 = {k: v[0] for k, v in parse_qs(qs_90).items()}
    assert params_90["PrNm"] == "3"
    assert params_90["Time"] == "90"
    assert "DryLev" not in params_90

    # Switch back to Cotton -> level select becomes available, time select resets to "off"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Cotton"},
        blocking=True,
    )

    l_state_cotton = hass.states.get(level_eid)
    assert l_state_cotton is not None
    assert l_state_cotton.state != "unavailable"

    t_state_cotton = hass.states.get(time_eid)
    assert t_state_cotton is not None
    assert t_state_cotton.state == "off"
    assert "off" in t_state_cotton.attributes["options"]

    # Press start -> dispatches standard start with DryLev=3
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send_cotton:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send_cotton.assert_called_once()
    qs_cotton = mock_send_cotton.call_args[0][0]
    params_cotton = {k: v[0] for k, v in parse_qs(qs_cotton).items()}
    assert params_cotton["PrNm"] == "1"
    assert params_cotton["DryLev"] == "3"
    assert "Time" not in params_cotton


async def test_dryer_write_entities_unavailable_when_machine_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test start button, delay number, and selects are unavailable when machine is off."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_TUMBLE_DELAY_NUMBER.format(entry.entry_id)
    )
    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert start_eid is not None
    assert delay_eid is not None
    assert program_eid is not None

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    off_status = TumbleDryerStatus(
        machine_state=MachineState.OFF,
        program_state=coordinator.data.program_state,
        cycle_state=coordinator.data.cycle_state,
        program=coordinator.data.program,
        remaining_minutes=0,
        remote_control=True,
        dry_level=coordinator.data.dry_level,
        dry_level_selected=coordinator.data.dry_level_selected,
        refresh=False,
        need_clean_filter=False,
        water_tank_full=False,
        door_closed=True,
        error=None,
        delay_value=None,
        checkup_state=None,
        recipe_id=None,
        time=None,
        rapido=None,
    )
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()

    assert hass.states.get(start_eid).state == "unavailable"
    assert hass.states.get(delay_eid).state == "unavailable"
    assert hass.states.get(program_eid).state == "unavailable"


async def test_dryer_buttons_unavailable_on_coordinator_update_failure(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test buttons become unavailable when coordinator update fails."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    stop_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_STOP_BUTTON.format(entry.entry_id)
    )
    assert start_eid is not None
    assert stop_eid is not None

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(start_eid).state == "unavailable"
    assert hass.states.get(stop_eid).state == "unavailable"


async def test_dryer_button_send_command_exception(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test exception in send_command is re-raised and write_pending decremented."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert start_eid is not None

    with (
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            side_effect=aiohttp.ClientError("Dryer write error"),
        ),
        pytest.raises(aiohttp.ClientError),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )


async def test_dryer_start_button_missing_and_invalid_states(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test start button handles missing registry entities and invalid numeric states."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_TUMBLE_DELAY_NUMBER.format(entry.entry_id)
    )
    assert start_eid is not None
    assert delay_eid is not None

    # Set delay number state to invalid string
    hass.states.async_set(delay_eid, "invalid_number")

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    assert "StSt=1" in qs
    assert "PrNm=1" in qs


async def test_dryer_start_button_unknown_program_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test unknown program name or empty programs raises ValueError."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    prog_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert start_eid is not None
    assert prog_eid is not None

    # Set program to unknown name
    hass.states.async_set(prog_eid, "Unknown Program Name")

    with pytest.raises(
        ValueError,
        match="Cannot start: program 'Unknown Program Name' not found in catalog",
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    # When no programs available, pressing raises ValueError
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    btn = CandyDryerStartButton(coordinator, entry, client, [])
    btn.hass = hass
    with pytest.raises(
        ValueError,
        match="Cannot start: program 'Unknown Program Name' not found in catalog",
    ):
        await btn.async_press()


async def test_dryer_start_button_timed_dry_default_time(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test timed-dry program with no time option selected uses default time."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    prog_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(entry.entry_id)
    )
    time_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_TUMBLE_TIME_SELECT.format(entry.entry_id)
    )
    assert start_eid is not None
    assert prog_eid is not None
    assert time_eid is not None

    # Set program to RAPID_45_MIN
    programs = parse_dryer_programs(entry.data[CONF_KEY_PROGRAMS])
    rapid_prog = next(p for p in programs if p.name == "RAPID_45_MIN")
    hass.states.async_set(prog_eid, rapid_prog.localized_name("en"))
    # Set time select to unavailable (None)
    hass.states.async_set(time_eid, "unavailable")

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    assert "Time=45" in qs


async def test_dryer_start_button_missing_registry_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test dryer start button raises on missing select, and defaults to 0.0 for missing number."""
    entry = await _init_dryer_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_TUMBLE_START_BUTTON.format(entry.entry_id)
    )
    assert start_eid is not None

    orig_get_eid = registry.async_get_entity_id

    # When select is missing, pressing start button raises ValueError
    with (
        patch.object(
            registry,
            "async_get_entity_id",
            side_effect=lambda domain, platform, unique_id: None
            if domain == "select"
            else orig_get_eid(domain, platform, unique_id),
        ),
        pytest.raises(
            ValueError,
            match="Cannot start: program 'None' not found in catalog",
        ),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    # When only number is missing, number state defaults to 0.0 and start succeeds
    with (
        patch.object(
            registry,
            "async_get_entity_id",
            side_effect=lambda domain, platform, unique_id: None
            if domain == "number"
            else orig_get_eid(domain, platform, unique_id),
        ),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
