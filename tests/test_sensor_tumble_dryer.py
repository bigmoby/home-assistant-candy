from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy.client import TumbleDryerProgram
from custom_components.candy.const import CONF_KEY_PROGRAM_LANGUAGE, CONF_KEY_PROGRAMS
from custom_components.candy.sensor import (
    CandyTumbleDelaySensor,
    CandyTumbleErrorCodeSensor,
    CandyTumbleProgramSensor,
)

from .common import init_integration


async def test_main_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    state = hass.states.get("sensor.tumble_dryer")

    assert state
    assert state.state == "Idle"
    assert state.attributes == {
        "program": 1,
        "remaining_minutes": 150,
        "remote_control": True,
        "dry_level": 2,
        "dry_level_now": 1,
        "refresh": False,
        "need_clean_filter": False,
        "water_tank_full": False,
        "door_closed": True,
        "delay_value": 0,
        "time": 0,
        "friendly_name": "Tumble dryer",
        "icon": "mdi:tumble-dryer",
    }


async def test_program_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    state = hass.states.get("sensor.tumble_dryer_dryer_program")

    assert state
    assert state.state == "1"
    assert state.attributes == {
        "friendly_name": "Tumble dryer Dryer program",
        "icon": "mdi:tumble-dryer",
    }


async def test_main_sensor_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("tumble_dryer/running.json")
    )

    state = hass.states.get("sensor.tumble_dryer")

    assert state
    assert state.state == "Running"
    assert state.attributes == {
        "program": 1,
        "remaining_minutes": 150,
        "remote_control": True,
        "dry_level": 2,
        "dry_level_now": 1,
        "refresh": False,
        "need_clean_filter": False,
        "water_tank_full": False,
        "door_closed": True,
        "delay_value": 0,
        "time": 0,
        "friendly_name": "Tumble dryer",
        "icon": "mdi:tumble-dryer",
    }


async def test_cycle_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    state = hass.states.get("sensor.tumble_dryer_dryer_cycle_status")

    assert state
    assert state.state == "Hang Dry"
    assert state.attributes == {
        "friendly_name": "Tumble dryer Dryer cycle status",
        "icon": "mdi:tumble-dryer",
    }


async def test_cycle_sensor_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("tumble_dryer/running.json")
    )

    state = hass.states.get("sensor.tumble_dryer_dryer_cycle_status")

    assert state
    assert state.state == "Running"
    assert state.attributes == {
        "friendly_name": "Tumble dryer Dryer cycle status",
        "icon": "mdi:tumble-dryer",
    }


async def test_cycle_sensor_pre_heating(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When the dryer is in program phase 1 (pre-heating), sensors should stay available."""
    pre_heating_fixture = load_fixture("tumble_dryer/running.json").replace(
        '"PrPh": "2"', '"PrPh": "1"'
    )
    await init_integration(hass, aioclient_mock, pre_heating_fixture)

    state = hass.states.get("sensor.tumble_dryer_dryer_cycle_status")

    assert state
    assert state.state == "Pre-heating"
    assert state.attributes == {
        "friendly_name": "Tumble dryer Dryer cycle status",
        "icon": "mdi:tumble-dryer",
    }


async def test_remaining_time_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    state = hass.states.get("sensor.tumble_dryer_dryer_cycle_remaining_time")

    assert state
    assert state.state == "0"
    assert state.attributes == {
        "device_class": "duration",
        "friendly_name": "Tumble dryer Dryer cycle remaining time",
        "icon": "mdi:progress-clock",
        "unit_of_measurement": "min",
    }


async def test_remaining_time_sensor_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("tumble_dryer/running.json")
    )

    state = hass.states.get("sensor.tumble_dryer_dryer_cycle_remaining_time")

    assert state
    assert state.state == "150"
    assert state.attributes == {
        "device_class": "duration",
        "friendly_name": "Tumble dryer Dryer cycle remaining time",
        "icon": "mdi:progress-clock",
        "unit_of_measurement": "min",
    }


async def test_main_sensor_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    entity_reg = entity_registry.async_get(hass)
    device_reg = device_registry.async_get(hass)
    entry = entity_reg.async_get("sensor.tumble_dryer")
    device = device_reg.async_get(entry.device_id)

    assert device
    assert device.manufacturer == "Candy"
    assert device.name == "Tumble dryer"
    assert device.suggested_area == "Bathroom"


async def test_sensors_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    entity_reg = entity_registry.async_get(hass)
    device_reg = device_registry.async_get(hass)

    main_sensor = entity_reg.async_get("sensor.tumble_dryer")
    cycle_sensor = entity_reg.async_get("sensor.tumble_dryer_dryer_cycle_status")
    time_sensor = entity_reg.async_get("sensor.tumble_dryer_dryer_cycle_remaining_time")

    main_device = device_reg.async_get(main_sensor.device_id)
    cycle_device = device_reg.async_get(cycle_sensor.device_id)
    time_device = device_reg.async_get(time_sensor.device_id)

    assert main_device
    assert cycle_device
    assert time_device
    assert main_device == cycle_device == time_device


async def test_dry_level_and_diagnostic_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test dry level and diagnostic sensors."""
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    dry_level_state = hass.states.get("sensor.tumble_dryer_dry_level")
    assert dry_level_state
    assert dry_level_state.state == "hang_dry"

    checkup_state = hass.states.get("sensor.tumble_dryer_check_up_state")
    assert checkup_state
    assert checkup_state.state == "Idle"

    error_state = hass.states.get("sensor.tumble_dryer_dryer_error")
    assert error_state
    assert error_state.state == "0"


async def test_error_code_sensor_when_error_reported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test error code sensor when an error is present."""
    fixture = load_fixture("tumble_dryer/idle.json").replace(
        '"CodiceErrore": "0"', '"CodiceErrore": "E03"'
    )
    await init_integration(hass, aioclient_mock, fixture)

    error_state = hass.states.get("sensor.tumble_dryer_dryer_error")
    assert error_state
    assert error_state.state == "E03"
    assert error_state.attributes.get("description") == "E03 -  The water tank is full"


async def test_error_code_sensor_restored_state(hass: HomeAssistant) -> None:
    """Test error code sensor falls back to restored state when coordinator has no data."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.last_update_success = False

    entry = MockConfigEntry(domain="candy", data={})
    sensor = CandyTumbleErrorCodeSensor(coordinator, entry)
    sensor.hass = hass

    last_data = MagicMock()
    last_data.native_value = "E07"
    sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)

    await sensor.async_added_to_hass()
    assert sensor.available is True
    assert sensor.native_value == "E07"


def test_tumble_dryer_program_localization() -> None:
    """Test localized name and description lookup for dryer programs."""
    prog_whites = TumbleDryerProgram.from_dict(
        {
            "name": "NFC_TD_PROGRAM_NAME_WHITES",
            "parameters": {"selector_position": 1},
        }
    )
    assert prog_whites.localized_name("en") == "Whites"
    assert prog_whites.localized_name("it") == "Bianchi"
    assert prog_whites.localized_description("en") is not None
    assert prog_whites.localized_description("it") is not None

    prog_mix = TumbleDryerProgram.from_dict(
        {
            "name": "NFC_TD_PROGRAM_NAME_MIX_AND_DRY",
            "parameters": {"selector_position": 2},
        }
    )
    assert prog_mix.localized_name("en") == "Mix&Dry"
    assert prog_mix.localized_name("it") == "Mix&Dry"

    prog_dl = TumbleDryerProgram.from_dict(
        {
            "name": "DUAL_TD_PROGRAM_DOWNLOAD_DRY_EASY_IRON_SYNTHETICS",
            "parameters": {"selector_position": 10},
        }
    )
    assert prog_dl.localized_name("en") == "Easy Iron Sintetics"
    assert prog_dl.localized_name("it") == "Stiro Facile - Sintetici"


def test_candy_tumble_delay_sensor_none_data() -> None:
    """Test tumble delay sensor returns None when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    config_entry.data = {}
    sensor = CandyTumbleDelaySensor(coordinator, config_entry)
    assert sensor.native_value is None


async def test_program_sensor_with_catalog_programs(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test dryer program sensor returns program number as state and program_name as attribute."""
    programs_data = [
        {
            "position": 1,
            "name": "NFC_TD_PROGRAM_NAME_WHITES",
            "parameters": {"selector_position": 1},
        },
        {
            "position": 2,
            "name": "NFC_TD_PROGRAM_NAME_MIX_AND_DRY",
            "parameters": {"selector_position": 2},
        },
    ]
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("tumble_dryer/idle.json"),
        extra_config_data={
            CONF_KEY_PROGRAMS: programs_data,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )

    state = hass.states.get("sensor.tumble_dryer_dryer_program")
    assert state
    assert state.state == "1"
    assert state.attributes.get("program_name") == "Whites"


def test_candy_tumble_program_sensor_none_data() -> None:
    """Test tumble program sensor returns None and empty attributes when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    config_entry.data = {}
    sensor = CandyTumbleProgramSensor(coordinator, config_entry, [])
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}
