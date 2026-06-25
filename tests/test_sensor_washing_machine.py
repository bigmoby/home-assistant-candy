"""Tests for various sensors."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from pytest_homeassistant_custom_component.common import load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .common import init_integration


async def test_main_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("sensor.washing_machine")

    assert state
    assert state.state == "Idle"
    assert state.attributes == {
        "program": 1,
        "program_code": 136,
        "temperature": 40,
        "spin_speed": 800,
        "remaining_minutes": 0,
        "remote_control": True,
        "fill_percent": 0,
        "friendly_name": "Washing machine",
        "icon": "mdi:washing-machine",
    }


async def test_program_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("sensor.wash_program")

    assert state
    assert state.state == "1"
    assert state.attributes == {
        "program_code": 136,
        "friendly_name": "Wash program",
        "icon": "mdi:washing-machine",
    }


async def test_cycle_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("sensor.wash_cycle_status")

    assert state
    assert state.state == "Stopped"
    assert state.attributes == {
        "friendly_name": "Wash cycle status",
        "icon": "mdi:washing-machine",
    }


async def test_remaining_time_sensor_wash(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/running_wash.json")
    )

    state = hass.states.get("sensor.wash_cycle_remaining_time")

    assert state
    assert state.state == "8"
    assert state.attributes == {
        "friendly_name": "Wash cycle remaining time",
        "icon": "mdi:progress-clock",
        "unit_of_measurement": "min",
    }


async def test_remaining_time_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("sensor.wash_cycle_remaining_time")

    assert state
    assert state.state == "0"
    assert state.attributes == {
        "friendly_name": "Wash cycle remaining time",
        "icon": "mdi:progress-clock",
        "unit_of_measurement": "min",
    }


async def test_main_sensor_no_fillr(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/no_fillr.json")
    )

    state = hass.states.get("sensor.washing_machine")

    assert state
    assert state.state == "Idle"
    assert state.attributes == {
        "program": 4,
        "temperature": 40,
        "spin_speed": 1000,
        "remaining_minutes": 0,
        "remote_control": False,
        "friendly_name": "Washing machine",
        "icon": "mdi:washing-machine",
    }


async def test_main_sensor_no_pr(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/no_pr.json")
    )

    state = hass.states.get("sensor.washing_machine")

    assert state
    assert state.state == "Running"
    assert state.attributes == {
        "program": 6,
        "program_code": 3,
        "temperature": 40,
        "spin_speed": 1000,
        "remaining_minutes": 46,
        "remote_control": True,
        "fill_percent": 53,
        "friendly_name": "Washing machine",
        "icon": "mdi:washing-machine",
    }


async def test_main_sensor_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    entity_reg = entity_registry.async_get(hass)
    device_reg = device_registry.async_get(hass)
    entry = entity_reg.async_get("sensor.washing_machine")
    device = device_reg.async_get(entry.device_id)

    assert device
    assert device.manufacturer == "Candy"
    assert device.name == "Washing machine"
    assert device.suggested_area == "Bathroom"


async def test_sensors_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    entity_reg = entity_registry.async_get(hass)
    device_reg = device_registry.async_get(hass)

    main_sensor = entity_reg.async_get("sensor.washing_machine")
    cycle_sensor = entity_reg.async_get("sensor.wash_cycle_status")
    time_sensor = entity_reg.async_get("sensor.wash_cycle_remaining_time")

    main_device = device_reg.async_get(main_sensor.device_id)
    cycle_device = device_reg.async_get(cycle_sensor.device_id)
    time_device = device_reg.async_get(time_sensor.device_id)

    assert main_device
    assert cycle_device
    assert time_device
    assert main_device == cycle_device == time_device


async def test_main_sensor_off_after_finished(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When the device was Finished and then becomes unreachable, sensor should show Off."""
    # Load a fixture where the washing machine has finished
    finished_fixture = load_fixture("washing_machine/idle.json").replace(
        '"MachMd": "1"',
        '"MachMd": "7"',  # Override to FINISHED1 state
    )
    await init_integration(hass, aioclient_mock, finished_fixture)

    # Verify initial state is Finished
    state = hass.states.get("sensor.washing_machine")
    assert state
    assert state.state == "Finished"

    # Now simulate device going offline (TimeoutError on next poll)
    # aioclient_mock doesn't support per-call side effects easily, so we patch the client method
    from custom_components.candy.const import DATA_KEY_COORDINATOR, DOMAIN

    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert config_entries
    entry_id = config_entries[0].entry_id
    coordinator = hass.data[DOMAIN][entry_id][DATA_KEY_COORDINATOR]

    with patch(
        "custom_components.candy.client.CandyClient.status_with_retry",
        side_effect=TimeoutError,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("sensor.washing_machine")
    assert state
    assert state.state == "Off"
