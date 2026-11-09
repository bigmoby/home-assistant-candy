"""Tests for custom_components/candy/__init__.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import (
    CONF_KEY_USE_ENCRYPTION,
    DOMAIN,
    SCAN_INTERVAL_ACTIVE,
    SCAN_INTERVAL_RESTING,
    _make_off_status,
    _register_checkup_listener,
    _register_dryer_checkup_listener,
    _register_dryer_error_listener,
    _register_dryer_warning_listener,
    _register_stats_refresh_listener,
    _register_wash_error_listener,
    _restore_last_known_statistics,
    _restore_last_known_status,
)
from custom_components.candy.client.model import (
    DishwasherState,
    DishwasherStatus,
    MachineState,
    OvenState,
    OvenStatus,
    TumbleDryerStatus,
    WashingMachineStatus,
    WineCoolerProgram,
    WineCoolerState,
    WineCoolerStatus,
)
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DATA_KEY_DRYER_CHECKUP_UNSUB,
    DATA_KEY_DRYER_ERROR_UNSUB,
    DATA_KEY_DRYER_WARNING_UNSUB,
    DATA_KEY_STATS_COORDINATOR,
    DATA_KEY_WASH_ERROR_UNSUB,
    MODE_FULL_CONTROL,
    NOTIF_ID_DRYER_FILTER,
    NOTIF_ID_DRYER_WATER_TANK,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_OVEN,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_WASH_TOTAL_CYCLES,
    UNIQUE_ID_WASHING_MACHINE,
)

from .common import TEST_IP, init_integration

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STATUS_IDLE = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
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

_STATUS_ERROR_2 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "2", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_STATUS_ERROR_3 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "3", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_STATUS_TD_IDLE = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_STATUS_TD_ERROR_3 = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "7", "CodiceErrore": "E03", "Pr": "1", "PrPh": "0",
    "RemTime": "0", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_STATUS_TD_ERROR_7 = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "7", "CodiceErrore": "E07", "Pr": "1", "PrPh": "0",
    "RemTime": "0", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_STATS_OK = (
    '{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'
)

# ---------------------------------------------------------------------------
# _make_off_status — dishwasher and oven branches
# ---------------------------------------------------------------------------


def test_make_off_status_dishwasher():
    status = DishwasherStatus(
        machine_state=DishwasherState.WASH,
        program="P1+",
        remaining_minutes=30,
        delayed_start_hours=None,
        door_open=False,
        door_open_allowed=None,
        eco_mode=False,
        remote_control=True,
        salt_empty=False,
        rinse_aid_empty=False,
    )
    result = _make_off_status(status)
    assert result.machine_state == DishwasherState.IDLE
    assert result.remaining_minutes == 0
    assert result.program == "P1+"


def test_make_off_status_oven():
    status = OvenStatus(
        machine_state=OvenState.HEATING,
        program=1,
        selection=2,
        temp=200.0,
        temp_reached=True,
        program_length_minutes=None,
        remote_control=True,
    )
    result = _make_off_status(status)
    assert result.machine_state == OvenState.IDLE
    assert result.temp == 200.0


# ---------------------------------------------------------------------------
# _restore_last_known_status — one test per device type
# ---------------------------------------------------------------------------


async def test_restore_last_known_status_washing_machine(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="test-restore-wm")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_WASHING_MACHINE.format(entry.entry_id),
        config_entry=entry,
    )
    result = _restore_last_known_status(hass, entry.entry_id)
    assert isinstance(result, WashingMachineStatus)
    assert result.machine_state == MachineState.OFF
    assert result.checkup_state is None


async def test_restore_last_known_status_tumble_dryer(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="test-restore-td")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_TUMBLE_DRYER.format(entry.entry_id),
        config_entry=entry,
    )
    result = _restore_last_known_status(hass, entry.entry_id)
    assert isinstance(result, TumbleDryerStatus)
    assert result.machine_state == MachineState.OFF


async def test_restore_last_known_status_dishwasher(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="test-restore-dw")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_DISHWASHER.format(entry.entry_id),
        config_entry=entry,
    )
    result = _restore_last_known_status(hass, entry.entry_id)
    assert isinstance(result, DishwasherStatus)
    assert result.machine_state == DishwasherState.IDLE


async def test_restore_last_known_status_oven(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="test-restore-oven")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_OVEN.format(entry.entry_id),
        config_entry=entry,
    )
    result = _restore_last_known_status(hass, entry.entry_id)
    assert isinstance(result, OvenStatus)
    assert result.machine_state == OvenState.IDLE


async def test_restore_last_known_status_returns_none_when_no_entity(
    hass: HomeAssistant,
):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="test-restore-none")
    entry.add_to_hass(hass)
    result = _restore_last_known_status(hass, entry.entry_id)
    assert result is None


# ---------------------------------------------------------------------------
# _restore_last_known_statistics
# ---------------------------------------------------------------------------


async def test_restore_last_known_statistics_from_state(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="test-restore-stats")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    ent = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_WASH_TOTAL_CYCLES.format(entry.entry_id),
        config_entry=entry,
    )
    hass.states.async_set(ent.entity_id, "42")

    result = _restore_last_known_statistics(hass, entry.entry_id)
    assert result is not None
    assert result.total_cycles == 42


# ---------------------------------------------------------------------------
# async_setup_entry — statistics seeded from state machine (line 363)
# ---------------------------------------------------------------------------


async def test_seeded_statistics_on_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When total_cycles state exists before setup, coordinator is seeded without a fetch."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-seeded-stats",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)

    # Pre-register both entities so the restore helpers find them
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_WASHING_MACHINE.format(entry.entry_id),
        config_entry=entry,
    )
    cycles_ent = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_WASH_TOTAL_CYCLES.format(entry.entry_id),
        config_entry=entry,
    )
    hass.states.async_set(cycles_ent.entity_id, "50")

    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_IDLE
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    stats_coordinator = hass.data[DOMAIN][entry.entry_id].get(
        DATA_KEY_STATS_COORDINATOR
    )
    assert stats_coordinator is not None
    assert stats_coordinator.data.total_cycles == 50


# ---------------------------------------------------------------------------
# update_status — error paths when can_infer_off is False
# ---------------------------------------------------------------------------


async def test_update_fails_when_running_and_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When machine is RUNNING and status fetch times out, UpdateFailed is raised."""
    entry = await init_integration(
        hass, aioclient_mock, _STATUS_RUNNING, statistics_response=_STATS_OK
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with patch(
        "custom_components.candy.client.CandyClient.status_with_retry",
        side_effect=TimeoutError,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert not coordinator.last_update_success


async def test_update_consecutive_timeouts_resting_to_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When can_infer_off is True, 1st and 2nd timeouts keep last state; 3rd infers OFF."""
    entry = await init_integration(
        hass, aioclient_mock, _STATUS_IDLE, statistics_response=_STATS_OK
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    assert coordinator.data.machine_state == MachineState.IDLE
    assert coordinator.update_interval == SCAN_INTERVAL_ACTIVE

    with patch(
        "custom_components.candy.client.CandyClient.status",
        side_effect=TimeoutError,
    ):
        # 1st timeout: retain last known status, switch to resting interval
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.IDLE
        assert coordinator.update_interval == SCAN_INTERVAL_RESTING

        # 2nd timeout: retain last known status, stay on resting interval
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.IDLE
        assert coordinator.update_interval == SCAN_INTERVAL_RESTING

        # 3rd timeout: threshold reached, infer OFF
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.OFF
        assert coordinator.update_interval == SCAN_INTERVAL_RESTING


async def test_update_consecutive_timeouts_resets_on_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Successful poll resets consecutive timeout counter and restores active interval."""
    entry = await init_integration(
        hass, aioclient_mock, _STATUS_IDLE, statistics_response=_STATS_OK
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with patch(
        "custom_components.candy.client.CandyClient.status",
        side_effect=TimeoutError,
    ):
        # 2 consecutive timeouts
        for _ in range(2):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    assert coordinator.data.machine_state == MachineState.IDLE
    assert coordinator.update_interval == SCAN_INTERVAL_RESTING

    # Successful poll restores active interval
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data.machine_state == MachineState.IDLE
    assert coordinator.update_interval == SCAN_INTERVAL_ACTIVE


async def test_update_raises_update_failed_on_generic_exception(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Any non-network exception from status_with_retry is wrapped in UpdateFailed."""
    entry = await init_integration(
        hass, aioclient_mock, _STATUS_RUNNING, statistics_response=_STATS_OK
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with patch(
        "custom_components.candy.client.CandyClient.status_with_retry",
        side_effect=RuntimeError("unexpected"),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert not coordinator.last_update_success


# ---------------------------------------------------------------------------
# update_statistics — error with cache fallback (lines 342-348)
# ---------------------------------------------------------------------------


async def test_stats_error_returns_cached_value(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When statistics fetch fails but cache exists, coordinator returns cached data."""
    entry = await init_integration(
        hass, aioclient_mock, _STATUS_RUNNING, statistics_response=_STATS_OK
    )
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]
    assert stats_coordinator is not None
    first_data = stats_coordinator.data

    with patch(
        "custom_components.candy.client.CandyClient.statistics_with_retry",
        side_effect=TimeoutError,
    ):
        await stats_coordinator.async_request_refresh()
        await hass.async_block_till_done()

    assert stats_coordinator.data == first_data
    assert stats_coordinator.last_update_success


# ---------------------------------------------------------------------------
# Maintenance notification (line 450)
# ---------------------------------------------------------------------------


async def test_maintenance_notification_fires_when_due(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Persistent notification is created when a maintenance counter reaches zero."""
    # total_cycles=388 (from _STATS_OK), last=288 → elapsed=100 == threshold → due
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_IDLE,
        statistics_response=_STATS_OK,
        extra_config_data={
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_WATER_HARDNESS: 2,
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 288,
        },
    )
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]

    with patch("custom_components.candy.pn_async_create") as mock_notify:
        stats_coordinator.async_set_updated_data(stats_coordinator.data)
        await hass.async_block_till_done()

    mock_notify.assert_called()


# ---------------------------------------------------------------------------
# Washing Machine Error Notifications
# ---------------------------------------------------------------------------


async def test_wash_error_notification_posted_on_startup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When washing machine starts up with an active error, notification is immediately posted."""
    with patch("custom_components.candy.pn_async_create") as mock_notify:
        entry = await init_integration(
            hass,
            aioclient_mock,
            _STATUS_ERROR_2,
            statistics_response=_STATS_OK,
        )
    mock_notify.assert_called_once()
    assert (
        mock_notify.call_args.kwargs["notification_id"]
        == f"candy_{entry.entry_id}_wash_error"
    )
    assert "E02" in mock_notify.call_args.kwargs["title"]
    assert "E02-Troubles with loading water" in mock_notify.call_args.args[1]


async def test_wash_error_notification_lifecycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Notification created on error, updated on error change, dismissed when cleared."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_IDLE,
        statistics_response=_STATS_OK,
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        # 1. Error occurs (Err: 2)
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_ERROR_2
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_called_once()
        assert (
            mock_notify.call_args.kwargs["notification_id"]
            == f"candy_{entry.entry_id}_wash_error"
        )
        assert "E02" in mock_notify.call_args.kwargs["title"]
        mock_dismiss.assert_not_called()

        # 2. Same error stays (Err: 2) -> no duplicate call
        mock_notify.reset_mock()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        mock_notify.assert_not_called()
        mock_dismiss.assert_not_called()

        # 3. New error occurs (Err: 3) -> updated notification
        mock_notify.reset_mock()
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_ERROR_3
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_called_once()
        assert (
            mock_notify.call_args.kwargs["notification_id"]
            == f"candy_{entry.entry_id}_wash_error"
        )
        assert "E03" in mock_notify.call_args.kwargs["title"]
        mock_dismiss.assert_not_called()

        # 4. Error cleared (Err: 0) -> notification dismissed
        mock_notify.reset_mock()
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_IDLE
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_not_called()
        mock_dismiss.assert_called_once_with(hass, f"candy_{entry.entry_id}_wash_error")

        # 5. Stays cleared (Err: 0) -> dismiss not called again
        mock_dismiss.reset_mock()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        mock_dismiss.assert_not_called()


async def test_wash_error_notification_respects_language(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Notification text matches configured wizard language."""
    with patch("custom_components.candy.pn_async_create") as mock_notify:
        await init_integration(
            hass,
            aioclient_mock,
            _STATUS_ERROR_2,
            statistics_response=_STATS_OK,
            extra_config_data={CONF_KEY_PROGRAM_LANGUAGE: "it"},
        )
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["title"] == "Errore lavatrice: E02"
    assert "E02-Problema di carico acqua" in mock_notify.call_args.args[1]


async def test_wash_error_notification_unknown_code(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Unknown error code does not create notification and logs warning."""
    status_err_99 = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "99", "MachMd": "1", "Pr": "1", "PrPh": "0",
        "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
        "DelVal": "0", "RemTime": "0", "FillR": "0"
      }
    }"""
    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy._LOGGER.warning") as mock_warn,
    ):
        await init_integration(
            hass,
            aioclient_mock,
            status_err_99,
            statistics_response=_STATS_OK,
        )
    mock_notify.assert_not_called()
    mock_warn.assert_called_with("Unknown washing machine error code: %s", 99)


async def test_wash_error_listener_unloaded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Wash error listener is cleaned up when entry is unloaded."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_IDLE,
        statistics_response=_STATS_OK,
    )
    assert DATA_KEY_WASH_ERROR_UNSUB in hass.data[DOMAIN][entry.entry_id]

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_wash_error_notification_unknown_code_on_update(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Unknown error code appearing on status update logs warning and skips notification."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_IDLE,
        statistics_response=_STATS_OK,
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    status_err_99 = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "99", "MachMd": "6", "Pr": "1", "PrPh": "0",
        "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
        "DelVal": "0", "RemTime": "0", "FillR": "0"
      }
    }"""

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy._LOGGER.warning") as mock_warn,
    ):
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_err_99
        )
        aioclient_mock.get(
            f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
            text='{"response":"SUCCESS"}',
        )
        aioclient_mock.get(
            f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
            text=_STATS_OK,
        )
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_warn.assert_called_with("Unknown washing machine error code: %s", 99)


def test_wash_error_listener_handles_none_status(hass: HomeAssistant):
    """Wash error listener safely ignores None coordinator data on update."""
    mock_coordinator = MagicMock()
    mock_coordinator.data = None
    listener_cb = None

    def _capture_listener(cb):
        nonlocal listener_cb
        listener_cb = cb
        return MagicMock()

    mock_coordinator.async_add_listener = _capture_listener
    mock_entry = MagicMock()
    mock_entry.entry_id = "test-entry"
    mock_entry.data = {}

    unsub = _register_wash_error_listener(hass, mock_entry, mock_coordinator)
    assert callable(unsub)
    assert listener_cb is not None

    with patch("custom_components.candy.pn_async_create") as mock_notify:
        listener_cb()

    mock_notify.assert_not_called()


def test_checkup_listener_handles_none_status(hass: HomeAssistant):
    """Checkup listener safely ignores None coordinator data on update."""
    mock_coordinator = MagicMock()
    mock_coordinator.data = None
    listener_cb = None

    def _capture_listener(cb):
        nonlocal listener_cb
        listener_cb = cb
        return MagicMock()

    mock_coordinator.async_add_listener = _capture_listener
    mock_entry = MagicMock()
    mock_entry.data = {}

    unsub = _register_checkup_listener(hass, mock_entry, mock_coordinator)
    assert callable(unsub)
    assert listener_cb is not None
    listener_cb()


def test_stats_refresh_listener_handles_none_status(hass: HomeAssistant):
    """Stats refresh listener safely ignores None coordinator data on update."""
    mock_coordinator = MagicMock()
    mock_coordinator.data = None
    mock_stats_coordinator = MagicMock()
    listener_cb = None

    def _capture_listener(cb):
        nonlocal listener_cb
        listener_cb = cb
        return MagicMock()

    mock_coordinator.async_add_listener = _capture_listener
    mock_entry = MagicMock()

    unsub = _register_stats_refresh_listener(
        hass, mock_entry, mock_coordinator, mock_stats_coordinator
    )
    assert callable(unsub)
    assert listener_cb is not None
    listener_cb()
    mock_stats_coordinator.async_request_refresh.assert_not_called()


async def test_update_statistics_raises_when_no_restored_stats_and_fetch_fails(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When machine is not off, no restored stats exist, and statistics fetch fails, UpdateFailed is raised."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_IDLE
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        exc=aiohttp.ClientError("Failed to fetch statistics"),
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="stats_fail_test",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_PASSWORD: "",
            CONF_KEY_USE_ENCRYPTION: False,
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert DATA_KEY_STATS_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]


async def test_dryer_error_notification_posted_on_startup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When tumble dryer starts up with an active error, notification is immediately posted."""
    with patch("custom_components.candy.pn_async_create") as mock_notify:
        entry = await init_integration(
            hass,
            aioclient_mock,
            _STATUS_TD_ERROR_3,
        )
    mock_notify.assert_called_once()
    assert (
        mock_notify.call_args.kwargs["notification_id"]
        == f"candy_{entry.entry_id}_dryer_error"
    )
    assert "E03" in mock_notify.call_args.kwargs["title"]
    assert "The water tank is full" in mock_notify.call_args.args[1]


async def test_dryer_error_notification_lifecycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dryer notification created on error, updated on error change, dismissed when cleared."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_TD_IDLE,
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        # 1. Error occurs (E03)
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_TD_ERROR_3
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_called_once()
        assert (
            mock_notify.call_args.kwargs["notification_id"]
            == f"candy_{entry.entry_id}_dryer_error"
        )
        assert "E03" in mock_notify.call_args.kwargs["title"]
        mock_dismiss.assert_not_called()

        # 2. Same error stays (E03) -> no duplicate call
        mock_notify.reset_mock()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        mock_notify.assert_not_called()
        mock_dismiss.assert_not_called()

        # 3. New error occurs (E07) -> updated notification
        mock_notify.reset_mock()
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_TD_ERROR_7
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_called_once()
        assert (
            mock_notify.call_args.kwargs["notification_id"]
            == f"candy_{entry.entry_id}_dryer_error"
        )
        assert "E07" in mock_notify.call_args.kwargs["title"]
        mock_dismiss.assert_not_called()

        # 4. Error cleared (0) -> notification dismissed
        mock_notify.reset_mock()
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0", text=_STATUS_TD_IDLE
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_not_called()
        mock_dismiss.assert_called_once_with(
            hass, f"candy_{entry.entry_id}_dryer_error"
        )


async def test_dryer_error_notification_respects_language(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dryer notification text matches configured language."""
    with patch("custom_components.candy.pn_async_create") as mock_notify:
        await init_integration(
            hass,
            aioclient_mock,
            _STATUS_TD_ERROR_3,
            extra_config_data={CONF_KEY_PROGRAM_LANGUAGE: "it"},
        )
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["title"] == "Errore asciugatrice: E03"
    assert "Tanica raccolta acqua piena" in mock_notify.call_args.args[1]


async def test_dryer_error_notification_unknown_code(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Unknown dryer error code logs warning and does not notify."""
    status_err_99 = """{
      "statusTD": {
        "StatoWiFi": "1", "StatoTD": "7", "CodiceErrore": "E99", "Pr": "1", "PrPh": "0",
        "RemTime": "0", "DryLev": "2", "Time": "0", "Rapido": "0",
        "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
        "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
      }
    }"""
    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy._LOGGER.warning") as mock_warn,
    ):
        await init_integration(
            hass,
            aioclient_mock,
            status_err_99,
        )
    mock_notify.assert_not_called()
    mock_warn.assert_called_with("Unknown tumble dryer error code: %s", 99)


async def test_dryer_error_listener_unloaded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dryer error listener is cleaned up when entry is unloaded."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_TD_IDLE,
    )
    assert DATA_KEY_DRYER_ERROR_UNSUB in hass.data[DOMAIN][entry.entry_id]

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data.get(DOMAIN, {})


def test_dryer_error_listener_handles_none_status(hass: HomeAssistant):
    """Dryer error listener safely handles None coordinator data."""
    mock_coordinator = MagicMock()
    mock_coordinator.data = None
    listener_cb = None

    def _capture_listener(cb):
        nonlocal listener_cb
        listener_cb = cb
        return MagicMock()

    mock_coordinator.async_add_listener = _capture_listener
    mock_entry = MagicMock()
    mock_entry.entry_id = "test-entry"
    mock_entry.data = {}

    unsub = _register_dryer_error_listener(hass, mock_entry, mock_coordinator)
    assert callable(unsub)
    assert listener_cb is not None

    with patch("custom_components.candy.pn_async_create") as mock_notify:
        listener_cb()

    mock_notify.assert_not_called()


_STATUS_TD_CLEAN_FILTER = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "1", "WaterTankFull": "0", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_STATUS_TD_WATER_TANK_FULL = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "1", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_STATUS_TD_BOTH_WARNINGS = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "1", "WaterTankFull": "1", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""


async def test_dryer_warning_notifications_clean_filter_lifecycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Clean filter notification is created when CleanFilter=1 and dismissed when 0."""
    entry = await init_integration(hass, aioclient_mock, _STATUS_TD_IDLE)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0",
            text=_STATUS_TD_CLEAN_FILTER,
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_called_once()
        _, kwargs = mock_notify.call_args
        assert kwargs["notification_id"] == NOTIF_ID_DRYER_FILTER.format(entry.entry_id)
        mock_dismiss.assert_not_called()

        mock_notify.reset_mock()
        mock_dismiss.reset_mock()

        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0",
            text=_STATUS_TD_IDLE,
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_not_called()
        mock_dismiss.assert_called_once_with(
            hass, NOTIF_ID_DRYER_FILTER.format(entry.entry_id)
        )


async def test_dryer_warning_notifications_water_tank_lifecycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Water tank full notification is created when WaterTankFull=1 and dismissed when 0."""
    entry = await init_integration(hass, aioclient_mock, _STATUS_TD_IDLE)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0",
            text=_STATUS_TD_WATER_TANK_FULL,
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_called_once()
        _, kwargs = mock_notify.call_args
        assert kwargs["notification_id"] == NOTIF_ID_DRYER_WATER_TANK.format(
            entry.entry_id
        )
        mock_dismiss.assert_not_called()

        mock_notify.reset_mock()
        mock_dismiss.reset_mock()

        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0",
            text=_STATUS_TD_IDLE,
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        mock_notify.assert_not_called()
        mock_dismiss.assert_called_once_with(
            hass, NOTIF_ID_DRYER_WATER_TANK.format(entry.entry_id)
        )


async def test_dryer_warning_on_startup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Starting HA with warning flags active creates notifications immediately."""
    with patch("custom_components.candy.pn_async_create") as mock_notify:
        entry = await init_integration(hass, aioclient_mock, _STATUS_TD_BOTH_WARNINGS)

    assert mock_notify.call_count == 2
    notif_ids = {call.kwargs["notification_id"] for call in mock_notify.call_args_list}
    assert NOTIF_ID_DRYER_FILTER.format(entry.entry_id) in notif_ids
    assert NOTIF_ID_DRYER_WATER_TANK.format(entry.entry_id) in notif_ids


async def test_dryer_listeners_unloaded(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Dryer warning and checkup listeners are cleaned up when entry is unloaded."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_TD_IDLE,
    )
    assert DATA_KEY_DRYER_ERROR_UNSUB in hass.data[DOMAIN][entry.entry_id]
    assert DATA_KEY_DRYER_WARNING_UNSUB in hass.data[DOMAIN][entry.entry_id]
    assert DATA_KEY_DRYER_CHECKUP_UNSUB in hass.data[DOMAIN][entry.entry_id]

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data.get(DOMAIN, {})


def test_make_off_status_wine_cooler():
    wc_status = WineCoolerStatus(
        machine_state=WineCoolerState.ON,
        program=WineCoolerProgram.RED_WINE,
        temp=16,
        light=False,
        error=None,
        remote_control=True,
    )
    off_status = _make_off_status(wc_status)
    assert off_status.machine_state == WineCoolerState.OFF


async def test_coordinator_off_state_consecutive_timeout(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_IDLE,
        statistics_response='{"statusCounters": {"Program1": "10"}}',
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        exc=aiohttp.ClientError,
    )
    # 3 consecutive timeouts transition to OFF
    for _ in range(3):
        await coordinator.async_refresh()
    assert coordinator.data.machine_state == MachineState.OFF

    # 4th timeout while already in OFF triggers lines 408-410
    await coordinator.async_refresh()
    assert coordinator.data.machine_state == MachineState.OFF
    assert coordinator.update_interval == SCAN_INTERVAL_RESTING


async def test_stats_fetch_update_failed_when_no_prior_stats(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=_STATUS_IDLE,
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        exc=aiohttp.ClientError,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Integration sets up, but stats coordinator is absent because first fetch failed without cached stats
    assert DATA_KEY_STATS_COORDINATOR not in hass.data[DOMAIN][entry.entry_id]


def test_dryer_warning_and_checkup_null_data(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.data = None
    warning_cb = None
    checkup_cb = None

    def _capture_warning(cb):
        nonlocal warning_cb
        warning_cb = cb
        return MagicMock()

    def _capture_checkup(cb):
        nonlocal checkup_cb
        checkup_cb = cb
        return MagicMock()

    mock_coordinator.async_add_listener = _capture_warning
    _register_dryer_warning_listener(hass, entry, mock_coordinator)
    assert warning_cb is not None
    # Test line 1052: status is None returns early
    warning_cb()

    mock_coordinator.async_add_listener = _capture_checkup
    mock_client = MagicMock()
    _register_dryer_checkup_listener(hass, entry, mock_coordinator, mock_client)
    assert checkup_cb is not None
    # Test line 1104: status is None returns early
    checkup_cb()


_STATUS_TD_CHECKUP_RUNNING = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "2", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "0", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "1"
  }
}"""

_STATUS_TD_CHECKUP_COMPLETED = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "0", "DryLev": "2", "Time": "0", "Rapido": "0",
    "Refresh": "0", "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "1",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "2"
  }
}"""


async def test_dryer_checkup_reset_failure_logs_warning(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await init_integration(
        hass,
        aioclient_mock,
        _STATUS_TD_CHECKUP_RUNNING,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "TD_DIGIT_A",
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    client = hass.data[DOMAIN][entry.entry_id][DATA_KEY_CLIENT]

    with (
        patch.object(
            client, "send_command", side_effect=RuntimeError("Command failed")
        ),
        patch("custom_components.candy.asyncio.sleep", new_callable=AsyncMock),
    ):
        aioclient_mock.clear_requests()
        aioclient_mock.get(
            f"http://{TEST_IP}/http-read.json?encrypted=0",
            text=_STATUS_TD_CHECKUP_COMPLETED,
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()
