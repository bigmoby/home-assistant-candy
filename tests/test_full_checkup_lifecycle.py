"""Tests for the Full Check-up lifecycle (completion notification, counter auto-reset, appliance reset)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import (
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_USE_ENCRYPTION,
    DATA_KEY_COORDINATOR,
    DATA_KEY_FULL_CHECKUP_UNSUB,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
    MODE_FULL_CONTROL,
    NOTIF_ID_FULL_CHECKUP,
    NOTIF_ID_MAINT_FULL_CHECKUP,
    NOTIF_ID_WASH_ERROR,
    _register_full_checkup_listener,
)
from custom_components.candy.client.model import (
    CheckUpState,
    WashingMachineStatistics,
    WashingMachineStatus,
)
from custom_components.candy.const import MODE_READ_ONLY

from .common import TEST_IP

_STATS_50_CYCLES = '{"statusCounters": {"Temp0to30": "30", "Temp40": "20"}}'
_STATS_51_CYCLES = '{"statusCounters": {"Temp0to30": "31", "Temp40": "20"}}'

_RUNNING_CHECKUP_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "2", "Pr": "3", "PrPh": "2",
    "PrCode": "12", "SLevel": "0", "Temp": "0", "SpinSp": "0",
    "DelVal": "0", "RemTime": "180", "FillR": "0", "CheckUpState": "1", "DisTestRes": "0"
  }
}"""

_COMPLETED_CHECKUP_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "7", "Pr": "3", "PrPh": "0",
    "PrCode": "12", "SLevel": "0", "Temp": "0", "SpinSp": "0",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "2", "DisTestRes": "0"
  }
}"""

_COMPLETED_CHECKUP_LOCAL_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "0", "Err": "0", "MachMd": "7", "Pr": "3", "PrPh": "0",
    "PrCode": "12", "SLevel": "0", "Temp": "0", "SpinSp": "0",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "2", "DisTestRes": "0"
  }
}"""

_ERROR_CHECKUP_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "3", "MachMd": "6", "Pr": "3", "PrPh": "0",
    "PrCode": "12", "SLevel": "0", "Temp": "0", "SpinSp": "0",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "2", "DisTestRes": "0"
  }
}"""

_IDLE_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0", "DisTestRes": "0"
  }
}"""


def _make_entry(**extra) -> MockConfigEntry:
    data = {
        CONF_IP_ADDRESS: TEST_IP,
        CONF_KEY_USE_ENCRYPTION: False,
        CONF_PASSWORD: "",
        CONF_KEY_MODE: MODE_FULL_CONTROL,
        CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0,
    }
    data.update(extra)
    return MockConfigEntry(domain=DOMAIN, unique_id="test-full-checkup", data=data)


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


def test_checkup_state_enum():
    assert CheckUpState.from_code(0) == CheckUpState.IDLE
    assert CheckUpState.from_code(1) == CheckUpState.RUNNING
    assert CheckUpState.from_code(2) == CheckUpState.COMPLETED
    with pytest.raises(ValueError, match="Unrecognized code"):
        CheckUpState.from_code(99)


def test_checkup_state_model_parsing():
    status = WashingMachineStatus.from_json(
        {
            "MachMd": "1",
            "PrPh": "0",
            "Pr": "1",
            "PrCode": "12",
            "Temp": "40",
            "SpinSp": "10",
            "RemTime": "0",
            "WiFiStatus": "1",
            "CheckUpState": "2",
        }
    )
    assert status.checkup_state == CheckUpState.COMPLETED


def test_checkup_state_model_parsing_absent():
    status = WashingMachineStatus.from_json(
        {
            "MachMd": "1",
            "PrPh": "0",
            "Pr": "1",
            "PrCode": "12",
            "Temp": "40",
            "SpinSp": "10",
            "RemTime": "0",
            "WiFiStatus": "1",
        }
    )
    assert status.checkup_state is None


async def test_full_checkup_completion_lifecycle(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Transitioning to CheckUpState=2 notifies, resets maintenance counter, and resets appliance."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_CHECKUP_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    assert coordinator.data.checkup_state == CheckUpState.RUNNING

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("custom_components.candy.asyncio.sleep") as mock_sleep,
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_JSON, _STATS_51_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    # 1. Notification posted
    mock_notify.assert_called_once()
    _, kwargs = mock_notify.call_args
    assert kwargs["title"] == "Full Check-up Results"
    assert "Healthy level: 100%" in mock_notify.call_args[0][1]
    assert "Checks carried out:" in mock_notify.call_args[0][1]
    assert kwargs["notification_id"] == NOTIF_ID_FULL_CHECKUP.format(entry.entry_id)

    # 2. Previous maintenance due notification dismissed
    mock_dismiss.assert_called_once_with(
        hass, NOTIF_ID_MAINT_FULL_CHECKUP.format(entry.entry_id)
    )

    # 3. Counter reset to fresh total cycles (51 from _STATS_51_CYCLES)
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 51

    # 4. Appliance reset command sent and settling delay performed
    mock_send.assert_called_once()
    qs = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "StSt=0" in qs
    assert "PrNm=11" in qs
    assert any(c.args == (5,) for c in mock_sleep.call_args_list)


async def test_full_checkup_completion_localized_italian(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Notification text is localized when configured language is Italian."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _RUNNING_CHECKUP_JSON,
        **{CONF_KEY_PROGRAM_LANGUAGE: "it"},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss"),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ),
        patch("custom_components.candy.asyncio.sleep"),
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_called_once()
    _, kwargs = mock_notify.call_args
    assert kwargs["title"] == "Risultati Check-up Completo"
    assert "Livello di salute: 100%" in mock_notify.call_args[0][1]
    assert "Verifiche effettuate:" in mock_notify.call_args[0][1]


async def test_full_checkup_local_mode_skips_write(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """When remote_control is False, write command is not sent, but notification and reset happen."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_CHECKUP_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss"),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("custom_components.candy.asyncio.sleep") as mock_sleep,
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_LOCAL_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_called_once()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 50
    mock_send.assert_not_called()
    assert not any(c.args == (5,) for c in mock_sleep.call_args_list)


async def test_full_checkup_aborted_does_not_reset_counter(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """If CheckUpState drops from 1 to 0 without reaching 2, do not reset counter or notify."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_CHECKUP_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        _mock_status(aioclient_mock, _IDLE_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_dismiss.assert_not_called()
    mock_send.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 0


async def test_full_checkup_no_duplicate_on_startup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Starting HA when CheckUpState is already 2 does not fire duplicate notification."""
    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        entry = await _setup(hass, aioclient_mock, _COMPLETED_CHECKUP_JSON)
        coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_dismiss.assert_not_called()
    mock_send.assert_not_called()


async def test_full_checkup_from_idle_does_not_fire(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Direct transition from IDLE to COMPLETED without RUNNING does not notify or reset."""
    entry = await _setup(hass, aioclient_mock, _IDLE_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_not_called()
    mock_dismiss.assert_not_called()
    mock_send.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 0


async def test_full_checkup_error_suppresses_completion(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """An appliance error code suppresses completion notification and counter reset."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_CHECKUP_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss") as mock_dismiss,
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        _mock_status(aioclient_mock, _ERROR_CHECKUP_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    # Full check-up completion notification is suppressed, but wash error notification is posted
    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs.get(
        "notification_id"
    ) != NOTIF_ID_FULL_CHECKUP.format(entry.entry_id)
    assert mock_notify.call_args.kwargs.get(
        "notification_id"
    ) == NOTIF_ID_WASH_ERROR.format(entry.entry_id)
    mock_dismiss.assert_not_called()
    mock_send.assert_not_called()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 0


async def test_full_checkup_unloads_cleanly(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """Unloading the config entry calls the full checkup listener unsub callback."""
    entry = await _setup(hass, aioclient_mock, _IDLE_JSON)
    assert DATA_KEY_FULL_CHECKUP_UNSUB in hass.data[DOMAIN][entry.entry_id]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert DOMAIN not in hass.data


def test_full_checkup_coordinator_data_none(
    hass: HomeAssistant,
):
    """When coordinator.data is None, the listener handles it safely without error."""
    mock_coordinator = MagicMock()
    mock_coordinator.data = None
    listener_cb = None

    def mock_add_listener(cb):
        nonlocal listener_cb
        listener_cb = cb
        return MagicMock()

    mock_coordinator.async_add_listener = mock_add_listener

    mock_entry = MagicMock()
    mock_stats_coordinator = MagicMock()
    mock_client = MagicMock()

    _register_full_checkup_listener(
        hass,
        mock_entry,
        mock_coordinator,
        mock_stats_coordinator,
        mock_client,
    )

    assert listener_cb is not None
    with patch("custom_components.candy.pn_async_create") as mock_notify:
        listener_cb()

    mock_notify.assert_not_called()


async def test_full_checkup_stats_none_retains_baseline(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """When stats coordinator is None and stats refresh fails, prior baseline is retained."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _RUNNING_CHECKUP_JSON,
        **{CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 10},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]
    stats_coordinator.async_set_updated_data(None)

    with (
        patch("custom_components.candy.pn_async_create"),
        patch("custom_components.candy.pn_async_dismiss"),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ),
        patch("custom_components.candy.asyncio.sleep"),
        patch.object(
            stats_coordinator, "async_request_refresh", new_callable=AsyncMock
        ),
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 10


async def test_full_checkup_read_only_mode_skips_write(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """When mode is read-only, reset command is not sent even if remote_control is True."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _RUNNING_CHECKUP_JSON,
        **{CONF_KEY_MODE: MODE_READ_ONLY},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create") as mock_notify,
        patch("custom_components.candy.pn_async_dismiss"),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send,
        patch("custom_components.candy.asyncio.sleep") as mock_sleep,
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_notify.assert_called_once()
    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 50
    mock_send.assert_not_called()
    assert not any(c.args == (5,) for c in mock_sleep.call_args_list)


async def test_full_checkup_reset_failure_logs_warning(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """When sending appliance reset fails, the error is logged as a warning without raising."""
    entry = await _setup(hass, aioclient_mock, _RUNNING_CHECKUP_JSON)
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with (
        patch("custom_components.candy.pn_async_create"),
        patch("custom_components.candy.pn_async_dismiss"),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            side_effect=RuntimeError("connection dropped"),
        ),
        patch("custom_components.candy._LOGGER.warning") as mock_warn,
        patch("custom_components.candy.asyncio.sleep"),
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    mock_warn.assert_called_once()
    assert "Failed to reset appliance check-up state" in mock_warn.call_args[0][0]


async def test_full_checkup_completion_restores_from_storage_when_stats_none(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
):
    """When stats coordinator data is None, Full Check-up baseline restores from last known statistics."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _RUNNING_CHECKUP_JSON,
        **{CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 10},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_STATS_COORDINATOR]
    stats_coordinator.async_set_updated_data(None)

    restored_stats = WashingMachineStatistics(total_cycles=388)

    with (
        patch("custom_components.candy.pn_async_create"),
        patch("custom_components.candy.pn_async_dismiss"),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ),
        patch("custom_components.candy.asyncio.sleep"),
        patch.object(stats_coordinator, "async_request_refresh"),
        patch(
            "custom_components.candy._restore_last_known_statistics",
            return_value=restored_stats,
        ),
    ):
        _mock_status(aioclient_mock, _COMPLETED_CHECKUP_JSON, _STATS_50_CYCLES)
        await coordinator.async_request_refresh()
        await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 388
