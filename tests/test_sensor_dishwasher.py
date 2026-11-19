"""Tests for various sensors."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from pytest_homeassistant_custom_component.common import load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy.const import DATA_KEY_WRITE_PENDING, DOMAIN
from custom_components.candy.sensor import CandyDishwasherLifetimeCyclesSensor

from .common import init_integration


async def test_main_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("dishwasher/idle.json"))

    state = hass.states.get("sensor.dishwasher")

    assert state
    assert state.state == "Idle"
    assert state.attributes == {
        "program": "P1+",
        "remaining_minutes": 0,
        "eco_mode": False,
        "door_open": False,
        "remote_control": True,
        "salt_empty": False,
        "rinse_aid_empty": False,
        "friendly_name": "Dishwasher",
        "icon": "mdi:glass-wine",
    }


async def test_program_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("dishwasher/idle.json"))

    state = hass.states.get("sensor.dishwasher_program")

    assert state
    assert state.state == "P1+"
    assert state.attributes == {
        "friendly_name": "Dishwasher Program",
        "icon": "mdi:glass-wine",
    }


async def test_main_sensor_wash(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("dishwasher/wash.json"))

    state = hass.states.get("sensor.dishwasher")

    assert state
    assert state.state == "Running"
    assert state.attributes["program"] == "P2-"
    assert state.attributes["remaining_minutes"] == 68
    assert state.attributes["eco_mode"] is True
    assert state.attributes["door_open"] is False
    assert state.attributes["remote_control"] is False
    assert state.attributes["salt_empty"] is True
    assert state.attributes["rinse_aid_empty"] is True

    phase_state = hass.states.get("sensor.dishwasher_cycle_status")
    assert phase_state
    assert phase_state.state == "Wash"


async def test_main_sensor_wash_no_opzprog(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("dishwasher/wash_no_opzprog.json")
    )

    state = hass.states.get("sensor.dishwasher")

    assert state
    assert state.state == "Running"
    assert state.attributes["program"] == "P2"
    assert state.attributes["remaining_minutes"] == 68
    assert state.attributes["eco_mode"] is True
    assert state.attributes["door_open"] is False
    assert state.attributes["remote_control"] is False
    assert state.attributes["salt_empty"] is False
    assert state.attributes["rinse_aid_empty"] is False

    phase_state = hass.states.get("sensor.dishwasher_cycle_status")
    assert phase_state
    assert phase_state.state == "Wash"


async def test_main_sensor_drying_optional_params(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("dishwasher/drying_optional_params.json")
    )

    state = hass.states.get("sensor.dishwasher")

    assert state
    assert state.state == "Running"
    assert state.attributes["program"] == "P2"
    assert state.attributes["remaining_minutes"] == 58
    assert state.attributes["delayed_start_hours"] == 4
    assert state.attributes["eco_mode"] is True
    assert state.attributes["door_open"] is False
    assert state.attributes["door_open_allowed"] is True
    assert state.attributes["remote_control"] is True
    assert state.attributes["salt_empty"] is False
    assert state.attributes["rinse_aid_empty"] is True

    phase_state = hass.states.get("sensor.dishwasher_cycle_status")
    assert phase_state
    assert phase_state.state == "Drying"


async def test_remaining_time_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("dishwasher/idle.json"))

    state = hass.states.get("sensor.dishwasher_remaining_time")

    assert state
    assert state.state == "0"
    assert state.attributes == {
        "device_class": "duration",
        "friendly_name": "Dishwasher Remaining time",
        "icon": "mdi:progress-clock",
        "unit_of_measurement": "min",
    }


async def test_remaining_time_sensor_wash(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("dishwasher/wash.json"))

    state = hass.states.get("sensor.dishwasher_remaining_time")

    assert state
    assert state.state == "68"
    assert state.attributes == {
        "device_class": "duration",
        "friendly_name": "Dishwasher Remaining time",
        "icon": "mdi:progress-clock",
        "unit_of_measurement": "min",
    }


async def test_main_sensor_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("dishwasher/idle.json"))

    entity_reg = entity_registry.async_get(hass)
    device_reg = device_registry.async_get(hass)
    entry = entity_reg.async_get("sensor.dishwasher")
    device = device_reg.async_get(entry.device_id)

    assert device
    assert device.manufacturer == "Candy"
    assert device.name == "Dishwasher"
    assert device.suggested_area == "Kitchen"


async def test_sensors_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(hass, aioclient_mock, load_fixture("dishwasher/idle.json"))

    entity_reg = entity_registry.async_get(hass)
    device_reg = device_registry.async_get(hass)

    main_sensor = entity_reg.async_get("sensor.dishwasher")
    time_sensor = entity_reg.async_get("sensor.dishwasher_remaining_time")

    main_device = device_reg.async_get(main_sensor.device_id)
    time_device = device_reg.async_get(time_sensor.device_id)

    assert main_device
    assert time_device
    assert main_device == time_device


async def test_dishwasher_hardware_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    fixture_data = load_fixture("dishwasher/idle.json").replace(
        '"statusDWash": {',
        '"statusDWash": {"r6": "3", "r7": "4", "r8": "150", ',
    )
    await init_integration(hass, aioclient_mock, fixture_data)

    buzzer = hass.states.get("sensor.dishwasher_buzzer_volume")
    hardness = hass.states.get("sensor.dishwasher_water_hardness")
    cycles = hass.states.get("sensor.dishwasher_completed_cycles")

    assert buzzer
    assert buzzer.state == "3"
    assert hardness
    assert hardness.state == "4"
    assert cycles
    assert cycles.state == "150"


async def test_dishwasher_main_sensor_write_pending(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify main dishwasher sensor shows 'Sending command' when write is pending."""
    entry = await init_integration(
        hass, aioclient_mock, load_fixture("dishwasher/idle.json")
    )
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    hass.data[DOMAIN][entry.entry_id][DATA_KEY_WRITE_PENDING] = 1
    coordinator.async_update_listeners()

    state = hass.states.get("sensor.dishwasher")
    assert state
    assert state.state == "Sending command"


async def test_dishwasher_lifetime_cycles_restoration(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify lifetime cycles sensor uses restored state when coordinator has None."""
    entry = await init_integration(
        hass, aioclient_mock, load_fixture("dishwasher/idle.json")
    )
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    sensor = CandyDishwasherLifetimeCyclesSensor(coordinator, entry)
    sensor.hass = hass
    sensor.entity_id = "sensor.dishwasher_completed_cycles"

    # Simulate get_last_sensor_data returning restored 240 cycles
    last_data = MagicMock()
    last_data.native_value = 240
    sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)  # type: ignore[assignment]
    await sensor.async_added_to_hass()

    coordinator.data.last_cycle_counter = None
    assert sensor.native_value == 240
    assert sensor.available is True
