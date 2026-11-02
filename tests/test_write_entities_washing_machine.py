"""Tests for write entities (select/number/button) in Full Control mode."""

from __future__ import annotations

import copy
import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.button import (
    _build_dualtech_start_params,
    async_setup_entry,
)
from custom_components.candy.client import (
    parse_wash_programs,
    resolve_downloadable_programs,
)
from custom_components.candy.client.model import (
    DownloadableProgram,
    MachineState,
    WashingMachineStatus,
)
from custom_components.candy.const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CONF_KEY_BRAND,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_PENDING,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    DRY_TARGET_CUPBOARD_DRY,
    DRY_TARGET_EXTRA_DRY,
    DRY_TARGET_IRON_DRY,
    DRY_TARGET_NO_DRY,
    DRY_TARGET_OPTIONS_FULL,
    DRY_TARGET_OPTIONS_ONLY_DRY,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    PROGRAM_TYPE_DRYING,
    PROGRAM_TYPE_WASH_AND_DRY,
    PROGRAM_TYPE_WASHING,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_DETERGENT_AUTODOSE,
    UNIQUE_ID_WASH_DRY_SELECT,
    UNIQUE_ID_WASH_ESTIMATED_DURATION,
    UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH,
    UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON,
    UNIQUE_ID_WASH_LIMESCALE_BUTTON,
    UNIQUE_ID_WASH_MAINT_FILTER_BUTTON,
    UNIQUE_ID_WASH_MAINT_FULL_CHECKUP_BUTTON,
    UNIQUE_ID_WASH_MAINT_LIMESCALE_BUTTON,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_OPTION_GOODNIGHT,
    UNIQUE_ID_WASH_OPTION_HYGIENE,
    UNIQUE_ID_WASH_OPTION_PREWASH,
    UNIQUE_ID_WASH_OPTION_RINSE_1,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_PROGRAM_DESCRIPTION,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT,
    UNIQUE_ID_WASH_RESUME_BUTTON,
    UNIQUE_ID_WASH_RESUME_GOOD_NIGHT,
    UNIQUE_ID_WASH_SCHEDULED_FINISH,
    UNIQUE_ID_WASH_SCHEDULED_START,
    UNIQUE_ID_WASH_SOFTENER_AUTODOSE,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    UNIQUE_ID_WASH_STOP_BUTTON,
    UNIQUE_ID_WASH_TEMP_SELECT,
    UNIQUE_ID_WASH_WATER_HARDNESS,
    WATER_HARDNESS_OPTIONS,
)
from custom_components.candy.select import CandyWashProgramDescriptionSensor

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

# RAPID_30_MIN: pos=8, sel=7, temp and spin fixed (255 = not selectable), soil fixed, no steam
_RAPID = {
    "program": {
        "position": 8,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_30_MIN",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "7"}},
            {"command_parameter": {"name": "pr_code", "validation": "71"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "255"}},
            {"command_parameter": {"name": "default_temperature", "validation": "30"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "255"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "9"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "30"}},
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

# RAPID_44_MIN: pos=9, sel=7, temp and spin fixed (255 = not selectable), soil fixed, no steam
_RAPID_44 = {
    "program": {
        "position": 9,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_44_MIN",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "7"}},
            {"command_parameter": {"name": "pr_code", "validation": "103"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "255"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "255"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "9"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "44"}},
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

_PROGRAMS = [_COTTON, _RAPID, _RAPID_44]

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

_PAUSED_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "3", "Pr": "1", "PrPh": "2",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "1200", "FillR": "50", "CheckUpState": "0"
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

_STATS_OK = (
    '{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'
)


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


async def _init_full_control_custom(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    extra_data: dict,
) -> MockConfigEntry:
    data = {
        CONF_IP_ADDRESS: TEST_IP,
        CONF_KEY_USE_ENCRYPTION: False,
        CONF_PASSWORD: "",
        CONF_KEY_MODE: MODE_FULL_CONTROL,
        CONF_KEY_PROGRAMS: _PROGRAMS,
    }
    data.update(extra_data)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control",
        data=data,
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
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "7"').replace(
        '"PrCode": "136"', '"PrCode": "71"'
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
    assert state.attributes["options"] == [
        "0",
        "400",
        "600",
        "800",
        "1000",
        "1200",
        "1400",
    ]


async def test_spin_select_special_catalog_speeds(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Verify special catalog speeds (1300/1500) are included only when in catalog."""
    prog_1300 = {
        "program": {
            "position": 1,
            "name": "COTTONS_1300",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "1"}},
                {
                    "command_parameter": {
                        "name": "maximum_spin_speed",
                        "validation": "1300",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_spin_speed",
                        "validation": "1300",
                    }
                },
            ],
        }
    }
    entry = await _init_full_control_custom(
        hass, aioclient_mock, _IDLE_JSON, {CONF_KEY_PROGRAMS: [prog_1300]}
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    assert state is not None
    assert state.attributes["options"] == [
        "0",
        "400",
        "600",
        "800",
        "1000",
        "1200",
        "1300",
    ]


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
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "7"').replace(
        '"PrCode": "136"', '"PrCode": "71"'
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
    assert state.attributes.get("step") == 30


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
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "7"').replace(
        '"PrCode": "136"', '"PrCode": "71"'
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
    # Rapid has fixed soil (min=max=2) → uses default_duration = 30
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "7"').replace(
        '"PrCode": "136"', '"PrCode": "71"'
    )
    entry = await _init_full_control(hass, aioclient_mock, rapid_idle)
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "30"


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


async def test_estimated_duration_prewash_adds_standard_delta(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton steam_type=C, default soil=2 (medium=90). Prewash adds +20 -> 110 min.
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_PREWASH.format(entry.entry_id)
    )
    assert prewash_eid is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )
    await hass.async_block_till_done()
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "110"


async def test_estimated_duration_extra_rinse_adds_standard_delta(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton steam_type=C, default soil=2 (medium=90). Extra rinse 1 adds +10 -> 100 min.
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    rinse1_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_RINSE_1.format(entry.entry_id)
    )
    assert rinse1_eid is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": rinse1_eid}, blocking=True
    )
    await hass.async_block_till_done()
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "100"


async def test_estimated_duration_prewash_and_rinse_combined(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Cotton steam_type=C, default soil=2 (medium=90) + Prewash (+20) + Rinse1 (+10) -> 120 min.
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_PREWASH.format(entry.entry_id)
    )
    rinse1_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_RINSE_1.format(entry.entry_id)
    )
    assert prewash_eid is not None
    assert rinse1_eid is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": rinse1_eid}, blocking=True
    )
    await hass.async_block_till_done()
    state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert state is not None
    assert state.state == "120"


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


async def test_estimated_duration_telemetry_no_program_code_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Estimated duration does not raise UnboundLocalError when program_code is None in telemetry."""
    no_prcode_json = _IDLE_JSON.replace('"PrCode": "136", ', "")
    entry = await _init_full_control(hass, aioclient_mock, no_prcode_json)
    registry = er.async_get(hass)
    prog_select_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    # Set the program select state to unavailable to test the fallback branch
    hass.states.async_set(prog_select_id, "unavailable")
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    coordinator.async_set_updated_data(coordinator.data)
    await hass.async_block_till_done()

    dur_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert dur_state is not None
    # Cotton (pos 1) resolved via selector_position alone, default soil=2 -> 90 min
    assert dur_state.state == "90"


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

    fixed_now = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
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
    fixed_now = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
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

    fixed_now = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
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

# New Clothes: parent=6 → Output 6 → RAPID_30_MIN (pos=8, selector_position=7, pr_code=71, max_spin_speed=255)
# position=33, spin_speed=1000, soil_level=2
_NFC_NEW_CLOTHES = DownloadableProgram(
    position=33,
    name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_NEW_CLOTHES",
    parent=6,
    temperature=20,
    spin_speed=1000,
    soil_level=2,
    options=0,
    steam=0,
    translations={"en": "New Clothes"},
    category_translations={"en": "Special"},
    description_translations={"en": "Wash new clothes."},
)

# Gym Fit: parent=7 → Output 7 → RAPID_44_MIN (pos=9, selector_position=7, pr_code=103, max_spin_speed=255)
# position=37, spin_speed=1000, soil_level=0 → falls back to base.min_soil_level=3 (Rapid 44')
_NFC_GYM_FIT = DownloadableProgram(
    position=37,
    name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_GYM_FIT",
    parent=7,
    temperature=30,
    spin_speed=1000,
    soil_level=0,
    options=0,
    steam=0,
    translations={"en": "Gym Fit - Fitness"},
    category_translations={"en": "Special"},
    description_translations={"en": "Wash gym and fitness clothes."},
)

# Tablecloths: parent=1 → Output 1 → RESISTANT_COTTONS
# soil_level=3 → duration_soil_max=120 (distinct from default_duration=90 and medium=90)
_NFC_TABLECLOTHS = DownloadableProgram(
    position=58,
    name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_TABLECLOTHS",
    parent=1,
    temperature=60,
    spin_speed=1000,
    soil_level=3,
    options=0,
    steam=0,
    translations={"en": "Tablecloths"},
    category_translations={"en": "Home Care"},
    description_translations={"en": "Wash tablecloths."},
)

_NFC_PROGRAMS = [_NFC_BATHROBE, _NFC_NEW_CLOTHES, _NFC_GYM_FIT, _NFC_TABLECLOTHS]


async def _init_full_control_nfc(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, status_json: str
) -> MockConfigEntry:
    """Init Full Control with NFC switch turned on and NFC test programs."""
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


def test_resolve_downloadable_programs_matches_gym_fit():
    programs = parse_wash_programs(_PROGRAMS)
    resolved = resolve_downloadable_programs([_NFC_GYM_FIT], programs)
    assert len(resolved) == 1
    nfc, base = resolved[0]
    assert nfc.name == "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_GYM_FIT"
    assert base.name == "RAPID_44_MIN"


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
    assert "Rapid 44 Min." in options
    # NFC programs appended with category prefix
    assert "Home Care - Bathrobe" in options
    assert "Home Care - Tablecloths" in options
    assert "Special - New Clothes" in options
    assert "Special - Gym Fit - Fitness" in options


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


def test_nfc_description_sensor_seed_from_coordinator_none():
    """Description sensor handles coordinator update with None status without error."""
    mock_coord = MagicMock()
    mock_coord.data = None
    mock_entry = MagicMock()
    mock_entry.data = {}

    sensor = CandyWashProgramDescriptionSensor(mock_coord, mock_entry)
    sensor._seed_from_coordinator()
    assert sensor.native_value is None


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

    # Select Tablecloths (soil_level=3) — duration should be 120 (duration_soil_max), not default 90
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Home Care - Tablecloths"},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.attributes.get("duration_minutes") == 120
    sensor_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert sensor_state is not None
    assert sensor_state.state == "120"

    # Select Bathrobe (soil_level=2) — duration should be 90 (duration_soil_medium)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Home Care - Bathrobe"},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.attributes.get("duration_minutes") == 90
    sensor_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert sensor_state is not None
    assert sensor_state.state == "90"

    # Select Gym Fit (soil_level=0) — falls back to base soil 3 duration 44
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Special - Gym Fit - Fitness"},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert state is not None
    assert state.attributes.get("duration_minutes") == 44
    sensor_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    assert sensor_state is not None
    assert sensor_state.state == "44"

    # Switch to standard program — duration attribute should be absent
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Whites"},
        blocking=True,
    )
    await hass.async_block_till_done()
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


async def test_start_button_nfc_zero_soil_level_falls_back_to_base_soil_level(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # Gym Fit: position=37, parent=7 → base=RAPID_44_MIN (PrCode=103, selector_position=7)
    # nfc.soil_level=0 is outside RAPID_44_MIN's soil range [3, 3] → falls back to base.min_soil_level=3
    # This ensures the machine runs the 44-minute cycle instead of defaulting to Rapid 14' (SLevTgt=0/1)
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    program_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": program_eid, "option": "Special - Gym Fit - Fitness"},
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
    assert "PrNm=7" in qs
    assert f"PrNm={_NFC_GYM_FIT.position}" not in qs
    assert "PrCode=103" in qs
    assert "PrStr=Gym%20Fit%20-%20Fitness" in qs
    assert "TmpTgt=30" in qs
    assert "SpdTgt=10" in qs  # 1000 // 100
    assert "SLevTgt=3" in qs  # falls back to RAPID_44_MIN min_soil_level (3)
    assert "RecipeId=D_37" in qs


async def test_start_button_nfc_new_clothes(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    # New Clothes: position=33, parent=6 → base=RAPID_30_MIN (PrCode=71, selector_position=7)
    # nfc.soil_level=2 matches RAPID_30_MIN's soil range [2, 2] → SLevTgt=2
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
    assert "PrNm=7" in qs
    assert f"PrNm={_NFC_NEW_CLOTHES.position}" not in qs
    assert "PrCode=71" in qs
    assert "PrStr=New%20Clothes" in qs
    assert "TmpTgt=20" in qs
    assert "SpdTgt=10" in qs  # 1000 // 100
    assert "SLevTgt=2" in qs  # matches base soil level
    assert "RecipeId=D_33" in qs


async def test_start_button_nfc_with_checkup_scheduled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """NFC start button records checkup pending when checkup is scheduled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control-nfc-checkup",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS,
            CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=_IDLE_JSON)
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

    registry = er.async_get(hass)
    nfc_switch_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(entry.entry_id)
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": nfc_switch_eid}, blocking=True
    )

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
    assert "StartCheckUp=1" in qs
    assert "RecipeId=D_33" in qs
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True


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
    rapid_idle = _IDLE_JSON.replace('"Pr": "1"', '"Pr": "7"').replace(
        '"PrCode": "136"', '"PrCode": "71"'
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


async def test_steam_switch_turn_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Steam switch can be turned on and turned off."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    steam_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    )
    assert steam_eid is not None

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": steam_eid}, blocking=True
    )
    assert hass.states.get(steam_eid).state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": steam_eid}, blocking=True
    )
    assert hass.states.get(steam_eid).state == "off"


async def test_nfc_switch_turn_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """NFC special programs switch can be turned off."""
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    nfc_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(entry.entry_id)
    )
    assert nfc_eid is not None
    assert hass.states.get(nfc_eid).state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": nfc_eid}, blocking=True
    )
    assert hass.states.get(nfc_eid).state == "off"


async def test_wash_option_switch_unavailable_when_coordinator_fails(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Wash option switch reports unavailable when coordinator update fails."""
    entry = await _init_full_control_with_options(hass, aioclient_mock, _IDLE_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    registry = er.async_get(hass)
    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_PREWASH.format(entry.entry_id)
    )
    assert prewash_eid is not None
    assert hass.states.get(prewash_eid).state == "off"

    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    assert hass.states.get(prewash_eid).state == "unavailable"


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
# Resume button
# ---------------------------------------------------------------------------


async def test_resume_button_available_when_paused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _PAUSED_JSON)
    resume_state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_BUTTON)
    assert resume_state is not None
    assert resume_state.state != "unavailable"

    # Start and Pause buttons must be unavailable when paused
    start_state = _state(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    assert start_state is not None
    assert start_state.state == "unavailable"

    pause_state = _state(hass, entry, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    assert pause_state is not None
    assert pause_state.state == "unavailable"

    # Stop button must remain available when paused
    stop_state = _state(hass, entry, "button", UNIQUE_ID_WASH_STOP_BUTTON)
    assert stop_state is not None
    assert stop_state.state != "unavailable"


async def test_resume_button_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_resume_button_unavailable_when_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_BUTTON)
    assert state is not None
    assert state.state == "unavailable"


async def test_resume_button_sends_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control(hass, aioclient_mock, _PAUSED_JSON)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_RESUME_BUTTON.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once_with("Pa=0")


async def test_resume_button_present_for_rapido(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_interface_type(
        hass, aioclient_mock, "RAPIDO_4DIG_STM_NEL"
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_BUTTON)
    assert state is not None


async def test_resume_button_absent_for_bianca(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_interface_type(
        hass, aioclient_mock, "BIANCA_SOME_MODEL"
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_BUTTON)
    assert state is None


async def test_resume_button_present_when_no_interface_type(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Existing entries without interface_type in config keep the resume button."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_BUTTON)
    assert state is not None


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


async def test_pause_button_absent_for_dualtech(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_interface_type(
        hass, aioclient_mock, "3D_DUAL"
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    assert state is None


async def test_delay_number_step_dualtech(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_with_interface_type(
        hass, aioclient_mock, "3D_DUAL"
    )
    state = _state(hass, entry, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    assert state is not None
    assert state.attributes.get("step") == 60


async def _init_full_control_dualtech(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    interface_type: str,
    brand: str,
    is_washer_dryer_flag: bool,
    programs: list,
    status_json: str,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-dualtech",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: programs,
            CONF_KEY_INTERFACE_TYPE: interface_type,
            CONF_KEY_BRAND: brand,
            CONF_KEY_IS_WASHER_DRYER: is_washer_dryer_flag,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_dualtech_start_command_defaults(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        False,
        _PROGRAMS,
        _IDLE_JSON,
    )
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
    qs: str = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "Pa=0" in qs
    assert "Sel=0" in qs
    assert "PrNm=1" in qs
    assert "StSt=1" in qs
    assert "Stm=0" in qs
    assert "RecipeId=0" in qs
    assert "CheckUpState=0" in qs
    assert "TmpTgt=" not in qs
    assert "TmpDf=" not in qs
    assert "SLevTgt=" not in qs
    assert "SpdTgt=" not in qs
    assert "SpdDef=" not in qs
    assert "OptMsk=" not in qs
    assert "Option=" not in qs


async def test_dualtech_start_command_custom_temp_spin_soil(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        False,
        _PROGRAMS,
        _IDLE_JSON,
    )
    registry = er.async_get(hass)
    temp_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_TEMP_SELECT.format(entry.entry_id)
    )
    spin_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SPIN_SELECT.format(entry.entry_id)
    )
    soil_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SOIL_SELECT.format(entry.entry_id)
    )
    assert temp_eid is not None
    assert spin_eid is not None
    assert soil_eid is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": temp_eid, "option": "60"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": spin_eid, "option": "1200"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": soil_eid, "option": "high"},
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
    assert "TmpTgt=60" in qs
    assert "TmpDf=40" in qs
    assert "SpdTgt=12" in qs
    assert "SpdDef=8" in qs
    assert "SLevTgt=3" in qs


async def test_dualtech_start_command_delayed_start(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        False,
        _PROGRAMS,
        _IDLE_JSON,
    )
    registry = er.async_get(hass)
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
    )
    assert delay_eid is not None
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid, "value": 120}, blocking=True
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
    assert "DelMd=1" in qs
    assert "DelVl=2" in qs
    assert "StSt=1" not in qs


async def test_dualtech_start_command_washer_dryer_option(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When in wash-only mode, Option sends 0 even if catalog specifies dry=255. When dry target is selected, Option sends the target."""
    # Program with catalog dry=0 (e.g. Silk / Cotton without dry) sends Option=0
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "hoover",
        True,
        _PROGRAMS,
        _IDLE_JSON,
    )
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

    mock_send.assert_called_once()
    qs: str = mock_send.call_args[0][0]
    assert "Option=0" in qs

    # Wash program with catalog dry=255 in wash-only mode sends Option=0 (not 255)
    prog_dry_255 = copy.deepcopy(_COTTON)
    prog_dry_255["program"]["command_parameters"].append(
        {"command_parameter": {"name": "dry", "validation": "255"}}
    )
    entry2 = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "hoover",
        True,
        [prog_dry_255],
        _IDLE_JSON,
    )
    start_eid2 = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry2.entry_id)
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send2:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid2}, blocking=True
        )

    mock_send2.assert_called_once()
    qs2: str = mock_send2.call_args[0][0]
    assert "Option=0" in qs2

    # Wash program with dry target selected sends that target (e.g. cupboard_dry -> Option=2)
    dry_eid2 = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry2.entry_id)
    )
    type_eid2 = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry2.entry_id)
    )
    assert type_eid2 is not None
    assert dry_eid2 is not None
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_eid2, "option": PROGRAM_TYPE_WASH_AND_DRY},
        blocking=True,
    )
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send3:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid2}, blocking=True
        )

    mock_send3.assert_called_once()
    qs3: str = mock_send3.call_args[0][0]
    assert "Option=2" in qs3


async def test_dualtech_start_command_pink_rule(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    cotton_with_options = copy.deepcopy(_COTTON)
    cotton_with_options["program"]["command_parameters"].append(
        {"command_parameter": {"name": "available_options", "validation": "255"}}
    )
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "hoover",
        False,
        [cotton_with_options],
        _IDLE_JSON,
    )
    registry = er.async_get(hass)
    rinse_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_RINSE_1.format(entry.entry_id)
    )
    assert rinse_eid is not None
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

    mock_send.assert_called_once()
    qs: str = mock_send.call_args[0][0]
    assert "OptMsk=128" in qs


async def test_dualtech_start_command_pink_rule_multiple_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When extra rinse (+1, bit 16) is combined with other options, it is remapped to bit 128."""
    cotton_with_options = copy.deepcopy(_COTTON)
    cotton_with_options["program"]["command_parameters"].append(
        {"command_parameter": {"name": "available_options", "validation": "255"}}
    )
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "hoover",
        False,
        [cotton_with_options],
        _IDLE_JSON,
    )
    registry = er.async_get(hass)
    rinse_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_RINSE_1.format(entry.entry_id)
    )
    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_OPTION_PREWASH.format(entry.entry_id)
    )
    assert rinse_eid is not None
    assert prewash_eid is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": rinse_eid}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
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
    # Bit 1 (prewash) + Bit 128 (remapped extra rinse +1) = 129
    assert "OptMsk=129" in qs


async def test_dualtech_stop_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        False,
        _PROGRAMS,
        _RUNNING_JSON,
    )
    registry = er.async_get(hass)
    stop_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_STOP_BUTTON.format(entry.entry_id)
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
    qs: str = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "StSt=0" in qs
    assert "DelMd=0" in qs
    assert "PrNm=1" in qs
    assert "DelVl=" not in qs


async def _init_full_control_nfc_dualtech(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    interface_type: str,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control-nfc-dualtech",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS,
            CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            CONF_KEY_INTERFACE_TYPE: interface_type,
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

    registry = er.async_get(hass)
    nfc_switch_eid = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(entry.entry_id)
    )
    assert nfc_switch_eid is not None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": nfc_switch_eid}, blocking=True
    )
    return entry


async def test_start_button_sends_nfc_dualtech(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_nfc_dualtech(
        hass, aioclient_mock, _IDLE_JSON, "3D_DUAL"
    )
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
    assert "Pa=0" in qs
    assert "Sel=0" in qs
    assert "PrNm=1" in qs
    assert "StSt=1" in qs
    assert "SpdTgt=10" in qs
    assert "SpdDef=8" in qs
    assert "OptMsk=16" in qs
    assert "RecipeId=D_56" in qs
    assert "CheckUpState=0" in qs
    assert "PrCode=" not in qs
    assert "PrStr=" not in qs


async def test_dualtech_start_command_default_soil_9(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        False,
        [_RAPID],
        _IDLE_JSON,
    )
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

    mock_send.assert_called_once()
    qs: str = mock_send.call_args[0][0]
    # default_soil_level is 9, minimum_soil_level is 2 -> sends SLevTgt=2
    assert "SLevTgt=2" in qs


async def test_dualtech_start_command_90c_soil_clamping(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    cotton_prog = copy.deepcopy(_COTTON)
    for cp in cotton_prog["program"]["command_parameters"]:
        if cp["command_parameter"]["name"] == "default_soil_level":
            cp["command_parameter"]["validation"] = "3"
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        False,
        [cotton_prog],
        _IDLE_JSON,
    )
    registry = er.async_get(hass)
    temp_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_TEMP_SELECT.format(entry.entry_id)
    )
    soil_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SOIL_SELECT.format(entry.entry_id)
    )
    assert temp_eid is not None
    assert soil_eid is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": temp_eid, "option": "90"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": soil_eid, "option": "low"},
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
    assert "SLevTgt=2" in qs
    assert "TmpTgt=90" in qs


async def test_dualtech_start_command_dry_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        True,
        _WD_PROGRAMS,
        _IDLE_JSON,
    )
    registry = er.async_get(hass)
    type_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    dry_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    assert type_eid is not None
    assert dry_eid is not None
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_eid, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_eid, "option": DRY_TARGET_EXTRA_DRY},
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
    assert "Pa=0" in qs
    assert "Sel=0" in qs
    assert "PrNm=16" in qs
    assert "StSt=1" in qs
    assert "Option=1" in qs
    assert "TmpTgt=" not in qs
    assert "SLevTgt=" not in qs
    assert "SpdTgt=" not in qs


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
        ("button", UNIQUE_ID_WASH_PAUSE_BUTTON),
        ("button", UNIQUE_ID_WASH_RESUME_BUTTON),
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
    """Full Check-up button requires maintenance_enabled or checkup_enabled."""
    entry = await _init_full_control_with_maintenance(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        _PROGRAMS_WITH_AUTOCLEAN,
        maintenance_enabled=False,
    )
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON)
    assert state is None


async def test_full_checkup_button_present_when_checkup_enabled_without_maintenance(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Full Check-up button is present if checkup_enabled is True even without maintenance counters."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-checkup-no-maint",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: _PROGRAMS_WITH_AUTOCLEAN,
            CONF_KEY_MAINTENANCE_ENABLED: False,
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
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
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = _state(hass, entry, "button", UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON)
    assert state is not None


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


async def _init_full_control_with_maintenance_dualtech(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    programs: list,
    interface_type: str,
) -> MockConfigEntry:
    """Full Control init for DualTech with maintenance enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-maintenance-dualtech",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: programs,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
            CONF_KEY_INTERFACE_TYPE: interface_type,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_full_checkup_button_sends_command_dualtech(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Pressing Full Check-up on DualTech sends Write=1&CheckUpState=1."""
    entry = await _init_full_control_with_maintenance_dualtech(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN, "3D_DUAL"
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
    assert "Write=1" in qs
    assert "CheckUpState=1" in qs


async def test_limescale_button_sends_command_dualtech(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Pressing Limescale Cleaning on DualTech sends dualtech start parameters."""
    entry = await _init_full_control_with_maintenance_dualtech(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN, "3D_DUAL"
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
    assert "Pa=0" in qs
    assert "Sel=0" in qs
    assert "PrNm=23" in qs
    assert "StSt=1" in qs
    assert "RecipeId=0" in qs
    assert "CheckUpState=0" in qs
    assert "PrCode=" not in qs
    assert "PrStr=" not in qs


async def test_dualtech_omits_maintenance_reset_buttons_and_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DualTech omits cycle counter reset buttons and total cycles sensor."""
    entry = await _init_full_control_with_maintenance_dualtech(
        hass, aioclient_mock, _IDLE_JSON, _PROGRAMS_WITH_AUTOCLEAN, "3D_DUAL"
    )
    assert _state(hass, entry, "button", UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON) is not None
    assert _state(hass, entry, "button", UNIQUE_ID_WASH_LIMESCALE_BUTTON) is not None
    # Reset buttons require stats_coordinator and must not be present
    assert (
        _state(hass, entry, "button", UNIQUE_ID_WASH_MAINT_FULL_CHECKUP_BUTTON) is None
    )
    assert _state(hass, entry, "button", UNIQUE_ID_WASH_MAINT_LIMESCALE_BUTTON) is None
    assert _state(hass, entry, "button", UNIQUE_ID_WASH_MAINT_FILTER_BUTTON) is None


# ---------------------------------------------------------------------------
# Washer-Dryer Program Type and Program Filtering Tests
# ---------------------------------------------------------------------------

_COTTON_WD = {
    "program": {
        "position": 1,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "pr_code", "validation": "65"}},
            {"command_parameter": {"name": "program_type", "validation": "W"}},
            {"command_parameter": {"name": "selector_position_dry", "validation": "1"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "90"}},
            {"command_parameter": {"name": "default_temperature", "validation": "60"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1400"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "1000"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "120"}},
            {"command_parameter": {"name": "dry", "validation": "255"}},
        ],
    }
}

_DELICATES_WD = {
    "program": {
        "position": 5,
        "name": "DUAL_WM_WD_PROGRAM_NAME_DELICATES",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "5"}},
            {"command_parameter": {"name": "pr_code", "validation": "4"}},
            {"command_parameter": {"name": "program_type", "validation": "W"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "40"}},
            {"command_parameter": {"name": "default_temperature", "validation": "30"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "400"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "59"}},
            {"command_parameter": {"name": "dry", "validation": "0"}},
        ],
    }
}

_HIGH_DRY_WD = {
    "program": {
        "position": 16,
        "name": "DUAL_WM_WD_PROGRAM_NAME_HIGH_DRY",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "16"}},
            {"command_parameter": {"name": "pr_code", "validation": "45"}},
            {"command_parameter": {"name": "program_type", "validation": "D"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "0"}},
            {"command_parameter": {"name": "default_temperature", "validation": "0"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "0"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "0"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "120"}},
            {"command_parameter": {"name": "dry", "validation": "255"}},
        ],
    }
}

_WD_PROGRAMS = [_COTTON_WD, _DELICATES_WD, _HIGH_DRY_WD]

_LOW_DRY_WD = {
    "program": {
        "position": 17,
        "name": "DUAL_WM_WD_PROGRAM_NAME_LOW_DRY",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "16"}},
            {"command_parameter": {"name": "pr_code", "validation": "75"}},
            {"command_parameter": {"name": "program_type", "validation": "D"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "0"}},
            {"command_parameter": {"name": "default_temperature", "validation": "0"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "0"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "0"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "120"}},
            {"command_parameter": {"name": "dry", "validation": "255"}},
        ],
    }
}

_WD_MULTI_DRY_PROGRAMS = [_COTTON_WD, _DELICATES_WD, _HIGH_DRY_WD, _LOW_DRY_WD]

_RAPID_WD = {
    "program": {
        "position": 16,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_WASH_AND_DRY_59_MIN",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "14"}},
            {"command_parameter": {"name": "pr_code", "validation": "16"}},
            {"command_parameter": {"name": "program_type", "validation": "W"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "30"}},
            {"command_parameter": {"name": "default_temperature", "validation": "30"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1000"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "1000"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "59"}},
            {"command_parameter": {"name": "dry", "validation": "0"}},
        ],
    }
}


async def _init_full_control_wd(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    programs: list[dict],
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-full-control-wd",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_IS_WASHER_DRYER: True,
            CONF_KEY_PROGRAMS: programs,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_program_type_select_omitted_for_wash_only_machine(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Standard washing machines do not expose the Program Type selector."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    assert state is None


async def test_program_type_select_created_for_washer_dryer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Washer-dryers expose the Program Type selector with correct initial options."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    assert state is not None
    assert state.state == PROGRAM_TYPE_WASHING
    assert state.attributes["options"] == [
        PROGRAM_TYPE_WASHING,
        PROGRAM_TYPE_DRYING,
        PROGRAM_TYPE_WASH_AND_DRY,
    ]


async def test_program_select_filtering_across_program_types(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Program list dynamically filters based on the selected Program Type."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    prog_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert type_id is not None
    assert prog_id is not None

    # 1. In 'washing' mode: only wash programs appear
    prog_state = hass.states.get(prog_id)
    assert prog_state is not None
    assert "Whites" in prog_state.attributes["options"]
    assert "Delicates" in prog_state.attributes["options"]
    assert "High Heat Dry" not in prog_state.attributes["options"]

    # 2. Switch to 'drying' mode: only standalone dry programs appear
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )
    prog_state = hass.states.get(prog_id)
    assert prog_state is not None
    assert prog_state.attributes["options"] == ["High Heat Dry"]
    assert prog_state.state == "High Heat Dry"

    # 3. Switch to 'wash_and_dry' mode: only combo-compatible wash programs appear
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASH_AND_DRY},
        blocking=True,
    )
    prog_state = hass.states.get(prog_id)
    assert prog_state is not None
    assert prog_state.attributes["options"] == ["Whites"]
    assert prog_state.state == "Whites"


async def test_program_select_includes_rapid_wash_and_dry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Rapid wash and dry appears in wash_and_dry mode even when catalog specifies program_type W."""
    programs = [_COTTON_WD, _DELICATES_WD, _HIGH_DRY_WD, _RAPID_WD]
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, programs)

    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    prog_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert type_id is not None
    assert prog_id is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASH_AND_DRY},
        blocking=True,
    )
    prog_state = hass.states.get(prog_id)
    assert prog_state is not None
    assert "Wash and Dry 59 Min." in prog_state.attributes["options"]
    assert "Whites" in prog_state.attributes["options"]


async def test_program_select_excludes_flangia_programs_on_dualtech(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """WashProgramSelect excludes flangia bezel parking programs on DualTech interface."""
    flangia_programs = [
        _COTTON,
        {
            "program": {
                "position": 15,
                "name": "DUAL_WM_WD_PROGRAM_NAME_ONE_FI_EXTRA",
                "command_parameters": [
                    {
                        "command_parameter": {
                            "name": "selector_position",
                            "validation": "15",
                        }
                    },
                ],
            }
        },
        {
            "program": {
                "position": 16,
                "name": "DUAL_WM_WD_PROGRAM_NAME_TUMBLING",
                "command_parameters": [
                    {
                        "command_parameter": {
                            "name": "selector_position",
                            "validation": "16",
                        }
                    },
                ],
            }
        },
        {
            "program": {
                "position": 17,
                "name": "DUAL_WM_WD_PROGRAM_NAME_SMART_FI_PLUS",
                "command_parameters": [
                    {
                        "command_parameter": {
                            "name": "selector_position",
                            "validation": "17",
                        }
                    },
                ],
            }
        },
    ]
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        "3D_DUAL",
        "candy",
        False,
        flangia_programs,
        _IDLE_JSON,
    )
    registry = er.async_get(hass)
    prog_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert prog_id is not None
    state = hass.states.get(prog_id)
    assert state is not None
    assert "Whites" in state.attributes["options"]
    for excluded in ("One-Fi Extra", "Tumbling", "Smart-Fi Plus"):
        assert excluded not in state.attributes["options"]


async def test_program_type_select_reflects_idle_dry_cycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Program type selector reflects drying when a dry cycle is selected on dial."""
    dry_idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "16", "PrPh": "0",
        "PrCode": "45", "SLevel": "0", "Temp": "0", "SpinSp": "0",
        "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, dry_idle_json, _WD_PROGRAMS
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    assert state is not None
    assert state.state == PROGRAM_TYPE_DRYING


async def test_program_type_select_reflects_idle_wash_and_dry_cycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Program type selector reflects wash_and_dry when DryT is active on wash program."""
    combo_idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
        "PrCode": "65", "SLevel": "0", "Temp": "60", "SpinSp": "10",
        "DryT": "1", "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, combo_idle_json, _WD_PROGRAMS
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    assert state is not None
    assert state.state == PROGRAM_TYPE_WASH_AND_DRY


async def test_program_type_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Program type selector is unavailable when the machine is running."""
    dry_running_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "16", "PrPh": "2",
        "PrCode": "45", "SLevel": "0", "Temp": "0", "SpinSp": "0",
        "DelVal": "0", "RemTime": "3600", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, dry_running_json, _WD_PROGRAMS
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    assert state is not None
    assert state.state == "unavailable"


async def test_dry_select_omitted_for_wash_only_machine(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Standard washing machines do not expose the Dry Select entity."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is None


async def test_dry_select_created_for_washer_dryer(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Washer-dryers expose the Dry Select entity defaulting to no_dry in washing mode."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is not None
    assert state.state == DRY_TARGET_NO_DRY
    assert state.attributes["options"] == [DRY_TARGET_NO_DRY]


async def test_dry_select_options_and_switching_across_program_types(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dry select options dynamically adapt to Program Type selections."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    assert type_id is not None
    assert dry_id is not None

    # 1. Initially in 'washing': only 'no_dry' is available
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.state == DRY_TARGET_NO_DRY
    assert dry_state.attributes["options"] == [DRY_TARGET_NO_DRY]

    # 2. Switch to 'wash_and_dry': exposes all dry targets and defaults to cupboard_dry
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASH_AND_DRY},
        blocking=True,
    )
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.state == DRY_TARGET_CUPBOARD_DRY
    assert dry_state.attributes["options"] == DRY_TARGET_OPTIONS_FULL

    # 3. User selects iron_dry
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_id, "option": DRY_TARGET_IRON_DRY},
        blocking=True,
    )
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.state == DRY_TARGET_IRON_DRY

    # 4. Switch to 'drying' (standalone dry): exposes dry targets only
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.attributes["options"] == DRY_TARGET_OPTIONS_ONLY_DRY
    assert dry_state.state == DRY_TARGET_IRON_DRY

    # 5. User selects extra_dry
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_id, "option": DRY_TARGET_EXTRA_DRY},
        blocking=True,
    )
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.state == DRY_TARGET_EXTRA_DRY

    # 6. Switch back to 'washing': clamped back to 'no_dry'
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASHING},
        blocking=True,
    )
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.state == DRY_TARGET_NO_DRY
    assert dry_state.attributes["options"] == [DRY_TARGET_NO_DRY]


async def test_dry_select_incompatible_wash_program_clamped(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dry select clamps to no_dry when selecting a program incompatible with drying."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    prog_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    assert type_id is not None
    assert prog_id is not None
    assert dry_id is not None

    # Switch to wash_and_dry mode
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASH_AND_DRY},
        blocking=True,
    )
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.state == DRY_TARGET_CUPBOARD_DRY

    # Switch back to washing mode and select Delicates (incompatible with drying)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASHING},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_id, "option": "Delicates"},
        blocking=True,
    )
    dry_state = hass.states.get(dry_id)
    assert dry_state is not None
    assert dry_state.state == DRY_TARGET_NO_DRY
    assert dry_state.attributes["options"] == [DRY_TARGET_NO_DRY]


async def test_dry_select_reflects_idle_dry_cycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dry select reflects dry target when a dry cycle is selected on dial."""
    dry_idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "16", "PrPh": "0",
        "PrCode": "45", "SLevel": "0", "Temp": "0", "SpinSp": "0",
        "DryT": "1", "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, dry_idle_json, _WD_PROGRAMS
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is not None
    assert state.state == DRY_TARGET_EXTRA_DRY
    assert state.attributes["options"] == DRY_TARGET_OPTIONS_ONLY_DRY


async def test_dry_select_reflects_idle_wash_and_dry_cycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dry select reflects active DryT when dial is on a wash program."""
    combo_idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
        "PrCode": "65", "SLevel": "0", "Temp": "60", "SpinSp": "10",
        "DryT": "1", "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, combo_idle_json, _WD_PROGRAMS
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is not None
    assert state.state == DRY_TARGET_EXTRA_DRY
    assert state.attributes["options"] == DRY_TARGET_OPTIONS_FULL


async def test_dry_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dry select is unavailable when the machine is running."""
    dry_running_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "16", "PrPh": "2",
        "PrCode": "45", "SLevel": "0", "Temp": "0", "SpinSp": "0",
        "DelVal": "0", "RemTime": "3600", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, dry_running_json, _WD_PROGRAMS
    )
    state = _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    assert state is not None
    assert state.state == "unavailable"


async def test_dry_select_invalid_option_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Selecting an invalid dry target raises ServiceValidationError."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    assert dry_id is not None

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": dry_id, "option": "invalid_dry_target"},
            blocking=True,
        )


async def test_start_button_sends_command_wd_wash_only(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Starting a cycle on a washer-dryer in wash-only mode dispatches Dry=0."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert start_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "Write=1" in query_string
    assert "StSt=1" in query_string
    assert "PrNm=1" in query_string
    assert "PrCode=65" in query_string
    assert "Dry=0" in query_string


async def test_start_button_sends_command_wd_wash_and_dry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Starting a cycle on a washer-dryer in wash_and_dry mode dispatches selected Dry target."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert type_id is not None
    assert dry_id is not None
    assert start_id is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASH_AND_DRY},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_id, "option": DRY_TARGET_IRON_DRY},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "Write=1" in query_string
    assert "StSt=1" in query_string
    assert "PrNm=1" in query_string
    assert "PrCode=65" in query_string
    assert "Dry=3" in query_string


async def test_start_button_sends_command_wd_drying(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Starting a standalone drying cycle on a washer-dryer dispatches selected Dry target."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert type_id is not None
    assert dry_id is not None
    assert start_id is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_id, "option": DRY_TARGET_EXTRA_DRY},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "Write=1" in query_string
    assert "StSt=1" in query_string
    assert "PrNm=16" in query_string
    assert "PrCode=45" in query_string
    assert "Dry=1" in query_string
    assert "TmpTgt=0" in query_string
    assert "SpdTgt=0" in query_string
    assert "SLevTgt=0" in query_string


async def test_start_button_unknown_dry_target_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unknown dry target state in the entity state machine raises ValueError upon start."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert dry_id is not None
    assert start_id is not None

    hass.states.async_set(dry_id, "invalid_target")

    with pytest.raises(ValueError, match="Unknown dry target: invalid_target"):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )


async def test_program_disambiguation_same_selector_position(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Selector position shared across multiple drying programs correctly disambiguates via PrCode."""
    low_dry_idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "16", "PrPh": "0",
        "PrCode": "75", "SLevel": "0", "Temp": "0", "SpinSp": "0",
        "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, low_dry_idle_json, _WD_MULTI_DRY_PROGRAMS
    )
    prog_state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    type_state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    assert prog_state is not None
    assert prog_state.state == "Low Heat Dry"
    assert type_state is not None
    assert type_state.state == PROGRAM_TYPE_DRYING


async def test_estimated_duration_washer_dryer_combinations(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Estimated duration sensor dynamically updates when changing program type and dry target."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    dur_id = registry.async_get_entity_id(
        "sensor", DOMAIN, UNIQUE_ID_WASH_ESTIMATED_DURATION.format(entry.entry_id)
    )
    assert type_id is not None
    assert dry_id is not None
    assert dur_id is not None

    # Default washing mode (Cotton): default duration = 120 min, dry_target = no_dry (+0)
    dur_state = hass.states.get(dur_id)
    assert dur_state is not None
    assert dur_state.state == "120"

    # Switch to wash_and_dry mode: dry_target defaults to cupboard_dry (+120 min)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_WASH_AND_DRY},
        blocking=True,
    )
    dur_state = hass.states.get(dur_id)
    assert dur_state is not None
    assert dur_state.state == "240"  # 120 wash + 120 dry

    # Change dry target to iron_dry (+90 min)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_id, "option": DRY_TARGET_IRON_DRY},
        blocking=True,
    )
    dur_state = hass.states.get(dur_id)
    assert dur_state is not None
    assert dur_state.state == "210"  # 120 wash + 90 dry

    # Switch to standalone drying mode (High Heat Dry): returns dry duration
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )
    dur_state = hass.states.get(dur_id)
    assert dur_state is not None
    assert dur_state.state == "90"  # iron_dry duration

    # Change dry target to extra_dry (+150 min)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": dry_id, "option": DRY_TARGET_EXTRA_DRY},
        blocking=True,
    )
    dur_state = hass.states.get(dur_id)
    assert dur_state is not None
    assert dur_state.state == "150"


async def test_start_button_dry_program_forces_zero_parameters(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Dry program forces temp, spin, and soil targets to 0 on start."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert type_id is not None
    assert start_id is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "TmpTgt=0" in query_string
    assert "SpdTgt=0" in query_string
    assert "SLevTgt=0" in query_string


async def test_program_description_disambiguation_multi_programs_same_selector(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Description sensor correctly disambiguates between drying cycles sharing selector 16."""
    low_dry_idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "16", "PrPh": "0",
        "PrCode": "75", "SLevel": "0", "Temp": "0", "SpinSp": "0",
        "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry = await _init_full_control_wd(
        hass, aioclient_mock, low_dry_idle_json, _WD_MULTI_DRY_PROGRAMS
    )
    desc_state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_DESCRIPTION)
    assert desc_state is not None
    assert desc_state.state.startswith("Low temperature drying programme")


async def test_scheduled_finish_idle_updates_on_dry_target_change(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Scheduled finish sensor shifts finish time when program type and dry target change."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    dry_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    delay_id = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
    )
    assert type_id is not None
    assert dry_id is not None
    assert delay_id is not None

    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_id, "value": 60}, blocking=True
    )

    fixed_now = dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
    with patch("homeassistant.util.dt.now", return_value=fixed_now):
        # 1. Washing mode: Cotton (120m) + Delay (60m) = 180m -> 15:00
        hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].async_set_updated_data(
            hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR].data
        )
        await hass.async_block_till_done()
        finish_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_FINISH)
        assert finish_state is not None
        assert "2025-01-01T15:00:00" in finish_state.state

        # 2. Switch to wash_and_dry mode: adds cupboard_dry (+120m) = 300m -> 17:00
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": type_id, "option": PROGRAM_TYPE_WASH_AND_DRY},
            blocking=True,
        )
        finish_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_FINISH)
        assert finish_state is not None
        assert "2025-01-01T17:00:00" in finish_state.state

        # 3. Change dry target to iron_dry (+90m): 120m + 60m + 90m = 270m -> 16:30
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": dry_id, "option": DRY_TARGET_IRON_DRY},
            blocking=True,
        )
        finish_state = _state(hass, entry, "sensor", UNIQUE_ID_WASH_SCHEDULED_FINISH)
        assert finish_state is not None
        assert "2025-01-01T16:30:00" in finish_state.state


async def test_start_button_dry_program_ignores_temp_and_spin_select_values(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Start button forces TmpTgt=0 and SpdTgt=0 on drying cycles regardless of UI select states."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    temp_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_TEMP_SELECT.format(entry.entry_id)
    )
    spin_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SPIN_SELECT.format(entry.entry_id)
    )
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert type_id is not None
    assert start_id is not None

    if temp_id:
        hass.states.async_set(temp_id, "60")
    if spin_id:
        hass.states.async_set(spin_id, "1000")

    steam_id = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    )
    if steam_id:
        hass.states.async_set(steam_id, "on")

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )

    mock_send.assert_called_once()
    query_string: str = mock_send.call_args[0][0]
    assert "TmpTgt=0" in query_string
    assert "SpdTgt=0" in query_string
    assert "SLevTgt=0" in query_string
    assert "OptMsk1=0" in query_string
    assert "Stm=0" in query_string


async def test_start_button_dry_program_with_zero_dry_target_raises(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Attempting to start a drying cycle when dry_target is 0 raises ValueError."""
    entry = await _init_full_control_wd(hass, aioclient_mock, _IDLE_JSON, _WD_PROGRAMS)
    registry = er.async_get(hass)
    type_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert type_id is not None
    assert start_id is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_id, "option": PROGRAM_TYPE_DRYING},
        blocking=True,
    )

    with (
        patch(
            "custom_components.candy.button.WashStartButton._get_dry_target",
            return_value=0,
        ),
        pytest.raises(
            ValueError,
            match="Cannot start drying cycle without a valid dry target setting",
        ),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )


async def test_estimated_duration_delayed_start_falls_back_to_telemetry_dry_target(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Estimated duration uses telemetry dry_target when dry_select is unavailable during delayed start."""
    delayed_json = (
        _IDLE_JSON.replace('"MachMd": "1"', '"MachMd": "5"')
        .replace('"DelVal": "0"', '"DelVal": "60"')
        .replace('"statusLavatrice": {', '"statusLavatrice": {"DryT": "2", ')
    )

    entry = await _init_full_control_wd(
        hass, aioclient_mock, delayed_json, _WD_PROGRAMS
    )
    registry = er.async_get(hass)
    dur_id = registry.async_get_entity_id(
        "sensor", DOMAIN, UNIQUE_ID_WASH_ESTIMATED_DURATION.format(entry.entry_id)
    )
    dry_select_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    assert dur_id is not None
    assert dry_select_id is not None

    # The select entity is unavailable while delayed start is active
    dry_state = hass.states.get(dry_select_id)
    assert dry_state is not None
    assert dry_state.state == "unavailable"

    # Cotton default duration = 120 min, telemetry dry_target = Cupboard dry (+120 min) = 240 min
    dur_state = hass.states.get(dur_id)
    assert dur_state is not None
    assert dur_state.state == "240"


async def test_sub_selects_and_switch_disambiguate_programs_by_program_code(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Sub-selects and switches match program_code on multiplexed dial selector positions."""
    cotton_with_steam = copy.deepcopy(_COTTON_WD)
    for cp in cotton_with_steam["program"]["command_parameters"]:
        if cp["command_parameter"]["name"] == "steam":
            cp["command_parameter"]["validation"] = "1"

    entry = await _init_full_control_wd(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        [cotton_with_steam, _HIGH_DRY_WD, _LOW_DRY_WD],
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Telemetry reports dial position 16 with PrCode 75 (LOW_DRY, max_temp=0, max_spin=0, steam=False)
    payload = json.loads(_IDLE_JSON)["statusLavatrice"]
    payload["Pr"] = "16"
    payload["PrCode"] = "75"
    status_low = WashingMachineStatus.from_json(payload)
    coordinator.async_set_updated_data(status_low)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    temp_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_TEMP_SELECT.format(entry.entry_id)
    )
    spin_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SPIN_SELECT.format(entry.entry_id)
    )
    soil_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SOIL_SELECT.format(entry.entry_id)
    )
    steam_id = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    )

    assert temp_id is not None
    assert spin_id is not None
    assert soil_id is not None
    assert steam_id is not None

    temp_entity = hass.data["select"].get_entity(temp_id)
    spin_entity = hass.data["select"].get_entity(spin_id)
    soil_entity = hass.data["select"].get_entity(soil_id)
    steam_entity = hass.data["switch"].get_entity(steam_id)

    assert temp_entity._active_program().pr_code == 75
    assert spin_entity._active_program().pr_code == 75
    assert soil_entity._active_program().pr_code == 75
    assert steam_entity._active_program().pr_code == 75

    # When running, wash program select is unavailable and steam switch falls back to telemetry
    payload["MachMd"] = "2"
    status_running = WashingMachineStatus.from_json(payload)
    coordinator.async_set_updated_data(status_running)
    await hass.async_block_till_done()

    assert steam_entity._active_program().pr_code == 75


# ---------------------------------------------------------------------------
# Good Night Resume button
# ---------------------------------------------------------------------------


async def test_good_night_resume_button_when_rinse_hold(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    status_dict = json.loads(_RUNNING_JSON)
    status_dict["statusLavatrice"]["PrPh"] = "9"
    gn_json = json.dumps(status_dict)

    entry = await _init_full_control(hass, aioclient_mock, gn_json)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_GOOD_NIGHT)
    assert state is not None
    assert state.state != "unavailable"

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_RESUME_GOOD_NIGHT.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_send.assert_called_once_with("Write=1&RestartGN=1")


async def test_good_night_resume_button_unavailable_when_not_in_rinse_hold(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await _init_full_control(hass, aioclient_mock, _RUNNING_JSON)
    state = _state(hass, entry, "button", UNIQUE_ID_WASH_RESUME_GOOD_NIGHT)
    assert state is not None
    assert state.state == "unavailable"


# ---------------------------------------------------------------------------
# Water Hardness select
# ---------------------------------------------------------------------------


async def test_water_hardness_select(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    extra = {CONF_KEY_INTERFACE_TYPE: "red_devil_axi_ad"}
    entry = await _init_full_control_custom(hass, aioclient_mock, _IDLE_JSON, extra)

    state = _state(hass, entry, "select", UNIQUE_ID_WASH_WATER_HARDNESS)
    assert state is not None
    assert state.attributes["options"] == WATER_HARDNESS_OPTIONS

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_WATER_HARDNESS.format(entry.entry_id)
    )
    assert entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": "hard"},
            blocking=True,
        )

    mock_send.assert_called_once_with("SetHard=3")


# ---------------------------------------------------------------------------
# Auto-dose switches
# ---------------------------------------------------------------------------


async def test_autodose_switches(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    raw_status = json.loads(_IDLE_JSON)
    raw_status["statusLavatrice"]["Det"] = "0"
    raw_status["statusLavatrice"]["Soft"] = "1"
    status_str = json.dumps(raw_status)

    extra = {CONF_KEY_INTERFACE_TYPE: "red_devil_axi_ad"}
    entry = await _init_full_control_custom(hass, aioclient_mock, status_str, extra)

    registry = er.async_get(hass)
    det_id = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_DETERGENT_AUTODOSE.format(entry.entry_id)
    )
    soft_id = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_SOFTENER_AUTODOSE.format(entry.entry_id)
    )
    assert det_id is not None
    assert soft_id is not None

    det_state = hass.states.get(det_id)
    soft_state = hass.states.get(soft_id)
    assert det_state is not None and det_state.state == "off"
    assert soft_state is not None and soft_state.state == "on"

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": det_id}, blocking=True
        )

    mock_send.assert_called_once_with("Write=1&SetDet=1&SetSoft=1")

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": soft_id}, blocking=True
        )

    mock_send.assert_called_once_with("Write=1&SetDet=0&SetSoft=0")


# ---------------------------------------------------------------------------
# Extra Dose switch and start cycle parameter
# ---------------------------------------------------------------------------


async def test_extra_dose_switch_and_start_cycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    extra = {
        CONF_KEY_INTERFACE_TYPE: "red_devil_axi_ad",
        CONF_KEY_PROGRAMS: _PROGRAMS_WITH_OPTIONS,
    }
    entry = await _init_full_control_custom(hass, aioclient_mock, _IDLE_JSON, extra)

    registry = er.async_get(hass)
    ed_id = registry.async_get_entity_id(
        "switch", DOMAIN, UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH.format(entry.entry_id)
    )
    start_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert ed_id is not None
    assert start_id is not None

    assert hass.states.get(ed_id).state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": ed_id}, blocking=True
    )
    assert hass.states.get(ed_id).state == "on"

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_id}, blocking=True
        )

    mock_send.assert_called_once()
    query: str = mock_send.call_args[0][0]
    assert "ED=1" in query


async def test_button_setup_entry_unsupported_coordinator_data(
    hass: HomeAssistant,
) -> None:
    """Test button async_setup_entry exits early when coordinator data is not WashingMachineStatus."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_unsupported_entry",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coordinator = MagicMock()
    coordinator.data = None
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
    }
    added_entities = []
    await async_setup_entry(hass, entry, added_entities.append)
    assert len(added_entities) == 0


def test_build_wash_command_params_soil_level_9() -> None:
    """Test soil level 9 is remapped to program.min_soil_level."""
    programs = parse_wash_programs([_COTTON])
    params = _build_dualtech_start_params(
        program=programs[0],
        temp=programs[0].default_temperature,
        soil=9,
        spin=programs[0].default_spin_speed,
        opt_mask=0,
        steam=False,
        dry=0,
        recipe_id=0,
        checkup=0,
        delay_minutes=0,
        is_washer_dryer=False,
        is_hoover=False,
        interface_type="3D_DUAL",
    )
    assert params.get("SLevTgt") == programs[0].min_soil_level


async def test_start_button_missing_and_invalid_states(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test start button handles invalid entity states by falling back to defaults."""
    entry = await _init_full_control_dualtech(
        hass,
        aioclient_mock,
        interface_type="3D_DUAL",
        brand="candy",
        is_washer_dryer_flag=True,
        programs=_PROGRAMS,
        status_json=_IDLE_JSON,
    )
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
    )
    dry_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(entry.entry_id)
    )
    temp_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_TEMP_SELECT.format(entry.entry_id)
    )
    spin_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SPIN_SELECT.format(entry.entry_id)
    )
    soil_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SOIL_SELECT.format(entry.entry_id)
    )
    assert start_eid is not None
    assert delay_eid is not None
    assert dry_eid is not None

    hass.states.async_set(dry_eid, "unavailable")
    if temp_eid:
        hass.states.async_set(temp_eid, "invalid_int")
    if spin_eid:
        hass.states.async_set(spin_eid, "invalid_int")
    if soil_eid:
        hass.states.async_set(soil_eid, "invalid_soil_key")

    hass.states.async_set("number.dummy_invalid_number", "invalid_float")

    orig_async_get = registry.async_get_entity_id

    def custom_get_entity_id(domain, platform, unique_id):
        if domain == "number":
            return "number.dummy_invalid_number"
        return orig_async_get(domain, platform, unique_id)

    with (
        patch.object(registry, "async_get_entity_id", side_effect=custom_get_entity_id),
        patch(
            "custom_components.candy.button.CandyWashButtonBase._send_command_and_refresh",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    query: str = mock_send.call_args[0][0]
    assert "StSt=1" in query


async def test_start_button_unknown_program_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test start button raises ValueError when program select has unknown name."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    prog_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert start_eid is not None
    assert prog_eid is not None

    hass.states.async_set(prog_eid, "Nonexistent Program")

    with pytest.raises(
        ValueError,
        match="Cannot start: program 'Nonexistent Program' not found in catalog",
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )


async def test_start_button_nfc_program_with_option_mask(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test starting an NFC program with an active option switch includes option mask."""
    entry = await _init_full_control_nfc(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    prog_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id)
    )
    assert start_eid is not None
    assert prog_eid is not None

    # Remove delay entity so _get_number hits entity_id is None branch
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(entry.entry_id)
    )
    if delay_eid:
        registry.async_remove(delay_eid)

    # Register prewash switch and set to on so loop hits opt_mask |= bitmask
    opt_uid = f"{entry.entry_id}-wash_option_prewash"
    opt_entry = registry.async_get_or_create("switch", DOMAIN, opt_uid)
    hass.states.async_set(opt_entry.entity_id, "on")

    # Select the first NFC program
    lang = entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, hass.config.language)
    nfc_name = _NFC_PROGRAMS[0].category_prefixed(lang)
    hass.states.async_set(prog_eid, nfc_name)

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )

    mock_send.assert_called_once()
    query: str = mock_send.call_args[0][0]
    assert "OptMsk=" in query or "PrCode=" in query


async def test_start_button_missing_registry_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test start button returns None for state when entity missing from registry."""
    entry = await _init_full_control(hass, aioclient_mock, _IDLE_JSON)
    registry = er.async_get(hass)
    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert start_eid is not None

    with (
        patch.object(registry, "async_get_entity_id", return_value=None),
        pytest.raises(
            ValueError, match="Cannot start: program 'None' not found in catalog"
        ),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )
