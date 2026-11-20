"""Tests for dishwasher maintenance counters, statistics, and diagnostic checkup."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_DISHWASHER,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_WATER_HARDNESS,
    UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON,
    UNIQUE_ID_DISHWASHER_MAINT_FILTER,
    UNIQUE_ID_DISHWASHER_MAINT_FILTER_BUTTON,
    UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP,
    UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP_BUTTON,
    UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE,
    UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE_BUTTON,
    UNIQUE_ID_DISHWASHER_TOTAL_CYCLES,
)
from custom_components.candy.device_trigger import async_get_triggers

from .common import TEST_IP, init_integration

_READY_FIXTURE = "dishwasher/remote_ready.json"
_LEGACY_FIXTURE = "dishwasher/idle.json"


def _make_status_json(fixture_name: str, overrides: dict[str, str]) -> str:
    """Return JSON string with overridden statusDWash fields."""
    data = json.loads(load_fixture(fixture_name))
    data["statusDWash"].update(overrides)
    return json.dumps(data)


def _get_entity_state(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    domain: str,
    unique_id_template: str,
) -> str | None:
    """Return state string for an entity unique_id or None if not registered."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        domain, DOMAIN, unique_id_template.format(entry.entry_id)
    )
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    return state.state if state is not None else None


async def test_modern_dishwasher_statistics_and_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test statistics and maintenance sensors for modern dishwashers."""
    status = _make_status_json(
        _READY_FIXTURE,
        {"r7": "3", "StatoWiFi": "1", "StatoDWash": "2", "CheckUp": "0"},
    )
    stats = json.dumps({"statusCounters": {"s1": "10", "s2": "5", "s3": "15"}})
    entry = await init_integration(
        hass,
        aioclient_mock,
        status,
        stats,
        {
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
            CONF_KEY_IS_DISHWASHER: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: True,
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: True,
            CONF_KEY_WATER_HARDNESS: 2,
        },
    )

    # Total cycles: 10 + 5 + 15 = 30
    cycles = _get_entity_state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_TOTAL_CYCLES)
    assert cycles == "30"

    # Full checkup: 100 - (30 - 0) = 70
    checkup = _get_entity_state(
        hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP
    )
    assert checkup == "70"

    # Filter: 100 - (30 - 0) = 70
    filt = _get_entity_state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_FILTER)
    assert filt == "70"

    # Limescale: r7 is 3 -> threshold 95. 95 - (30 - 0) = 65
    limescale = _get_entity_state(
        hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE
    )
    assert limescale == "65"


async def test_legacy_dishwasher_skips_statistics_and_maintenance(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test that Family 1 legacy dishwashers create no stats or maintenance entities."""
    status = load_fixture(_LEGACY_FIXTURE)
    entry = await init_integration(
        hass,
        aioclient_mock,
        status,
        None,
        {
            CONF_KEY_INTERFACE_TYPE: "DishwasherInterfaceTypeFSTouch",
            CONF_KEY_IS_DISHWASHER: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
        },
    )

    assert (
        _get_entity_state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_TOTAL_CYCLES)
        is None
    )
    assert (
        _get_entity_state(
            hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP
        )
        is None
    )
    assert (
        _get_entity_state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE)
        is None
    )
    assert (
        _get_entity_state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_FILTER)
        is None
    )
    assert (
        _get_entity_state(hass, entry, "button", UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON)
        is None
    )
    assert (
        _get_entity_state(
            hass, entry, "button", UNIQUE_ID_DISHWASHER_MAINT_FILTER_BUTTON
        )
        is None
    )


async def test_modern_dishwasher_maintenance_reset_buttons(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test resetting maintenance baselines via buttons."""
    status = _make_status_json(
        _READY_FIXTURE,
        {"r7": "3", "StatoWiFi": "1", "StatoDWash": "2"},
    )
    stats = json.dumps({"statusCounters": {"s1": "20", "s2": "10"}})
    entry = await init_integration(
        hass,
        aioclient_mock,
        status,
        stats,
        {
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
            CONF_KEY_IS_DISHWASHER: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_WATER_HARDNESS: 2,
        },
    )

    registry = er.async_get(hass)

    # Reset Filter
    filter_btn_id = registry.async_get_entity_id(
        "button",
        DOMAIN,
        UNIQUE_ID_DISHWASHER_MAINT_FILTER_BUTTON.format(entry.entry_id),
    )
    assert filter_btn_id is not None
    await hass.services.async_call(
        "button", "press", {"entity_id": filter_btn_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FILTER] == 30
    assert (
        _get_entity_state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_FILTER)
        == "100"
    )

    # Reset Limescale
    limescale_btn_id = registry.async_get_entity_id(
        "button",
        DOMAIN,
        UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE_BUTTON.format(entry.entry_id),
    )
    assert limescale_btn_id is not None
    await hass.services.async_call(
        "button", "press", {"entity_id": limescale_btn_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 30
    assert (
        _get_entity_state(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE)
        == "95"
    )

    # Reset Check-up
    checkup_btn_id = registry.async_get_entity_id(
        "button",
        DOMAIN,
        UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP_BUTTON.format(entry.entry_id),
    )
    assert checkup_btn_id is not None
    await hass.services.async_call(
        "button", "press", {"entity_id": checkup_btn_id}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 30
    assert (
        _get_entity_state(
            hass, entry, "sensor", UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP
        )
        == "100"
    )


async def test_modern_dishwasher_checkup_button_and_completion_listener(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test checkup button press and subsequent auto-reset upon completion."""
    status_ready = _make_status_json(
        _READY_FIXTURE,
        {"r7": "3", "StatoWiFi": "1", "StatoDWash": "2", "CheckUp": "0"},
    )
    stats = json.dumps({"statusCounters": {"s1": "30"}})
    entry = await init_integration(
        hass,
        aioclient_mock,
        status_ready,
        stats,
        {
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
            CONF_KEY_IS_DISHWASHER: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
        },
    )

    registry = er.async_get(hass)
    checkup_btn = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON.format(entry.entry_id)
    )
    assert checkup_btn is not None

    with (
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": checkup_btn}, blocking=True
        )
        mock_send.assert_called_once_with("StartCheckUp=1")

    # Simulate checkup progression: RUNNING (1) -> COMPLETED (2) with OK (1)
    status_running = _make_status_json(
        _READY_FIXTURE,
        {
            "StatoWiFi": "1",
            "StatoDWash": "3",
            "CheckUp": "1",
            "DisTestRes": "0",
        },
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_running
    )
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    status_completed = _make_status_json(
        _READY_FIXTURE,
        {
            "StatoWiFi": "1",
            "StatoDWash": "2",
            "CheckUp": "2",
            "DisTestRes": "1",
        },
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_completed
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0", text=stats
    )

    with (
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send_reset,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Check-up dismissal command dispatched
        mock_send_reset.assert_called_once_with("Write=1&StartStop=0&Program=11")
        # Baseline auto-reset to total cycles (30)
        assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 30


async def test_dishwasher_device_triggers(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test device triggers for modern vs legacy dishwashers."""
    status = load_fixture(_READY_FIXTURE)
    stats = json.dumps({"statusCounters": {"s1": "10"}})
    modern_entry = await init_integration(
        hass,
        aioclient_mock,
        status,
        stats,
        {
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
            CONF_KEY_IS_DISHWASHER: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
        },
    )

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, modern_entry.entry_id)})
    assert device is not None

    triggers = await async_get_triggers(hass, device.id)
    types = {t["type"] for t in triggers}
    assert "dishwashing_started" in types
    assert "dishwashing_completed" in types
    assert "error_reported" in types
    assert "maintenance_full_checkup_due" in types
    assert "maintenance_limescale_due" in types
    assert "maintenance_filter_due" in types
