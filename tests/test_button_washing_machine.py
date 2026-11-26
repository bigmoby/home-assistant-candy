"""Tests for WashMaintResetButton entities."""

from __future__ import annotations

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.const import (
    CONF_KEY_IS_WASHING_MACHINE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MODE,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    MAINTENANCE_FULL_CHECKUP_THRESHOLD,
    MODE_FULL_CONTROL,
    UNIQUE_ID_WASH_TOTAL_CYCLES,
)

from .common import TEST_IP

_FULL_CHECKUP_BTN = "button.washing_machine_check_up_maintenance_reset"
_LIMESCALE_BTN = "button.washing_machine_limescale_maintenance_reset"
_FILTER_BTN = "button.washing_machine_filter_maintenance_reset"

# ---------------------------------------------------------------------------
# Shared config and helpers
# ---------------------------------------------------------------------------

_MAINTENANCE_CONFIG = {
    CONF_KEY_IS_WASHING_MACHINE: True,
    CONF_KEY_MAINTENANCE_ENABLED: True,
    CONF_KEY_WATER_HARDNESS: 2,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 348,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 348,
    CONF_KEY_MAINTENANCE_LAST_FILTER: 348,
    CONF_KEY_MODE: MODE_FULL_CONTROL,
}


async def _init(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    extra_config_data: dict,
    with_statistics: bool = True,
) -> MockConfigEntry:
    data = {
        CONF_IP_ADDRESS: TEST_IP,
        CONF_KEY_USE_ENCRYPTION: False,
        CONF_PASSWORD: "",
    }
    data.update(extra_config_data)

    entry = MockConfigEntry(domain=DOMAIN, unique_id="test-maint-reset", data=data)
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=load_fixture("washing_machine/idle.json"),
    )
    if with_statistics:
        aioclient_mock.get(
            f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
            text='{"response":"SUCCESS"}',
        )
        aioclient_mock.get(
            f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
            text=load_fixture("washing_machine/statistics.json"),
        )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ---------------------------------------------------------------------------
# Presence tests
# ---------------------------------------------------------------------------


async def test_reset_buttons_present_when_maintenance_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    assert hass.states.get(_FULL_CHECKUP_BTN) is not None
    assert hass.states.get(_LIMESCALE_BTN) is not None
    assert hass.states.get(_FILTER_BTN) is not None


async def test_reset_buttons_absent_when_maintenance_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_MAINTENANCE_ENABLED] = False

    await _init(hass, aioclient_mock, config)

    assert hass.states.get(_FULL_CHECKUP_BTN) is None
    assert hass.states.get(_LIMESCALE_BTN) is None
    assert hass.states.get(_FILTER_BTN) is None


async def test_reset_buttons_absent_without_statistics(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG, with_statistics=False)

    assert hass.states.get(_FULL_CHECKUP_BTN) is None
    assert hass.states.get(_LIMESCALE_BTN) is None
    assert hass.states.get(_FILTER_BTN) is None


# ---------------------------------------------------------------------------
# Reset logic tests — total_cycles=40 (10+25+5 from statistics fixture)
# ---------------------------------------------------------------------------


async def test_reset_full_checkup_stores_total_cycles(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Pressing resets last_reset to total_cycles (388)."""
    entry = await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _FULL_CHECKUP_BTN},
        blocking=True,
    )

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 388


async def test_reset_limescale_stores_total_cycles(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _LIMESCALE_BTN},
        blocking=True,
    )

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 388


async def test_reset_filter_stores_total_cycles(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _FILTER_BTN},
        blocking=True,
    )

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FILTER] == 388


async def test_reset_full_checkup_sensor_shows_full_threshold_after_reset(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """After reset, sensor immediately reflects full threshold without waiting for poll."""
    await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    # Before: total=388, last=348 → 60 remaining
    assert (
        hass.states.get(
            "sensor.washing_machine_check_up_maintenance_remaining_cycles"
        ).state
        == "60"
    )

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _FULL_CHECKUP_BTN},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(
        "sensor.washing_machine_check_up_maintenance_remaining_cycles"
    ).state == str(MAINTENANCE_FULL_CHECKUP_THRESHOLD)


async def test_reset_counter_that_is_overdue(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Counter at 0 (overdue) returns to full threshold after reset."""
    # total=388, last=288 → elapsed=100 → due (sensor=0)
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = 288

    await _init(hass, aioclient_mock, config)

    assert (
        hass.states.get(
            "sensor.washing_machine_check_up_maintenance_remaining_cycles"
        ).state
        == "0"
    )

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _FULL_CHECKUP_BTN},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(
        "sensor.washing_machine_check_up_maintenance_remaining_cycles"
    ).state == str(MAINTENANCE_FULL_CHECKUP_THRESHOLD)


async def test_reset_idempotent_when_already_at_max(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Pressing again when counter is already at max is a no-op."""
    # total=388, last=388 → sensor already shows full threshold
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = 388

    entry = await _init(hass, aioclient_mock, config)

    assert hass.states.get(
        "sensor.washing_machine_check_up_maintenance_remaining_cycles"
    ).state == str(MAINTENANCE_FULL_CHECKUP_THRESHOLD)

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _FULL_CHECKUP_BTN},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 388
    assert hass.states.get(
        "sensor.washing_machine_check_up_maintenance_remaining_cycles"
    ).state == str(MAINTENANCE_FULL_CHECKUP_THRESHOLD)


async def test_reset_when_stats_coordinator_data_unavailable_uses_restored_stats(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When stats data is None at press time, reset recovers baseline from restored sensor."""
    entry = await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    # Force stats coordinator data to None (e.g. appliance is off)
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]
    stats_coordinator.data = None

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _FULL_CHECKUP_BTN},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Baseline is set to 388 (recovered total cycles from sensor state), not corrupted to 0
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 388
    # sensor returns unknown because coordinator.data is None and no restored value
    assert (
        hass.states.get(
            "sensor.washing_machine_check_up_maintenance_remaining_cycles"
        ).state
        == "unknown"
    )


async def test_reset_when_stats_and_sensor_unavailable_preserves_baseline(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When both stats data and total cycles sensor are unavailable, existing baseline is preserved."""
    entry = await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    # Force stats coordinator data to None
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]
    stats_coordinator.data = None

    # Clear sensor state to simulate no prior recorded total cycles
    total_sensor_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, UNIQUE_ID_WASH_TOTAL_CYCLES.format(entry.entry_id)
    )
    assert total_sensor_id is not None
    hass.states.async_set(total_sensor_id, "unknown")

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _FULL_CHECKUP_BTN},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Baseline is preserved at previous value (348), avoiding corruption to 0
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 348


async def test_reset_button_available_when_offline(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Reset buttons must remain available even when the main coordinator is offline."""
    entry = await _init(hass, aioclient_mock, _MAINTENANCE_CONFIG)

    btn_state = hass.states.get(_FULL_CHECKUP_BTN)
    assert btn_state is not None
    assert btn_state.state != "unavailable"

    # Simulate main coordinator reporting update failure
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    coordinator.last_update_success = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    btn_state = hass.states.get(_FULL_CHECKUP_BTN)
    assert btn_state is not None
    assert btn_state.state != "unavailable"
