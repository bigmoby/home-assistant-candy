"""Tests for write entities (select/number/button) in Full Control mode."""

from __future__ import annotations

import copy
import datetime
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client import (
    parse_wash_programs,
    resolve_downloadable_programs,
)
from custom_components.candy.client.model import DownloadableProgram, MachineState
from custom_components.candy.const import (
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_DRY_SELECT,
    UNIQUE_ID_WASH_ESTIMATED_DURATION,
    UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON,
    UNIQUE_ID_WASH_LIMESCALE_BUTTON,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_OPTION_GOODNIGHT,
    UNIQUE_ID_WASH_OPTION_HYGIENE,
    UNIQUE_ID_WASH_OPTION_PREWASH,
    UNIQUE_ID_WASH_OPTION_RINSE_1,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_PROGRAM_DESCRIPTION,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SCHEDULED_FINISH,
    UNIQUE_ID_WASH_SCHEDULED_START,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    UNIQUE_ID_WASH_STOP_BUTTON,
    UNIQUE_ID_WASH_TEMP_SELECT,
)

from .common import TEST_IP

# ---------------------------------------------------------------------------
# Minimal program catalog used across all tests
# ---------------------------------------------------------------------------

# RESISTANT_COTTONS: pos=1, sel=1, supports temp/spin/soil selection, supports steam
_COTTON = {
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
            {"command_parameter": {"name": "selector_position_dry", "validation": "1"}},
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

# RAPID_30_MIN: pos=2, sel=2, temp and spin fixed (255 = not selectable), soil fixed, no steam
_RAPID = {
    "program": {
        "position": 2,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_30_MIN",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "2"}},
            {"command_parameter": {"name": "pr_code", "validation": "5"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "255"}},
            {"command_parameter": {"name": "default_temperature", "validation": "30"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "255"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "14"}},
            {
                "command_parameter": {
                    "name": "remaining_time_soil_max",
                    "validation": "0",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_medium",
                    "validation": "0",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_min",
                    "validation": "0",
                }
            },
        ],
    }
}

_PROGRAMS = [_COTTON, _RAPID]

# AUTOCLEAN: selector_position=23, pr_code=104, fixed temp/spin (255)
_AUTOCLEAN = {
    "program": {
        "position": 23,
        "name": "AUTOCLEAN",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "23"}},
            {"command_parameter": {"name": "pr_code", "validation": "104"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "255"}},
            {"command_parameter": {"name": "default_temperature", "validation": "60"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "255"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "0"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "60"}},
            {
                "command_parameter": {
                    "name": "remaining_time_soil_max",
                    "validation": "0",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_medium",
                    "validation": "0",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_min",
                    "validation": "0",
                }
            },
        ],
    }
}
_PROGRAMS_WITH_AUTOCLEAN = [_COTTON, _RAPID, _AUTOCLEAN]

_IDLE_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_RUNNING_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "1", "PrPh": "2",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "1800", "FillR": "50", "CheckUpState": "0"
  }
}"""

# MachMd=1 (IDLE) is the closest the device returns; OFF is synthetic (unreachable).
# Simulate it by using IDLE JSON and then patching the coordinator data to MachineState.OFF.
_OFF_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "0", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_STATS_OK = '{"statusCounters": {"Temp0to30": "40"}}'


def _add_stats_mocks(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_OK,
    )


async def _init_full_control(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json: str
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _init_full_control_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> MockConfigEntry:
    """Init Full Control with the machine in the synthetic OFF state."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    off_status = copy.copy(coordinator.data)
    off_status.machine_state = MachineState.OFF
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()
    return entry


def _state(hass: HomeAssistant, entry: MockConfigEntry, platform: str, uid_tpl: str):
    """Look up an entity by unique_id template and return its state."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        platform, DOMAIN, uid_tpl.format(entry.entry_id)
    )
    if entity_id is None:
        return None
    return hass.states.get(entity_id)


# ---------------------------------------------------------------------------
# Program select
# ---------------------------------------------------------------------------


async def test_program_select_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert "Whites" in state.attributes["options"]
    assert "Rapid 30 Min." in state.attributes["options"]


async def test_program_select_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_program_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Temperature select
# ---------------------------------------------------------------------------


async def test_temp_select_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert "90" in state.attributes["options"]
    assert "0" in state.attributes["options"]


async def test_temp_select_unavailable_for_rapid_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    assert state is not None
    assert state.state == "unavailable"


async def test_temp_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Spin select
# ---------------------------------------------------------------------------


async def test_spin_select_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert "1400" in state.attributes["options"]
    assert "400" in state.attributes["options"]


async def test_spin_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Soil select
# ---------------------------------------------------------------------------


async def test_soil_select_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert state.attributes["options"] == ["low", "normal", "high"]


async def test_soil_select_reflects_device_slevel(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # SLevel=1 in the fixture, Cotton default_soil_level=2 — they differ, so the fallback
    # must read the live device value, not the program default.
    slevel_idle = _IDLE_JSON.replace('"SLevel": "0"', '"SLevel": "1"')
    entry = await _init_full_control(hass, aioclient_mock, slevel_idle)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    assert state is not None
    assert state.state == "low"


async def test_soil_select_unavailable_for_rapid_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    assert state is not None
    assert state.state == "unavailable"


async def test_soil_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Dry select (attach a drying phase to a compatible wash program, issue #9)
# ---------------------------------------------------------------------------


async def test_dry_select_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton has selector_position_dry=1, so the entity should be usable and
    # default to "off" (never attaches a drying phase unless explicitly set).
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["options"] == [
        "off",
        "extra_dry",
        "iron_dry",
        "cupboard_dry",
        "time_120",
        "time_90",
        "time_60",
        "time_30",
    ]


async def test_dry_select_unavailable_for_rapid_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Rapid has no selector_position_dry in its fixture catalog entry, so the
    # entity must stay unavailable rather than assume it works there too.
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is not None
    assert state.state == "unavailable"


async def test_dry_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Delay number
# ---------------------------------------------------------------------------


async def test_delay_number_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert state.state == "0"


async def test_delay_number_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Start button
# ---------------------------------------------------------------------------


async def test_start_button_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    assert state is not None
    assert state.state != "unavailable"


async def test_start_button_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_start_button_unavailable_when_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_off(hass, aioclient_mock)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_program_select_available_when_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_off(hass, aioclient_mock)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_delay_number_available_when_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_off(hass, aioclient_mock)
    state = _state(hass, entry, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_start_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "Write=1" in query_string
    assert "StSt=1" in query_string
    assert "PrNm=1" in query_string
    assert "PrCode=136" in query_string
    assert "PrStr=Whites" in query_string


# ---------------------------------------------------------------------------
# Stop button
# ---------------------------------------------------------------------------


async def test_stop_button_unavailable_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_STOP_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_stop_button_available_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_STOP_BUTTON)
    assert state is not None
    assert state.state != "unavailable"


async def test_stop_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_STOP_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "Write=1" in query_string
    assert "StSt=0" in query_string


# ---------------------------------------------------------------------------
# Read-only mode — no write entities registered
# ---------------------------------------------------------------------------


async def test_no_write_entities_in_read_only_mode(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-read-only",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=_IDLE_JSON)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "button", DOMAIN, UNIQUE_ID_WASH_STOP_BUTTON.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
        )
        is None
    )


# ---------------------------------------------------------------------------
# Steam switch
# ---------------------------------------------------------------------------


async def test_steam_switch_available_for_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_STEAM_SWITCH)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_steam_switch_unavailable_for_rapid_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_STEAM_SWITCH)
    assert state is not None
    assert state.state == "unavailable"


async def test_steam_switch_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_STEAM_SWITCH)
    assert state is not None
    assert state.state == "unavailable"


async def test_start_button_sends_steam_when_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    steam_entity_id = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    )
    assert steam_entity_id is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": steam_entity_id}, blocking=True
    )

    start_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_entity_id}, blocking=True
        )

    query_string: str = mock_send.call_args[0][0]
    assert "Stm=1" in query_string


async def test_start_button_no_steam_by_default(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    start_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_entity_id}, blocking=True
        )

    query_string: str = mock_send.call_args[0][0]
    assert "Stm=0" in query_string


async def test_start_button_sends_dry_value_when_selected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    dry_entity_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    assert dry_entity_id is not None
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_entity_id, "option": "cupboard_dry"},
        blocking=True,
    )

    start_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_entity_id}, blocking=True
        )

    query_string: str = mock_send.call_args[0][0]
    assert "Dry=3" in query_string


async def test_start_button_no_dry_by_default(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    start_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_entity_id}, blocking=True
        )

    query_string: str = mock_send.call_args[0][0]
    assert "Dry=0" in query_string


# ---------------------------------------------------------------------------
# Estimated duration sensor
# ---------------------------------------------------------------------------


async def test_estimated_duration_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_estimated_duration_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "unavailable"


async def test_estimated_duration_cotton_default_soil(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # SLevel=0 is outside Cotton's range [1,3], falls back to default_soil_level=2 → medium=90
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "90"


async def test_estimated_duration_cotton_heavy_soil(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # SLevel=3 → duration_soil_max = 120
    slevel3 = _IDLE_JSON.replace('"SLevel": "0"', '"SLevel": "3"')
    entry = await _init_full_control(hass, aioclient_mock, slevel3)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "120"


async def test_estimated_duration_cotton_light_soil(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # SLevel=1 → duration_soil_min = 60
    slevel1 = _IDLE_JSON.replace('"SLevel": "0"', '"SLevel": "1"')
    entry = await _init_full_control(hass, aioclient_mock, slevel1)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "60"


async def test_estimated_duration_rapid_uses_default_duration(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Rapid has fixed soil (min=max=0) → uses default_duration = 14
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "14"


async def test_estimated_duration_steam_off_no_change(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Steam switch off (default) → base duration unchanged (default soil=2 → medium=90)
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "90"


async def test_estimated_duration_steam_on_adds_offset_default_soil(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton steam_type=C, steam switch on, default soil=2 → medium=90 + 37 = 127
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    steam_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    )
    assert steam_eid is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": steam_eid}, blocking=True
    )
    # Force the duration sensor to re-render by triggering a coordinator update.
    # The steam subscription may not have been set up yet if the switch platform
    # registered after the sensor's deferred _subscribe_steam task ran.
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "127"


async def test_estimated_duration_steam_on_adds_offset_heavy_soil(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton steam_type=C, steam on, SLevel=3 → max=120 + 37 = 157
    slevel3 = _IDLE_JSON.replace('"SLevel": "0"', '"SLevel": "3"')
    entry = await _init_full_control(hass, aioclient_mock, slevel3)
    registry = er.async_get(hass)
    steam_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": steam_eid}, blocking=True
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "157"


async def test_estimated_duration_steam_on_adds_offset_light_soil(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton steam_type=C, steam on, SLevel=1 → min=60 + 37 = 97
    slevel1 = _IDLE_JSON.replace('"SLevel": "0"', '"SLevel": "1"')
    entry = await _init_full_control(hass, aioclient_mock, slevel1)
    registry = er.async_get(hass)
    steam_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": steam_eid}, blocking=True
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "97"


async def test_estimated_duration_not_registered_in_read_only(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-read-only-dur",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=_IDLE_JSON)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, UNIQUE_ID_WASH_ESTIMATED_DURATION.format(entry.entry_id)
        )
        is None
    )


# ---------------------------------------------------------------------------
# Scheduled start / finish sensors
# ---------------------------------------------------------------------------

_IDLE_DELAY_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "8",
    "DelVal": "60", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_RUNNING_45_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "1", "PrPh": "2",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "2700", "FillR": "50", "CheckUpState": "0"
  }
}"""


async def test_scheduled_start_unavailable_when_no_delay(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_START)
    assert state is not None
    assert state.state == "unavailable"


async def test_scheduled_start_shows_offset_timestamp(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_DELAY_JSON)

    # Simulate the user having set the delay slider to 60 min
    registry = er.async_get(hass)
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
    )
    assert delay_eid is not None
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid, "value": 60}, blocking=True
    )

    fixed_now = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
    with patch("homeassistant.util.dt.now", return_value=fixed_now):
        hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].async_set_updated_data(
            hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].data
        )
        await hass.async_block_till_done()
        state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_START)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    # 60 min delay → scheduled start at 13:00
    assert "2025-01-01T13:00:00" in state.state


async def test_scheduled_finish_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # RemTime=2700s → remaining_minutes=45
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_45_JSON)
    fixed_now = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
    with patch("homeassistant.util.dt.now", return_value=fixed_now):
        hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].async_set_updated_data(
            hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].data
        )
        await hass.async_block_till_done()
        state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_FINISH)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    # remaining=45min → finish ≈ 12:45
    assert "2025-01-01T12:45:00" in state.state


async def test_scheduled_finish_idle_with_delay_and_duration(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton/normal soil → estimated_duration=90; user sets delay to 60 → finish in 150min
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_DELAY_JSON)

    # Simulate the user having set the delay slider to 60 min
    registry = er.async_get(hass)
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
    )
    assert delay_eid is not None
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid, "value": 60}, blocking=True
    )

    fixed_now = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
    with patch("homeassistant.util.dt.now", return_value=fixed_now):
        hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].async_set_updated_data(
            hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].data
        )
        await hass.async_block_till_done()
        state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_FINISH)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    # 60min delay + 90min duration = 150min → 14:30
    assert "2025-01-01T14:30:00" in state.state


async def test_scheduled_sensors_absent_or_unavailable_in_read_only_mode(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-read-only-sched",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=_IDLE_JSON)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    # Scheduled start: not registered in read-only (no programs)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, UNIQUE_ID_WASH_SCHEDULED_START.format(entry.entry_id)
        )
        is None
    )
    # Scheduled finish: registered but unavailable when idle (no estimated duration)
    finish_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_FINISH)
    assert finish_state is not None
    assert finish_state.state == "unavailable"


# ---------------------------------------------------------------------------
# NFC special programs
# ---------------------------------------------------------------------------

# Bathrobe: parent=1 → Output 1 → RESISTANT_COTTONS (pos=1, pr_code=136, max_spin_speed=1400)
# position=56, spin_speed=1000, soil_level=2 (non-zero → used directly), options=16
_NFC_BATHROBE = DownloadableProgram(
    position=56,
    name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_BATHROBE",
    parent=1,  # Output 1 → RESISTANT_COTTONS
    temperature=40,
    spin_speed=1000,
    soil_level=2,
    options=16,
    steam=0,
    translations={"en": "Bathrobe"},
    category_translations={"en": "Home Care"},
    description_translations={"en": "Wash your bathrobe."},
)

# New Clothes: parent=6 → Output 6 → RAPID_30_MIN (pos=2, selector_position=2, pr_code=5, max_spin_speed=255)
# position=33, spin_speed=1000, soil_level=0 → sent as SLevTgt=0 (no fallback)
_NFC_NEW_CLOTHES = DownloadableProgram(
    position=33,
    name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_NEW_CLOTHES",
    parent=6,
    temperature=20,
    spin_speed=1000,
    soil_level=0,
    options=0,
    steam=0,
    translations={"en": "New Clothes"},
    category_translations={"en": "Special"},
    description_translations={"en": "Wash new clothes."},
)

_NFC_PROGRAMS = [_NFC_BATHROBE, _NFC_NEW_CLOTHES]


async def _init_full_control_nfc(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json: str
) -> MockConfigEntry:
    """Init Full Control with NFC switch turned on and two NFC test programs."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control-nfc",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS,
            CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.candy.select.load_downloadable_programs",
            return_value=_NFC_PROGRAMS,
        ),
        patch(
            "custom_components.candy.button.load_downloadable_programs",
            return_value=_NFC_PROGRAMS,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Turn the NFC switch on so special programs appear in the program selector
    registry = er.async_get(hass)
    nfc_switch_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(entry.entry_id)
    )
    assert nfc_switch_eid is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": nfc_switch_eid}, blocking=True
    )
    await hass.async_block_till_done()

    return entry


# --- resolve_downloadable_programs unit tests ---


def test_resolve_downloadable_programs_matches_cotton():
    programs = parse_wash_programs(_PROGRAMS)
    resolved = resolve_downloadable_programs([_NFC_BATHROBE], programs)
    assert len(resolved) == 1
    nfc, base = resolved[0]
    assert nfc.name == "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_BATHROBE"
    assert base.name == "RESISTANT_COTTONS"


def test_resolve_downloadable_programs_matches_rapid():
    programs = parse_wash_programs(_PROGRAMS)
    resolved = resolve_downloadable_programs([_NFC_NEW_CLOTHES], programs)
    assert len(resolved) == 1
    nfc, base = resolved[0]
    assert nfc.name == "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_NEW_CLOTHES"
    assert base.name == "RAPID_30_MIN"


def test_resolve_downloadable_programs_skips_unresolvable():
    unknown = DownloadableProgram(
        position=99,
        name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_UNKNOWN",
        parent=999,
        temperature=30,
        spin_speed=600,
        soil_level=0,
        options=0,
        steam=0,
        translations={"en": "Unknown"},
        category_translations={"en": "Cat"},
        description_translations={},
    )
    programs = parse_wash_programs(_PROGRAMS)
    resolved = resolve_downloadable_programs([unknown], programs)
    assert resolved == []


# --- Integration tests ---


async def test_nfc_program_options_appear_in_select(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    options = state.attributes["options"]
    # Standard programs still present
    assert "Whites" in options
    assert "Rapid 30 Min." in options
    # NFC programs appended with category prefix
    assert "Home Care - Bathrobe" in options
    assert "Special - New Clothes" in options


async def test_nfc_description_sensor_seeded_from_running_special_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test description sensor seeds downloadable program description from RecipeId."""
    running_special = _IDLE_JSON.replace(
        '"CheckUpState": "0"', '"CheckUpState": "0", "RecipeId": "D_33"'
    )
    entry = await _init_full_control_nfc(hass, aioclient_mock, running_special)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_DESCRIPTION)
    assert state is not None
    assert state.state == "Wash new clothes."


async def test_nfc_description_sensor_seeded_from_numeric_recipe_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test description sensor seeds from numeric RecipeId string."""
    running_special = _IDLE_JSON.replace(
        '"CheckUpState": "0"', '"CheckUpState": "0", "RecipeId": "56"'
    )
    entry = await _init_full_control_nfc(hass, aioclient_mock, running_special)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_DESCRIPTION)
    assert state is not None
    assert state.state == "Wash your bathrobe."


async def test_nfc_description_sensor_seeded_fallback_unknown_recipe_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test description sensor falls back to standard program for unknown RecipeId."""
    running_special = _IDLE_JSON.replace(
        '"CheckUpState": "0"', '"CheckUpState": "0", "RecipeId": "D_999"'
    )
    entry = await _init_full_control_nfc(hass, aioclient_mock, running_special)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_DESCRIPTION)
    assert state is not None
    assert state.state.startswith("This programme is developed")


async def test_nfc_description_sensor_updated_on_select(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test description sensor updates when selecting an NFC program in dropdown."""
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert program_eid is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Home Care - Bathrobe"},
        blocking=True,
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_DESCRIPTION)
    assert state is not None
    assert state.state == "Wash your bathrobe."

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Whites"},
        blocking=True,
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_DESCRIPTION)
    assert state is not None
    assert state.state.startswith("This programme is developed")


async def test_nfc_program_options_absent_when_toggle_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # NFC switch is off by default — special programs must not appear in the selector
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    options = state.attributes["options"]
    assert not any(" - " in opt for opt in options)


async def test_nfc_program_duration_attribute(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )

    # Select NFC program — duration attribute should be present
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Home Care - Bathrobe"},
        blocking=True,
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.attributes.get("duration_minutes") == 90

    # Switch to standard program — duration attribute should be absent
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Whites"},
        blocking=True,
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.attributes.get("duration_minutes") is None


async def test_nfc_select_disables_sub_selects(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert program_eid is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Home Care - Bathrobe"},
        blocking=True,
    )

    assert _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT).state == "40"
    assert (
        _state(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT).state == "unavailable"
    )
    assert (
        _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT).state == "unavailable"
    )


async def test_standard_select_after_nfc_re_enables_sub_selects(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )

    # First select an NFC program
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Home Care - Bathrobe"},
        blocking=True,
    )
    assert _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT).state == "40"

    # Then switch back to a standard program — sub-selects must re-enable
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Whites"},
        blocking=True,
    )
    assert (
        _state(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT).state != "unavailable"
    )
    assert (
        _state(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT).state != "unavailable"
    )
    assert (
        _state(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT).state != "unavailable"
    )


async def test_start_button_sends_nfc_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Bathrobe: position=56, parent=1 → Output 1 → base=RESISTANT_COTTONS (PrCode=136)
    # PrNm=1 (base.selector_position), temp=40, spin_speed=1000 → SpdTgt=10, soil_level=2 → SLevTgt=2, options=16, Stm=0
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Home Care - Bathrobe"},
        blocking=True,
    )

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    qs: str = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "StSt=1" in qs
    # PrNm MUST be the parent base program's selector_position (dial 1..16), NOT nfc.position (56).
    # Sending nfc.position causes the machine to reject the command with hardware fault E15.
    assert "PrNm=1" in qs
    assert f"PrNm={_NFC_BATHROBE.position}" not in qs
    assert "PrCode=136" in qs  # COTTON pr_code
    assert "PrStr=Bathrobe" in qs
    assert "TmpTgt=40" in qs
    assert "SpdTgt=10" in qs  # 1000 // 100
    assert "SLevTgt=2" in qs  # nfc.soil_level=2 (non-zero, used directly)
    assert "OptMsk1=16" in qs  # nfc.options=16, no user options active
    assert "RecipeId=D_56" in qs
    assert "Stm=0" in qs


async def test_start_button_nfc_zero_soil_level_sent_directly(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # New Clothes: position=33, parent=6 → base=RAPID_30_MIN (PrCode=5)
    # PrNm=2 (base.selector_position), soil_level=0 → sent as SLevTgt=0 (no fallback)
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Special - New Clothes"},
        blocking=True,
    )

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    qs: str = mock_send.call_args[0][0]
    assert "PrNm=2" in qs
    assert f"PrNm={_NFC_NEW_CLOTHES.position}" not in qs
    assert "PrCode=5" in qs
    assert "PrStr=New%20Clothes" in qs
    assert "TmpTgt=20" in qs
    assert "SpdTgt=10" in qs  # 1000 // 100
    assert "SLevTgt=0" in qs  # nfc.soil_level=0, sent directly
    assert "RecipeId=D_33" in qs


# ---------------------------------------------------------------------------
# Wash option switches (Prewash, Extra Rinse +1, …)
# ---------------------------------------------------------------------------

# COTTON variant with available_options=17: prewash(1) | rinse+1(16).
# RAPID keeps available_options=0 (absent from fixture → defaults to 0).
_COTTON_WITH_OPTIONS = {
    "program": {
        "position": 1,
        "name": "DUAL_WM_WD_PROGRAM_NAME_COTTON",
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
            {"command_parameter": {"name": "available_options", "validation": "17"}},
        ],
    }
}

_PROGRAMS_WITH_OPTIONS = [_COTTON_WITH_OPTIONS, _RAPID]


async def _init_full_control_with_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json: str
) -> MockConfigEntry:
    """Init Full Control using the program catalog that includes available_options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control-options",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS_WITH_OPTIONS,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    return entry


async def test_wash_option_prewash_registered(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_OPTION_PREWASH)
    assert state is not None


async def test_wash_option_rinse1_registered(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_OPTION_RINSE_1)
    assert state is not None


async def test_wash_option_not_registered_when_not_supported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # available_options=17 means neither hygiene(2) nor goodnight(8) are supported;
    # their switches must not be registered.
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_HYGIENE.format(entry.entry_id)
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_GOODNIGHT.format(entry.entry_id)
        )
        is None
    )


async def test_wash_option_available_cotton_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_OPTION_PREWASH)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")


async def test_wash_option_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_options(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_OPTION_PREWASH)
    assert state is not None
    assert state.state == "unavailable"


async def test_wash_option_unavailable_when_program_unsupported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Start with Rapid active: it has available_options=0, so prewash must be unavailable.
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "2"').replace(
        '"PrCode": "136"', '"PrCode": "5"'
    )
    entry = await _init_full_control_with_options(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "switch", UNIQUE_ID_WASH_OPTION_PREWASH)
    assert state is not None
    assert state.state == "unavailable"


async def test_wash_option_turn_on_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_PREWASH.format(entry.entry_id)
    )
    assert prewash_eid is not None

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )
    assert hass.states.get(prewash_eid).state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": prewash_eid}, blocking=True
    )
    assert hass.states.get(prewash_eid).state == "off"


async def test_start_button_includes_option_mask(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Turn on both prewash(1) and rinse+1(16) → OptMsk1=17.
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_PREWASH.format(entry.entry_id)
    )
    rinse_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_RINSE_1.format(entry.entry_id)
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": rinse_eid}, blocking=True
    )

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    qs: str = mock_send.call_args[0][0]
    assert "OptMsk1=17" in qs


async def test_start_button_no_options_by_default(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    qs: str = mock_send.call_args[0][0]
    assert "OptMsk1=0" in qs


async def test_wash_option_resets_on_program_change(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Turn on prewash while Cotton is active, then change to Rapid.
    # The program-change event must reset _is_on to False.
    # (Rapid doesn't support prewash so available=False, confirming the reset fired.)
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_PREWASH.format(entry.entry_id)
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )
    assert hass.states.get(prewash_eid).state == "on"

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Rapid 30 Min."},
        blocking=True,
    )
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    # Switch is unavailable on Rapid, which means _on_program_changed fired and reset it.
    assert hass.states.get(prewash_eid).state == "unavailable"


# ---------------------------------------------------------------------------
# Pause button
# ---------------------------------------------------------------------------


async def test_pause_button_available_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    assert state is not None
    assert state.state != "unavailable"


async def test_pause_button_unavailable_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_pause_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_PAUSE_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once_with("Pa=1")


# ---------------------------------------------------------------------------
# Feature gating: pause button excluded for BIANCA devices
# ---------------------------------------------------------------------------


async def _init_full_control_with_interface_type(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    interface_type: str,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-interface-type",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS,
            CONF_KEY_INTERFACE_TYPE: interface_type,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=_IDLE_JSON)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_pause_button_present_for_rapido(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_interface_type(
        hass, aioclient_mock, "RAPIDO_4DIG_STM_NEL"
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    assert state is not None


async def test_pause_button_absent_for_bianca(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_interface_type(
        hass, aioclient_mock, "BIANCA_SOME_MODEL"
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    assert state is None


async def test_pause_button_present_when_no_interface_type(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Existing entries without interface_type in config keep the pause button."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    assert state is not None


# ---------------------------------------------------------------------------
# Remote control gate: every control entity is unavailable when the machine
# is idle but not in Remote Control mode (WiFiStatus=0).
# ---------------------------------------------------------------------------


async def test_controls_unavailable_when_remote_control_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _OFF_JSON)

    gated = [
        ("select", UNIQUE_ID_WASH_PROGRAM_SELECT),
        ("select", UNIQUE_ID_WASH_TEMP_SELECT),
        ("select", UNIQUE_ID_WASH_SPIN_SELECT),
        ("select", UNIQUE_ID_WASH_SOIL_SELECT),
        ("number", UNIQUE_ID_WASH_DELAY_NUMBER),
        ("button", UNIQUE_ID_WASH_START_BUTTON),
        ("button", UNIQUE_ID_WASH_STOP_BUTTON),
        ("switch", UNIQUE_ID_WASH_STEAM_SWITCH),
    ]
    for platform, uid_tpl in gated:
        state = _state(hass, entry, platform, uid_tpl)
        assert state is not None, f"{uid_tpl} not registered"
        assert state.state == "unavailable", f"{uid_tpl} should be unavailable"


# ---------------------------------------------------------------------------
# AUTOCLEAN filtering and Limescale Cleaning button
# ---------------------------------------------------------------------------


async def _init_full_control_with_maintenance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    programs: list,
    maintenance_enabled: bool = True,
) -> MockConfigEntry:
    """Full Control init with maintenance counters enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-maintenance-buttons",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: programs,
            CONF_KEY_MAINTENANCE_ENABLED: maintenance_enabled,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_OK,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_autoclean_not_in_program_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """AUTOCLEAN program must be excluded from WashProgramSelect.options."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    options = state.attributes["options"]
    assert not any("autoclean" in opt.lower() for opt in options)
    assert "Whites" in options
    assert "Rapid 30 Min." in options


async def test_limescale_button_registered_when_autoclean_present(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Limescale Cleaning button is registered when AUTOCLEAN program exists."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_LIMESCALE_BUTTON)
    assert state is not None


async def test_limescale_button_absent_when_no_autoclean(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Limescale Cleaning button is NOT registered when AUTOCLEAN program absent."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_LIMESCALE_BUTTON)
    assert state is None


async def test_limescale_button_available_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Limescale Cleaning button is available when machine is idle."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_LIMESCALE_BUTTON)
    assert state is not None
    assert state.state != "unavailable"


async def test_limescale_button_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Limescale Cleaning button is unavailable when machine is running."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _RUNNING_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_LIMESCALE_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_limescale_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Pressing Limescale Cleaning sends write command with AUTOCLEAN params."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_LIMESCALE_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once()
    qs: str = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "StSt=1" in qs
    assert "PrNm=23" in qs
    assert "PrCode=104" in qs
    assert "TmpTgt=255" in qs
    assert "SpdTgt=0" in qs


async def test_limescale_button_absent_when_maintenance_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Limescale Cleaning button requires maintenance_enabled."""
    entry = await _init_full_control_with_maintenance(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        _PROGRAMS_WITH_AUTOCLEAN,
        maintenance_enabled=False,
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_LIMESCALE_BUTTON)
    assert state is None


async def test_limescale_button_unique_id_migrated_from_limestone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """A pre-existing 'wash_limestone_button' unique_id is migrated to 'wash_limescale_button'."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-limescale-migration",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS_WITH_AUTOCLEAN,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    old_unique_id = f"{entry.entry_id}-wash_limestone_button"
    registry_entry = registry.async_get_or_create(
        "button",
        DOMAIN,
        old_unique_id,
        config_entry=entry,
    )

    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=_IDLE_JSON)
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_OK,
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    migrated_entry = registry.async_get(registry_entry.entity_id)
    assert migrated_entry is not None
    assert migrated_entry.unique_id == f"{entry.entry_id}-wash_limescale_button"
    assert registry.async_get_entity_id("button", DOMAIN, old_unique_id) is None


async def test_full_checkup_button_in_diagnostics_when_maintenance_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Full Check-up button is registered under maintenance when enabled."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON)
    assert state is not None


async def test_full_checkup_button_absent_when_maintenance_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Full Check-up button requires maintenance_enabled."""
    entry = await _init_full_control_with_maintenance(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        _PROGRAMS_WITH_AUTOCLEAN,
        maintenance_enabled=False,
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON)
    assert state is None


async def test_full_checkup_button_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Full Check-up button is unavailable when machine is running."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _RUNNING_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_full_checkup_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Pressing Full Check-up sends CheckUpState=1."""
    entry = await _init_full_control_with_maintenance(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN
    )
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once()
    qs: str = mock_send.call_args[0][0]
    assert "CheckUpState=1" in qs
