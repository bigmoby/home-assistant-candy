"""Tests for the Limescale Cleaning lifecycle (completion notification, counter auto-reset)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import (
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_USE_ENCRYPTION,
    DATA_KEY_COORDINATOR,
    DATA_KEY_LIMESCALE_UNSUB,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
    MODE_FULL_CONTROL,
    NOTIF_ID_LIMESCALE,
    NOTIF_ID_MAINT_LIMESCALE,
    _register_limescale_listener,
)
from custom_components.candy.client.model import (
    MachineState,
    WashingMachineStatistics,
    WashingMachineStatus,
)

from .common import TEST_IP

_STATS_50_CYCLES = '{"statusCounters": {"Temp0to30": "30", "Temp40": "20"}}'
_STATS_51_CYCLES = '{"statusCounters": {"Temp0to30": "31", "Temp40": "20"}}'

_COTTON = {
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
        ],
    }
}

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
        ],
    }
}

_PROGRAMS_WITH_AUTOCLEAN = [_COTTON, _AUTOCLEAN]

_RUNNING_AUTOCLEAN_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "23", "PrPh": "2",
    "PrCode": "104", "SLevel": "0", "Temp": "60", "SpinSp": "0",
    "DelVal": "0", "RemTime": "1800", "FillR": "0"
  }
}"""

_COMPLETED_AUTOCLEAN_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "7", "Pr": "23", "PrPh": "0",
    "PrCode": "104", "SLevel": "0", "Temp": "60", "SpinSp": "0",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_IDLE_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_ERROR_AUTOCLEAN_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "3", "MachMd": "6", "Pr": "23", "PrPh": "0",
    "PrCode": "104", "SLevel": "0", "Temp": "60", "SpinSp": "0",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""

_RUNNING_COTTON_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "1", "PrPh": "2",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "3600", "FillR": "0"
  }
}"""

_COMPLETED_COTTON_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "7", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0"
  }
}"""


def _make_entry(**extra) -> MockConfigEntry:
    data = {
        CONF_IP_ADDRESS: TEST_IP,
        CONF_KEY_USE_ENCRYPTION: False,
        CONF_PASSWORD: "",
        CONF_KEY_MODE: MODE_FULL_CONTROL,
        CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 0,
        CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: True,
        CONF_KEY_PROGRAMS: _PROGRAMS_WITH_AUTOCLEAN,
    }
    data.update(extra)
    return MockConfigEntry(domain=DOMAIN, unique_id="test-limescale", data=data)


def _mock_status(
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    stats_json: str,
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=stats_json,
    )


async def _setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status_json: str,
    **extra_data,
) -> MockConfigEntry:
    entry = _make_entry(**extra_data)
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_50_CYCLES,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_limescale_completion_lifecycle(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Transitioning from running AUTOCLEAN to FINISHED notifies, dismisses due notification, and resets counter."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_AUTOCLEAN_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        _mock_status(aioclient_mock, _COMPLETED_AUTOCLEAN_JSON, _STATS_51_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    # 1. Completion notification posted
    mock_notify.assert_called_once()
    _, kwargs = mock_notify.call_args
    assert kwargs["title"] == "Limescale cleaning completed"
    assert "maintenance counter has been reset" in mock_notify.call_args[0][1]
    assert kwargs["notification_id"] == NOTIF_ID_LIMESCALE.format(entry.entry_id)

    # 2. Previous maintenance due notification dismissed
    mock_dismiss.assert_called_once_with(
        hass, NOTIF_ID_MAINT_LIMESCALE.format(entry.entry_id)
    )

    # 3. Counter reset to fresh total cycles (51 from _STATS_51_CYCLES)
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 51


async def test_limescale_completion_localized_italian(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Italian locale delivers Italian notification title and message."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _RUNNING_AUTOCLEAN_JSON,
        **{CONF_KEY_PROGRAM_LANGUAGE: "it"},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss"),
    ):
        _mock_status(aioclient_mock, _COMPLETED_AUTOCLEAN_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_called_once()
    _, kwargs = mock_notify.call_args
    assert kwargs["title"] == "Pulizia calcare completata"
    assert (
        "contatore di manutenzione è stato reimpostato" in mock_notify.call_args[0][1]
    )


async def test_limescale_aborted_does_not_reset_counter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """If AUTOCLEAN cycle drops to IDLE without reaching FINISHED, do not reset counter or notify."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_AUTOCLEAN_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        _mock_status(aioclient_mock, _IDLE_JSON, _STATS_51_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_dismiss.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 0


async def test_limescale_no_duplicate_on_startup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Starting HA when machine is already finished does not fire duplicate notification."""
    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        entry = await _setup(hass, aioclient_mock, _COMPLETED_AUTOCLEAN_JSON)
        coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_dismiss.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 0


async def test_limescale_from_idle_does_not_fire(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Transitioning directly from IDLE to FINISHED without running does not fire."""
    entry = await _setup(hass, aioclient_mock, _IDLE_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        _mock_status(aioclient_mock, _COMPLETED_AUTOCLEAN_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_dismiss.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 0


async def test_limescale_error_suppresses_completion(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Machine reporting an error suppresses limescale completion."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_AUTOCLEAN_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        _mock_status(aioclient_mock, _ERROR_AUTOCLEAN_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    # Any created notification must not be NOTIF_ID_LIMESCALE
    for call in mock_notify.call_args_list:
        assert call.kwargs.get("notification_id") != NOTIF_ID_LIMESCALE.format(
            entry.entry_id
        )
    mock_dismiss.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 0


async def test_limescale_other_programs_do_not_reset_counter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Standard wash cycles (like Cotton) do not reset the limescale counter."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_COTTON_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        _mock_status(aioclient_mock, _COMPLETED_COTTON_JSON, _STATS_51_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    for call in mock_notify.call_args_list:
        assert call.kwargs.get("notification_id") != NOTIF_ID_LIMESCALE.format(
            entry.entry_id
        )
    mock_dismiss.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 0


async def test_limescale_unloads_cleanly(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Unloading the config entry calls the limescale listener unsub callback."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_AUTOCLEAN_JSON)
    assert DATA_KEY_LIMESCALE_UNSUB in hass.data[DOMAIN][entry.entry_id]

    unsub_mock = MagicMock()
    hass.data[DOMAIN][entry.entry_id][DATA_KEY_LIMESCALE_UNSUB] = unsub_mock

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    unsub_mock.assert_called_once()


def test_limescale_coordinator_data_none(hass: HomeAssistant):
    """_register_limescale_listener handles coordinator.data being None gracefully."""
    coordinator = MagicMock()
    coordinator.data = None
    stats_coordinator = MagicMock()
    entry = _make_entry()

    listener_fn = None

    def _capture_listener(cb):
        nonlocal listener_fn
        listener_fn = cb
        return MagicMock()

    coordinator.async_add_listener = _capture_listener

    unsub = _register_limescale_listener(hass, entry, coordinator, stats_coordinator)
    assert callable(unsub)
    assert listener_fn is not None
    listener_fn()  # Must not raise


async def test_limescale_disabled_skips_registration(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """When maintenance limescale is disabled, listener is inert."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _RUNNING_AUTOCLEAN_JSON,
        **{CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: False},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        _mock_status(aioclient_mock, _COMPLETED_AUTOCLEAN_JSON, _STATS_51_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_dismiss.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 0


async def test_limescale_idle_to_running_to_finished_transition(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Transitioning from IDLE to RUNNING autoclean to FINISHED notifies and resets counter."""
    entry = await _setup(hass, aioclient_mock, _IDLE_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Transition from IDLE to RUNNING AUTOCLEAN
    running_status = WashingMachineStatus.from_json(
        json.loads(_RUNNING_AUTOCLEAN_JSON)["statusLavatrice"]
    )
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()
    assert coordinator.data.machine_state == MachineState.RUNNING

    # Transition from RUNNING AUTOCLEAN to FINISHED
    _mock_status(aioclient_mock, _COMPLETED_AUTOCLEAN_JSON, _STATS_51_CYCLES)
    completed_status = WashingMachineStatus.from_json(
        json.loads(_COMPLETED_AUTOCLEAN_JSON)["statusLavatrice"]
    )
    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
    ):
        coordinator.async_set_updated_data(completed_status)
        await hass.async_block_till_done()
        assert coordinator.data.machine_state == MachineState.FINISHED1

    mock_notify.assert_called_once()
    mock_dismiss.assert_called_once_with(
        hass, NOTIF_ID_MAINT_LIMESCALE.format(entry.entry_id)
    )
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 51


async def test_limescale_completion_restores_from_storage_when_stats_none(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """When stats coordinator data is None, baseline restores from last known statistics."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _RUNNING_AUTOCLEAN_JSON,
        **{CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 10},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]
    stats_coordinator.async_set_updated_data(None)

    restored_stats = WashingMachineStatistics(total_cycles=50)

    with (
        patch("custom_components.candy.pn_async_create"),
        patch("custom_components.candy.pn_async_dismiss"),
        patch.object(stats_coordinator, "async_request_refresh"),
        patch(
            "custom_components.candy._restore_last_known_statistics",
            return_value=restored_stats,
        ),
    ):
        _mock_status(aioclient_mock, _COMPLETED_AUTOCLEAN_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 50
