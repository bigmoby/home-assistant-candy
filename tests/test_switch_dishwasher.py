"""Unit tests for the dishwasher switch platform."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH,
    UNIQUE_ID_DISHWASHER_ECO_SWITCH,
    UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH,
    UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
    UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH,
)
from custom_components.candy.switch import _CandyDishwasherSwitchBase

from .common import init_integration

_READY = "dishwasher/remote_ready.json"
_RUNNING = "dishwasher/remote_running.json"
_CATALOG_PATH = Path(__file__).parent / "fixtures" / "catalog_serial_40_brava_dw.json"


def _load_dw_catalog() -> dict:
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, unique_id.format(entry.entry_id)
    )
    assert entity_id is not None
    return entity_id


def _optional_entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, unique_id.format(entry.entry_id)
    )


async def test_switches_toggle_and_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test toggling all dishwasher switches and observing in-memory state overrides."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        extra_config_data={"interface_type": "BRAVA_BI_DIGIT_OD"},
    )

    eco_id = _entity_id(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH)
    three_in_one_id = _entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH
    )
    half_load_id = _entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH
    )
    extra_dry_id = _entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH
    )
    auto_door_id = _entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH
    )

    # Initial state reflects panel values (all off in remote_ready)
    assert hass.states.get(eco_id).state == "off"
    assert hass.states.get(three_in_one_id).state == "off"
    assert hass.states.get(half_load_id).state == "off"
    assert hass.states.get(extra_dry_id).state == "off"
    assert hass.states.get(auto_door_id).state == "off"

    # Turn on eco and half load
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": eco_id}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": half_load_id}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": auto_door_id}, blocking=True
    )

    assert hass.states.get(eco_id).state == "on"
    assert hass.states.get(half_load_id).state == "on"
    assert hass.states.get(auto_door_id).state == "on"

    # Turn off eco
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": eco_id}, blocking=True
    )
    assert hass.states.get(eco_id).state == "off"


async def test_auto_door_switch_not_present_on_non_od_model(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Non-OD dishwasher models do not register the auto-door switch."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        extra_config_data={"interface_type": "DW_WIFI_FS"},
    )
    auto_door_id = _optional_entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH
    )
    assert auto_door_id is None


async def test_switches_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Switches are unavailable while machine is executing a cycle."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_RUNNING),
        extra_config_data={"interface_type": "BRAVA_BI_DIGIT_OD"},
    )
    eco_id = _entity_id(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH)
    assert hass.states.get(eco_id).state == "unavailable"


async def test_switch_availability_gated_by_program_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Switches evaluate program bitmask when an authentic program is selected."""
    catalog = _load_dw_catalog()
    # Program with available_options = 0 (e.g. Pre-wash)
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        extra_config_data={
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: catalog["interface_type"],
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    half_load_id = _entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH
    )

    # Initial state (panel) -> Half Load available
    assert hass.states.get(half_load_id).state != "unavailable"

    # Select Pre-wash (which has available_options: 8, where HalfLoad [bit 1] is not supported)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Pre-wash - 5 min"},
        blocking=True,
    )
    # Pre-wash has options=8 in catalog, so half load (bit 1, value 2) should become unavailable
    assert hass.states.get(half_load_id).state == "unavailable"

    # Select Eco 45°C (which has available_options: 31, allowing half load)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Eco 45°C"},
        blocking=True,
    )
    assert hass.states.get(half_load_id).state != "unavailable"


def test_dishwasher_switch_base_guards() -> None:
    """Test _CandyDishwasherSwitchBase available and is_on guards and abstract _panel_value."""
    coord = MagicMock()
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_sw_base")
    sw = _CandyDishwasherSwitchBase(coord, entry, 0, [])

    # 1. available returns False when super().available is False
    coord.last_update_success = False
    coord.data = None
    assert sw.available is False

    # 2. available returns False when coordinator.data is not DishwasherStatus
    coord.last_update_success = True
    coord.data = None
    assert sw.available is False

    # 3. is_on returns False when data is None and _user_value is None
    assert sw.is_on is False

    # 4. _panel_value raises NotImplementedError
    with pytest.raises(NotImplementedError):
        sw._panel_value()
