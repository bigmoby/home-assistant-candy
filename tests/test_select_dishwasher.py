"""Unit tests for the dishwasher select platform (program selection)."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DISHWASHER_PROGRAM_PANEL,
    DISHWASHER_PROGRAMS,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
)

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


async def test_select_fallback_options_when_no_catalog(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When no catalog programs are provided in config, fallback to DISHWASHER_PROGRAMS."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)

    state = hass.states.get(select_id)
    assert state is not None
    assert state.state == DISHWASHER_PROGRAM_PANEL
    expected_options = [DISHWASHER_PROGRAM_PANEL, *DISHWASHER_PROGRAMS.keys()]
    assert state.attributes["options"] == expected_options


async def test_select_with_authentic_catalog_programs_english(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When authentic catalog programs are provided, populate options with localized names."""
    catalog = _load_dw_catalog()
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

    state = hass.states.get(select_id)
    assert state is not None
    assert state.state == DISHWASHER_PROGRAM_PANEL
    options = state.attributes["options"]
    assert options[0] == DISHWASHER_PROGRAM_PANEL
    assert len(options) == 10  # "panel" + 9 programs
    assert "Eco 45°C" in options
    assert "Intensive 75°C" in options
    assert "ZOOM 39' 60°C" in options

    # Select an authentic catalog program
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Eco 45°C"},
        blocking=True,
    )
    assert hass.states.get(select_id).state == "Eco 45°C"

    # Select back to panel
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": DISHWASHER_PROGRAM_PANEL},
        blocking=True,
    )
    assert hass.states.get(select_id).state == DISHWASHER_PROGRAM_PANEL


async def test_select_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Program select becomes unavailable while a cycle is running."""
    catalog = _load_dw_catalog()
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_RUNNING),
        extra_config_data={
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: catalog["interface_type"],
        },
    )
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)

    state = hass.states.get(select_id)
    assert state is not None
    assert state.state == "unavailable"


async def test_select_program_resolution_and_selected_program_property(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test selected_program property in both catalog and fallback modes."""
    # 1. Fallback mode
    entry_fb = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    select_id_fb = _entity_id(
        hass, entry_fb, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT
    )
    entity_fb = hass.data["entity_components"]["select"].get_entity(select_id_fb)
    assert entity_fb is not None
    assert entity_fb.selected_program is None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id_fb, "option": "night_55"},
        blocking=True,
    )
    prog = entity_fb.selected_program
    assert prog is not None
    assert prog.cycle_id == 17
    assert prog.selector_position == 3

    # 2. Catalog mode
    catalog = _load_dw_catalog()
    entry_cat = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        extra_config_data={
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: catalog["interface_type"],
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    select_id_cat = _entity_id(
        hass, entry_cat, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT
    )
    entity_cat = hass.data["entity_components"]["select"].get_entity(select_id_cat)
    assert entity_cat is not None
    assert entity_cat.selected_program is None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id_cat, "option": "Eco 45°C"},
        blocking=True,
    )
    prog_cat = entity_cat.selected_program
    assert prog_cat is not None
    assert prog_cat.cycle_id == 8
    assert prog_cat.selector_position == 1
