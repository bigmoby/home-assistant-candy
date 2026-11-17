"""Tests for the self check-up feature."""

from __future__ import annotations

import contextlib
import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.button import _should_send_checkup
from custom_components.candy.client.model import CheckUpResult, MachineState
from custom_components.candy.const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CHECKUP_SCHEDULE_MONTHLY,
    CHECKUP_SCHEDULE_WEEKLY,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_LAST_DATE,
    CONF_KEY_CHECKUP_LAST_RESULT,
    CONF_KEY_CHECKUP_PENDING,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
    UNIQUE_ID_WASH_CHECKUP_RESULT,
    UNIQUE_ID_WASH_LAST_CHECKUP,
    UNIQUE_ID_WASH_START_BUTTON,
)

from .common import TEST_IP

# ---------------------------------------------------------------------------
# Minimal program entry (SPECIAL_39 matching Pr=1 PrCode=136)
# ---------------------------------------------------------------------------

_SPECIAL_39 = {
    "program": {
        "position": 1,
        "name": "DUAL_WM_WD_PROGRAM_NAME_SPECIAL_39",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "pr_code", "validation": "136"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "40"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1200"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "default_duration", "validation": "39"}},
            {"command_parameter": {"name": "available_options", "validation": "240"}},
        ],
    }
}

_IDLE_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_IDLE_WITH_DIS_TEST_RES_0 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0", "DisTestRes": "0"
  }
}"""

_IDLE_WITH_DIS_TEST_RES_1 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "2", "DisTestRes": "1"
  }
}"""

_IDLE_WITH_DIS_TEST_RES_2 = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "8",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "2", "DisTestRes": "2"
  }
}"""

_STATS_OK = (
    '{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'
)

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**extra) -> MockConfigEntry:
    data = {
        CONF_IP_ADDRESS: TEST_IP,
        CONF_KEY_USE_ENCRYPTION: False,
        CONF_PASSWORD: "",
        CONF_KEY_MODE: MODE_FULL_CONTROL,
        CONF_KEY_PROGRAMS: [_SPECIAL_39],
    }
    data.update(extra)
    return MockConfigEntry(domain=DOMAIN, unique_id="test-checkup", data=data)


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
        text=_STATS_OK,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _sensor_state(hass: HomeAssistant, entry: MockConfigEntry, uid_tpl: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, uid_tpl.format(entry.entry_id)
    )
    if entity_id is None:
        return None
    return hass.states.get(entity_id)


# ---------------------------------------------------------------------------
# Unit tests for _should_send_checkup
# ---------------------------------------------------------------------------


def test_checkup_disabled_returns_0():
    entry = _make_entry(**{CONF_KEY_CHECKUP_ENABLED: False})
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_disabled_ignores_schedule():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: False,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_every_cycle_returns_1():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_every_cycle_returns_1_even_if_recently_run():
    yesterday = (_NOW - timedelta(days=1)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
            CONF_KEY_CHECKUP_LAST_DATE: yesterday,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_weekly_no_last_date_returns_1():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_weekly_8_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=8)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_weekly_3_days_elapsed_returns_0():
    last = (_NOW - timedelta(days=3)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_weekly_exactly_7_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=7)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_monthly_no_last_date_returns_1():
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_monthly_31_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=31)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


def test_checkup_monthly_20_days_elapsed_returns_0():
    last = (_NOW - timedelta(days=20)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 0


def test_checkup_monthly_exactly_30_days_elapsed_returns_1():
    last = (_NOW - timedelta(days=30)).timestamp()
    entry = _make_entry(
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_MONTHLY,
            CONF_KEY_CHECKUP_LAST_DATE: last,
        }
    )
    assert _should_send_checkup(entry, _NOW) == 1


# ---------------------------------------------------------------------------
# CheckUpResult model
# ---------------------------------------------------------------------------


def test_checkup_result_enum_values():
    assert CheckUpResult.NOT_RUN.code == 0
    assert CheckUpResult.OK.code == 1
    assert CheckUpResult.PROBLEM.code == 2


def test_checkup_result_from_code():
    assert CheckUpResult.from_code(0) == CheckUpResult.NOT_RUN
    assert CheckUpResult.from_code(1) == CheckUpResult.OK
    assert CheckUpResult.from_code(2) == CheckUpResult.PROBLEM


# ---------------------------------------------------------------------------
# DisTestRes transition listener — timestamp persistence
# ---------------------------------------------------------------------------


async def test_dis_test_res_transition_0_to_1_writes_result_not_date(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes 0->1: result is cached; date is NOT written by the listener."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT) == CheckUpResult.OK.code
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_dis_test_res_transition_0_to_2_writes_result_not_date(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes 0->2 (problem): result is cached; date is NOT written by the listener."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.PROBLEM
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT) == CheckUpResult.PROBLEM.code
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_dis_test_res_stays_non_zero_no_duplicate_write(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes already non-zero on second update: result not overwritten; date never written."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # First update: 0 -> 1 (listener fires, writes result)
    ok_status = copy.copy(coordinator.data)
    ok_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(ok_status)
    await hass.async_block_till_done()

    first_result = entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT)
    assert first_result == CheckUpResult.OK.code
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None

    # Second update: still 1, no 0->non-zero transition, must NOT overwrite
    still_ok = copy.copy(coordinator.data)
    still_ok.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(still_ok)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT) == first_result
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_dis_test_res_1_to_0_no_write(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """DisTestRes 1→0 (reset/cancel): no timestamp written."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_1,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.NOT_RUN
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_checkup_listener_not_registered_when_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When checkup is disabled, no timestamp is ever written even on transition."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: False},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    new_status = copy.copy(coordinator.data)
    new_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(new_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


# ---------------------------------------------------------------------------
# Sensor registration
# ---------------------------------------------------------------------------


async def test_checkup_result_sensor_registered_when_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_1,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is not None
    assert state.state == "ok"


async def test_checkup_result_sensor_not_registered_when_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_1,
        **{CONF_KEY_CHECKUP_ENABLED: False},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is None


async def test_checkup_result_sensor_problem(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_2,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is not None
    assert state.state == "problem"


async def test_checkup_result_sensor_not_run(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_CHECKUP_RESULT)
    assert state is not None
    assert state.state == "not_run"


async def test_last_checkup_sensor_shows_stored_timestamp(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    ts = _NOW.timestamp()
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_LAST_DATE: ts,
        },
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_LAST_CHECKUP)
    assert state is not None
    assert state.state not in ("unknown", "unavailable")


async def test_last_checkup_sensor_unknown_when_never_run(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    state = _sensor_state(hass, entry, UNIQUE_ID_WASH_LAST_CHECKUP)
    assert state is not None
    assert state.state in ("unknown", "unavailable")


# ---------------------------------------------------------------------------
# _register_checkup_listener — guard branches not covered by other tests
# ---------------------------------------------------------------------------


async def test_checkup_listener_returns_early_when_dis_test_res_none(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Listener returns immediately when status.dis_test_res is None."""
    # Setup with machine having DisTestRes=0 so prev_result is seeded
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_WITH_DIS_TEST_RES_0,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Push a status with dis_test_res=None — listener should return at the guard
    no_dis_status = copy.copy(coordinator.data)
    no_dis_status.dis_test_res = None
    coordinator.async_set_updated_data(no_dis_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_checkup_listener_returns_early_when_prev_code_none(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Listener returns early on first update after initial state had no DisTestRes."""
    # _IDLE_JSON has no DisTestRes → initial_code=None → prev_result=[None]
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{CONF_KEY_CHECKUP_ENABLED: True},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Push status WITH DisTestRes=0 — prev_code is None → returns early without writing
    first_update = copy.copy(coordinator.data)
    first_update.dis_test_res = CheckUpResult.NOT_RUN
    coordinator.async_set_updated_data(first_update)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


# ---------------------------------------------------------------------------
# WashStartButton — checkup scheduling date written at request time
# ---------------------------------------------------------------------------


async def test_start_button_weekly_no_last_date_records_pending(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Weekly schedule, no prior date: pressing Start sends StartCheckUp=1 and sets pending flag, not date."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
        },
    )
    registry = er.async_get(hass)
    start_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )
    assert start_entity_id is not None

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_entity_id}, blocking=True
        )

    query_string: str = mock_send.call_args[0][0]
    assert "StartCheckUp=1" in query_string
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_start_button_weekly_recent_date_skips_checkup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Weekly schedule, last checkup 3 days ago: StartCheckUp=0 and date is unchanged."""
    three_days_ago = (datetime.now(UTC) - timedelta(days=3)).timestamp()
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: three_days_ago,
        },
    )
    registry = er.async_get(hass)
    start_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_entity_id}, blocking=True
        )

    query_string: str = mock_send.call_args[0][0]
    assert "StartCheckUp=0" in query_string
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) == three_days_ago
    assert not entry.data.get(CONF_KEY_CHECKUP_PENDING, False)


async def test_start_button_command_failure_does_not_record_checkup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Failed start command must not advance the checkup schedule clock or set pending."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
        },
    )
    registry = er.async_get(hass)
    start_entity_id = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(entry.entry_id)
    )

    with (
        patch("asyncio.sleep"),
        patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
            side_effect=Exception("connection refused"),
        ),
        contextlib.suppress(Exception),
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": start_entity_id}, blocking=True
        )

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None
    assert not entry.data.get(CONF_KEY_CHECKUP_PENDING, False)


async def test_checkup_recorded_on_cycle_completion_when_pending(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When a wash with pending checkup finishes, records timestamp and clears pending."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_PENDING: True,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Running wash
    running_status = copy.copy(coordinator.data)
    running_status.machine_state = MachineState.RUNNING
    running_status.dis_test_res = CheckUpResult.NOT_RUN
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True

    # Wash completes with OK checkup result
    finished_status = copy.copy(coordinator.data)
    finished_status.machine_state = MachineState.FINISHED1
    finished_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is not None
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT) == CheckUpResult.OK.code
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is False


async def test_checkup_delayed_wash_defers_timestamp_until_finished(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Delayed wash keeps previous timestamp through delay and running, records on finish."""
    initial_date = (datetime.now(UTC) - timedelta(days=10)).timestamp()
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: initial_date,
            CONF_KEY_CHECKUP_PENDING: True,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # State: Delayed start programmed
    delayed_status = copy.copy(coordinator.data)
    delayed_status.machine_state = MachineState.DELAYED_START_PROGRAMMED
    delayed_status.dis_test_res = CheckUpResult.NOT_RUN
    coordinator.async_set_updated_data(delayed_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) == initial_date
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True

    # State: Wash running
    running_status = copy.copy(coordinator.data)
    running_status.machine_state = MachineState.RUNNING
    running_status.dis_test_res = CheckUpResult.NOT_RUN
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) == initial_date

    # State: Wash finished
    finished_status = copy.copy(coordinator.data)
    finished_status.machine_state = MachineState.FINISHED1
    finished_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) > initial_date
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is False


async def test_checkup_ordinary_wash_does_not_reset_weekly_schedule_clock(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Ordinary wash with weekly schedule and DisTestRes=1 does not overwrite last checkup date."""
    three_days_ago = (datetime.now(UTC) - timedelta(days=3)).timestamp()
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_LAST_DATE: three_days_ago,
            CONF_KEY_CHECKUP_PENDING: False,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Ordinary wash finishes
    finished_status = copy.copy(coordinator.data)
    finished_status.machine_state = MachineState.FINISHED1
    finished_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    # Date remains 3 days ago, result is cached
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) == three_days_ago
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT) == CheckUpResult.OK.code


async def test_checkup_aborted_wash_clears_pending_without_advancing_clock(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Aborted wash (transitioning RUNNING -> IDLE without finishing) clears pending flag."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_PENDING: True,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Running wash
    running_status = copy.copy(coordinator.data)
    running_status.machine_state = MachineState.RUNNING
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True

    # User cancels/stops wash -> transitions back to IDLE
    idle_status = copy.copy(coordinator.data)
    idle_status.machine_state = MachineState.IDLE
    coordinator.async_set_updated_data(idle_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is False
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_checkup_every_cycle_records_on_completion(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Every cycle schedule records date on completion even if pending flag was not explicitly set."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_EVERY_CYCLE,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Running wash
    running_status = copy.copy(coordinator.data)
    running_status.machine_state = MachineState.RUNNING
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    # Finishes with OK
    finished_status = copy.copy(coordinator.data)
    finished_status.machine_state = MachineState.FINISHED1
    finished_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is not None
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT) == CheckUpResult.OK.code


async def test_checkup_error_state_clears_pending_without_recording(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Wash encountering an error then powered off clears pending flag without recording."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_PENDING: True,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Machine enters error state
    error_status = copy.copy(coordinator.data)
    error_status.machine_state = MachineState.ERROR
    coordinator.async_set_updated_data(error_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True

    # Machine turned off
    off_status = copy.copy(coordinator.data)
    off_status.machine_state = MachineState.OFF
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is False
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_checkup_finished_state_poll_idempotent(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Multiple coordinator updates while machine remains in FINISHED state do not re-record date."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_PENDING: True,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # First update: reaches FINISHED1
    finished_status = copy.copy(coordinator.data)
    finished_status.machine_state = MachineState.FINISHED1
    finished_status.dis_test_res = CheckUpResult.OK
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    first_recorded_date = entry.data.get(CONF_KEY_CHECKUP_LAST_DATE)
    assert first_recorded_date is not None
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is False

    # Second update: still in FINISHED1
    coordinator.async_set_updated_data(copy.copy(finished_status))
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) == first_recorded_date

    # Third update: transitions to OFF
    off_status = copy.copy(coordinator.data)
    off_status.machine_state = MachineState.OFF
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) == first_recorded_date
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is False


async def test_checkup_zero_result_finished_clears_pending_on_power_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Cycle finishing with DisTestRes=0 does not record date, and clears pending upon power off."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_PENDING: True,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Reaches FINISHED1 with NOT_RUN (0)
    finished_status = copy.copy(coordinator.data)
    finished_status.machine_state = MachineState.FINISHED1
    finished_status.dis_test_res = CheckUpResult.NOT_RUN
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    # Did not record since code == 0
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True

    # Machine powers off
    off_status = copy.copy(coordinator.data)
    off_status.machine_state = MachineState.OFF
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()

    # Pending cleared without recording
    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is False
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None


async def test_checkup_initial_idle_poll_preserves_pending(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Immediate poll after start where machine reports IDLE does not prematurely clear pending."""
    entry = await _setup(
        hass,
        aioclient_mock,
        _IDLE_JSON,
        **{
            CONF_KEY_CHECKUP_ENABLED: True,
            CONF_KEY_CHECKUP_SCHEDULE: CHECKUP_SCHEDULE_WEEKLY,
            CONF_KEY_CHECKUP_PENDING: True,
        },
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Poll still reports IDLE
    idle_status = copy.copy(coordinator.data)
    idle_status.machine_state = MachineState.IDLE
    coordinator.async_set_updated_data(idle_status)
    await hass.async_block_till_done()

    assert entry.data.get(CONF_KEY_CHECKUP_PENDING) is True
    assert entry.data.get(CONF_KEY_CHECKUP_LAST_DATE) is None
