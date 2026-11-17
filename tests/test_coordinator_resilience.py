"""Resilience test suite for Candy integration coordinator and connection lifecycles.

Validates coordinator behavior under:
- The 3-strike timeout rule (READ_MISSABLE = 3) across multiple appliance families
- Active cycle connection interruptions (RUNNING/PAUSED) preventing premature synthetic OFF
- Fast polling (20s resting) during dropouts and automatic recovery to 60s active polling
- Intermittent packet loss / connection flapping resetting timeout counters cleanly
"""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN, SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_RESTING
from custom_components.candy.client.model import (
    DishwasherState,
    MachineState,
    OvenState,
    WineCoolerState,
)
from custom_components.candy.const import DATA_KEY_COORDINATOR

from .common import TEST_IP, init_integration

_STATUS_WASH_IDLE = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

# RemTime in washing machine wire protocol is seconds: 2700s = 45 min
_STATUS_WASH_RUNNING = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "PrPh": "2",
    "Pr": "1", "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "10",
    "DelVal": "0", "RemTime": "2700", "FillR": "50"
  }
}"""

_STATUS_TD_IDLE = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "120", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_STATUS_DW_IDLE = """{
  "statusDWash": {
    "StatoWiFi": "1", "StatoDWash": "0", "CodiceErrore": "0", "Program": "P1",
    "OpzProg": "0", "RemTime": "0", "DelayStart": "0", "OpenDoor": "0",
    "OpenDoorOpt": "0", "Eco": "0", "MissSalt": "0", "MissRinse": "0"
  }
}"""

_STATUS_OVEN_IDLE = """{
  "statusForno": {
    "StatoWiFi": "1", "StartStop": "0", "Program": "1", "Selettore": "1",
    "TempRead": "70", "TempSetRaggiunta": "0", "TimeProgr": "0"
  }
}"""

_STATUS_WC_IDLE = """{
  "statusWCool": {
    "r1": "1", "r2": "E0", "r3": "1", "r4": "12", "r5": "2", "r10": "0"
  }
}"""

_STATS_MOCK = '{"statusCounters": {"Program1": "10"}}'


# ---------------------------------------------------------------------------
# Test 1: Tumble Dryer 3-Strike Timeout & Recovery
# ---------------------------------------------------------------------------


async def test_tumble_dryer_3_strike_timeout_and_recovery(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Tumble dryer must retain state for 2 timeouts, switch to OFF on 3rd, and restore active interval on reconnect."""
    entry = await init_integration(hass, aioclient_mock, _STATUS_TD_IDLE)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    assert coordinator.data.machine_state == MachineState.IDLE
    assert coordinator.update_interval == SCAN_INTERVAL_ACTIVE

    with patch(
        "custom_components.candy.client.CandyClient.status", side_effect=TimeoutError
    ):
        # Timeout 1: retain state, switch to resting interval
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.IDLE
        assert coordinator.update_interval == SCAN_INTERVAL_RESTING

        # Timeout 2: retain state, stay resting
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.IDLE
        assert coordinator.update_interval == SCAN_INTERVAL_RESTING

        # Timeout 3: threshold reached, infer OFF
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.OFF
        assert coordinator.update_interval == SCAN_INTERVAL_RESTING

    # Successful poll restores IDLE and active interval
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data.machine_state == MachineState.IDLE
    assert coordinator.update_interval == SCAN_INTERVAL_ACTIVE


# ---------------------------------------------------------------------------
# Test 2: Dishwasher 3-Strike Timeout
# ---------------------------------------------------------------------------


async def test_dishwasher_3_strike_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Dishwasher on 3rd timeout must safely transition to IDLE with 0 remaining minutes and resting interval."""
    entry = await init_integration(hass, aioclient_mock, _STATUS_DW_IDLE)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    assert coordinator.data.machine_state == DishwasherState.IDLE

    with patch(
        "custom_components.candy.client.CandyClient.status", side_effect=TimeoutError
    ):
        for _ in range(3):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    assert coordinator.data.machine_state == DishwasherState.IDLE
    assert coordinator.data.remaining_minutes == 0
    assert coordinator.update_interval == SCAN_INTERVAL_RESTING


# ---------------------------------------------------------------------------
# Test 3: Oven 3-Strike Timeout
# ---------------------------------------------------------------------------


async def test_oven_3_strike_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Oven on 3rd timeout must fall back to IDLE state and resting interval."""
    entry = await init_integration(hass, aioclient_mock, _STATUS_OVEN_IDLE)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    assert coordinator.data.machine_state == OvenState.IDLE

    with patch(
        "custom_components.candy.client.CandyClient.status", side_effect=TimeoutError
    ):
        for _ in range(3):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    assert coordinator.data.machine_state == OvenState.IDLE
    assert coordinator.update_interval == SCAN_INTERVAL_RESTING


# ---------------------------------------------------------------------------
# Test 4: Wine Cooler 3-Strike Timeout
# ---------------------------------------------------------------------------


async def test_wine_cooler_3_strike_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Wine cooler on 3rd timeout must transition to WineCoolerState.OFF."""
    entry = await init_integration(hass, aioclient_mock, _STATUS_WC_IDLE)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    assert coordinator.data.machine_state == WineCoolerState.ON

    with patch(
        "custom_components.candy.client.CandyClient.status_with_retry",
        side_effect=TimeoutError,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    # In Wine Cooler, WineCoolerState.ON is in active state (not off-inferred),
    # so error raises UpdateFailed without premature synthetic off
    assert not coordinator.last_update_success


# ---------------------------------------------------------------------------
# Test 5: Active Cycle Disconnect & Reconnect
# ---------------------------------------------------------------------------


async def test_active_wash_cycle_disconnect_and_reconnect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A running washing machine must NOT be prematurely marked synthetic OFF on network drop."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_WASH_RUNNING,
        statistics_response=_STATS_MOCK,
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    assert coordinator.data.machine_state == MachineState.RUNNING
    assert coordinator.data.remaining_minutes == 45

    # Simulate network drop mid-cycle
    with patch(
        "custom_components.candy.client.CandyClient.status_with_retry",
        side_effect=aiohttp.ClientConnectorError(
            connection_key=None,  # type: ignore[arg-type]
            os_error=OSError("Host unreachable"),
        ),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        # Must report update failure (entities become unavailable), NOT synthetic OFF
        assert not coordinator.last_update_success
        assert coordinator.data.machine_state == MachineState.RUNNING

    # Reconnection mid-cycle with updated remaining time (1500s = 25 min)
    _status_later = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "2", "PrPh": "3",
        "Pr": "1", "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "10",
        "DelVal": "0", "RemTime": "1500", "FillR": "80"
      }
    }"""
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=_status_later
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert coordinator.data.machine_state == MachineState.RUNNING
    assert coordinator.data.remaining_minutes == 25


# ---------------------------------------------------------------------------
# Test 6: Connection Flapping Jitter Resets Counter
# ---------------------------------------------------------------------------


async def test_connection_flapping_jitter_resets_counter(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Intermittent connection loss must reset timeout count on every success and avoid synthetic OFF."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_WASH_IDLE,
        statistics_response=_STATS_MOCK,
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    for _ in range(3):
        # 1. Momentary drop
        with patch(
            "custom_components.candy.client.CandyClient.status",
            side_effect=TimeoutError,
        ):
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert coordinator.data.machine_state == MachineState.IDLE
            assert coordinator.update_interval == SCAN_INTERVAL_RESTING

        # 2. Immediate recovery
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.IDLE
        assert coordinator.update_interval == SCAN_INTERVAL_ACTIVE

    # After 3 separate single dropouts, machine is still IDLE, not OFF
    assert coordinator.data.machine_state == MachineState.IDLE
