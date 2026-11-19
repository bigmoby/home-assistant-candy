"""Unit tests for dishwasher program descriptions and error code mappings."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.client.model import DishwasherProgram, TumbleDryerProgram
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DISHWASHER_PROGRAM_PANEL,
    NOTIF_ID_DISHWASHER_ERROR,
    UNIQUE_ID_DISHWASHER_ERROR,
    UNIQUE_ID_DISHWASHER_PROGRAM_DESCRIPTION,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
)
from custom_components.candy.helpers import (
    get_appliance_error_notification_strings,
    get_dishwasher_error_notification_strings,
)

from .common import init_integration

_READY = "dishwasher/remote_ready.json"
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


# ---------------------------------------------------------------------------
# 1. Model Grounding & Namespace Isolation Tests
# ---------------------------------------------------------------------------


def test_dishwasher_program_localization_english() -> None:
    """Verify dishwasher program names and descriptions resolve to authentic dishwasher strings."""
    prog = DishwasherProgram.from_dict({"name": "DW_WIFI_PROG_NAME_ECO"})
    assert prog.localized_name("en") == "Eco 45°C"
    desc = prog.localized_description("en")
    assert desc is not None
    assert "normally soiled tableware" in desc

    prog_zoom = DishwasherProgram.from_dict({"name": "DW_WIFI_PROG_NAME_ZOOM_39"})
    assert prog_zoom.localized_name("en") == "ZOOM 39' 60°C"
    desc_zoom = prog_zoom.localized_description("en")
    assert desc_zoom is not None
    assert "fast washing cycle" in desc_zoom


def test_dishwasher_program_localization_italian() -> None:
    """Verify dishwasher program names and descriptions resolve to Italian strings."""
    prog = DishwasherProgram.from_dict({"name": "DW_WIFI_PROG_NAME_ECO"})
    assert prog.localized_name("it") == "Eco 45°C"
    desc = prog.localized_description("it")
    assert desc is not None
    assert "stoviglie normalmente sporche" in desc


def test_no_namespace_collision_with_dryer() -> None:
    """Verify dishwasher ECO does not collide with tumble dryer ECO."""
    dw_prog = DishwasherProgram.from_dict({"name": "DW_WIFI_PROG_NAME_ECO"})
    td_prog = TumbleDryerProgram.from_dict({"name": "NFC_TD_PROGRAM_NAME_ECO"})

    # Dishwasher must return tableware Eco
    assert dw_prog.localized_name("en") == "Eco 45°C"
    assert "tableware" in dw_prog.localized_description("en")

    # Dryer must return cotton drying
    assert td_prog.localized_name("en") == "ECO Cotton"
    assert "dry a full load of cotton garments" in td_prog.localized_description("en")


# ---------------------------------------------------------------------------
# 2. Error Notification Helper Tests
# ---------------------------------------------------------------------------


def test_get_dishwasher_error_notification_strings_valid_codes() -> None:
    """Verify all 12 verified dishwasher error codes resolve correctly."""
    valid_codes = [2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18]
    for code in valid_codes:
        res_en = get_dishwasher_error_notification_strings(code, "en")
        assert res_en is not None
        title, message = res_en
        assert f"E{code:02d}" in title
        assert "Dishwasher error" in title
        assert f"E{code:02d}" in message
        assert "Customer Service" in message

        res_it = get_dishwasher_error_notification_strings(code, "it")
        assert res_it is not None
        title_it, message_it = res_it
        assert f"E{code:02d}" in title_it
        assert "Errore lavastoviglie" in title_it
        assert "Servizio Clienti" in message_it


def test_get_dishwasher_error_notification_strings_unknown_code() -> None:
    """Verify unknown or zero error codes return None."""
    assert get_dishwasher_error_notification_strings(0, "en") is None
    assert get_dishwasher_error_notification_strings(99, "en") is None


def test_get_appliance_error_notification_strings_invalid_type() -> None:
    """Verify unknown appliance type raises ValueError."""
    with pytest.raises(ValueError):
        get_appliance_error_notification_strings("unknown", 2, "en")


# ---------------------------------------------------------------------------
# 3. Error Sensor Extra State Attributes Tests
# ---------------------------------------------------------------------------


async def test_error_sensor_healthy_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When CodiceErrore is 0, error sensor has no extra state attributes description."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    err_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_ERROR)

    state = hass.states.get(err_id)
    assert state is not None
    assert state.state in ("0", "E0")
    assert "description" not in state.attributes


async def test_error_sensor_with_active_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When CodiceErrore is E02, error sensor exposes description attribute."""
    # Modify fixture to contain CodiceErrore: "E02"
    raw_json = json.loads(load_fixture(_READY))
    raw_json["statusDWash"]["CodiceErrore"] = "E02"

    entry = await init_integration(
        hass,
        aioclient_mock,
        json.dumps(raw_json),
        extra_config_data={CONF_KEY_PROGRAM_LANGUAGE: "en"},
    )
    err_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_ERROR)

    state = hass.states.get(err_id)
    assert state is not None
    assert state.state == "E02"
    assert state.attributes.get("description") == "E02-Troubles with loading water"


async def test_error_sensor_with_active_error_italian(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When language is Italian, error sensor exposes localized Italian description attribute."""
    raw_json = json.loads(load_fixture(_READY))
    raw_json["statusDWash"]["CodiceErrore"] = "E03"

    entry = await init_integration(
        hass,
        aioclient_mock,
        json.dumps(raw_json),
        extra_config_data={CONF_KEY_PROGRAM_LANGUAGE: "it"},
    )
    err_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_ERROR)

    state = hass.states.get(err_id)
    assert state is not None
    assert state.state == "E03"
    assert (
        state.attributes.get("description")
        == "E03-Problema al circuito di scarico acqua"
    )


# ---------------------------------------------------------------------------
# 4. Program Description Sensor Tests
# ---------------------------------------------------------------------------


async def test_program_description_sensor_with_catalog(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Program description sensor displays the description of the selected cycle."""
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
    desc_id = _entity_id(
        hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_DESCRIPTION
    )

    state = hass.states.get(desc_id)
    assert state is not None
    # Initially panel is selected, seeds from status (P17 -> Night)
    assert "Quietest washing cycle" in state.state

    # Change program selection to Eco 45°C
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Eco 45°C"},
        blocking=True,
    )
    desc_state_eco = hass.states.get(desc_id)
    assert desc_state_eco is not None
    assert "normally soiled tableware" in desc_state_eco.state

    # Change program selection to ZOOM 39'
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "ZOOM 39' 60°C"},
        blocking=True,
    )
    desc_state = hass.states.get(desc_id)
    assert desc_state is not None
    assert "fast washing cycle" in desc_state.state

    # Change back to panel
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": DISHWASHER_PROGRAM_PANEL},
        blocking=True,
    )
    desc_state_panel = hass.states.get(desc_id)
    assert desc_state_panel is not None
    assert "Quietest washing cycle" in desc_state_panel.state


# ---------------------------------------------------------------------------
# 5. Persistent Notification Lifecycle Tests
# ---------------------------------------------------------------------------


async def test_persistent_notification_created_and_dismissed_on_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify persistent notification is raised when error rises and dismissed when cleared."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        extra_config_data={CONF_KEY_PROGRAM_LANGUAGE: "en"},
    )
    notif_id = NOTIF_ID_DISHWASHER_ERROR.format(entry.entry_id)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Initially healthy -> no notification
    with (
        patch("custom_components.candy.pn_async_create") as mock_create,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        # Update coordinator with error E02
        raw_err = json.loads(load_fixture(_READY))
        raw_err["statusDWash"]["CodiceErrore"] = "E02"
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{entry.data['ip_address']}/http-read.json",
            json=raw_err,
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Notification must be created
        mock_create.assert_called_once()
        args, kwargs = mock_create.call_args
        assert kwargs["notification_id"] == notif_id
        assert "E02" in kwargs["title"]
        assert "E02-Troubles with loading water" in args[1]
        mock_dismiss.assert_not_called()

    # Clear error back to 0
    with (
        patch("custom_components.candy.pn_async_create") as mock_create,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        raw_ok = json.loads(load_fixture(_READY))
        raw_ok["statusDWash"]["CodiceErrore"] = "0"
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{entry.data['ip_address']}/http-read.json",
            json=raw_ok,
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Notification must be dismissed
        mock_dismiss.assert_called_once_with(hass, notif_id)
        mock_create.assert_not_called()
