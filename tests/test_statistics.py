"""Tests for statistics fetching behaviour."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client.model import MachineState, WashingMachineStatistics
from custom_components.candy.const import (
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
)

from .common import TEST_IP

_STATUS_OFF = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "0", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_STATUS_RUNNING = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "1", "PrPh": "1",
    "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "45", "FillR": "30"
  }
}"""

_STATUS_FINISHED1 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "7", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_STATUS_FINISHED2 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "8", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_STATUS_PAUSED = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "3", "Pr": "1", "PrPh": "1",
    "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "20", "FillR": "50"
  }
}"""

_STATS_OK = (
    '{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'
)


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    with_statistics: bool = True,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-stats",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    if with_statistics:
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


# ---------------------------------------------------------------------------
# OFF guard — skips fetch, returns cache or raises
# ---------------------------------------------------------------------------


async def test_off_guard_raises_when_no_cache(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Machine is OFF with no cached stats: manual refresh must fail with UpdateFailed, no HTTP call."""
    entry = await _setup(hass, aioclient_mock, _STATUS_OFF, with_statistics=False)

    stats_coordinator = hass.data[DOMAIN][entry.entry_id].get(
        DATA_KEY_STATS_COORDINATOR
    )
    # Coordinator is present (initial fetch was skipped cleanly, not failed)
    assert stats_coordinator is not None

    calls_before = len(aioclient_mock.mock_calls)

    # Trigger the hourly poll manually — should raise UpdateFailed without HTTP
    await stats_coordinator.async_request_refresh()
    await hass.async_block_till_done()

    calls_after = len(aioclient_mock.mock_calls)
    assert calls_after == calls_before
    assert not stats_coordinator.last_update_success


async def test_off_guard_returns_cache_without_http_call(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Machine is OFF but cache exists: coordinator must return cached value, no new HTTP call."""
    # Start online so we get a cached statistics value
    entry = await _setup(hass, aioclient_mock, _STATUS_RUNNING, with_statistics=True)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]

    assert stats_coordinator is not None
    first_data = stats_coordinator.data

    # Transition the machine to OFF
    off_status = copy.copy(coordinator.data)
    off_status.machine_state = MachineState.OFF
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()

    # Count HTTP calls before requesting a stats refresh
    calls_before = len(aioclient_mock.mock_calls)

    await stats_coordinator.async_request_refresh()
    await hass.async_block_till_done()

    calls_after = len(aioclient_mock.mock_calls)

    # No new HTTP call should have been made
    assert calls_after == calls_before
    # Cached data is still returned
    assert stats_coordinator.data == first_data


# ---------------------------------------------------------------------------
# Finish-triggered stats refresh
# ---------------------------------------------------------------------------


async def test_stats_refresh_triggered_on_running_to_finished1(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """RUNNING → FINISHED1: stats coordinator must be refreshed."""
    entry = await _setup(hass, aioclient_mock, _STATUS_RUNNING, with_statistics=True)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]

    with patch.object(
        stats_coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        finished_status = copy.copy(coordinator.data)
        finished_status.machine_state = MachineState.FINISHED1
        coordinator.async_set_updated_data(finished_status)
        await hass.async_block_till_done()

    mock_refresh.assert_called_once()


async def test_stats_refresh_triggered_on_running_to_finished2(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """RUNNING → FINISHED2: stats coordinator must be refreshed."""
    entry = await _setup(hass, aioclient_mock, _STATUS_RUNNING, with_statistics=True)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]

    with patch.object(
        stats_coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        finished_status = copy.copy(coordinator.data)
        finished_status.machine_state = MachineState.FINISHED2
        coordinator.async_set_updated_data(finished_status)
        await hass.async_block_till_done()

    mock_refresh.assert_called_once()


async def test_no_refresh_on_finished_to_finished(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """FINISHED1 → FINISHED2: already finished, no second refresh."""
    entry = await _setup(hass, aioclient_mock, _STATUS_FINISHED1, with_statistics=True)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]

    with patch.object(
        stats_coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        finished2_status = copy.copy(coordinator.data)
        finished2_status.machine_state = MachineState.FINISHED2
        coordinator.async_set_updated_data(finished2_status)
        await hass.async_block_till_done()

    mock_refresh.assert_not_called()


async def test_no_refresh_on_running_to_paused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """RUNNING → PAUSED: not a finish event, no refresh."""
    entry = await _setup(hass, aioclient_mock, _STATUS_RUNNING, with_statistics=True)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]

    with patch.object(
        stats_coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as mock_refresh:
        paused_status = copy.copy(coordinator.data)
        paused_status.machine_state = MachineState.PAUSED
        coordinator.async_set_updated_data(paused_status)
        await hass.async_block_till_done()

    mock_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# from_json — Program* counters wrap at 256, temperature counters must not
# ---------------------------------------------------------------------------


def test_total_cycles_survives_program_counter_wraparound():
    """Program11 wrapped from 254 to 5 after seven more washes crossed 256.

    Real incident: total_cycles collapsed from 394 to 139 (a drop of exactly 256)
    because it summed the 8-bit Program* counters. The wide temperature counters
    track the same events and don't wrap, so the total must be derived from those.
    """
    payload = {
        "Program1": "10",
        "Program11": "5",
        "Temp0to30": "318",
        "Temp40": "77",
        "Temp60to90": "0",
    }
    stats = WashingMachineStatistics.from_json(payload)
    assert stats.total_cycles == 395
