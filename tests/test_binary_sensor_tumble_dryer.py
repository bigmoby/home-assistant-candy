"""Tests for tumble dryer binary sensors."""

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy.binary_sensor import (
    CandyTumbleCleanFilterBinarySensor,
    CandyTumbleDoorBinarySensor,
    CandyTumbleRemoteControlBinarySensor,
    CandyTumbleWaterTankBinarySensor,
)
from custom_components.candy.const import DOMAIN

from .common import init_integration


async def test_tumble_dryer_binary_sensors_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test tumble dryer binary sensors in idle normal state."""
    await init_integration(hass, aioclient_mock, load_fixture("tumble_dryer/idle.json"))

    remote_state = hass.states.get("binary_sensor.tumble_dryer_remote_control")
    assert remote_state
    assert remote_state.state == "on"

    door_state = hass.states.get("binary_sensor.tumble_dryer_door")
    assert door_state
    # DoorState: 1 (closed) -> binary sensor door is off (not open)
    assert door_state.state == "off"
    assert door_state.attributes.get("device_class") == "door"

    filter_state = hass.states.get("binary_sensor.tumble_dryer_clean_filter")
    assert filter_state
    assert filter_state.state == "off"
    assert filter_state.attributes.get("device_class") == "problem"

    tank_state = hass.states.get("binary_sensor.tumble_dryer_water_tank_full")
    assert tank_state
    assert tank_state.state == "off"
    assert tank_state.attributes.get("device_class") == "problem"


async def test_tumble_dryer_binary_sensors_problem_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test tumble dryer binary sensors when door is open and filters/tank need service."""
    fixture = (
        load_fixture("tumble_dryer/idle.json")
        .replace('"DoorState": "1"', '"DoorState": "0"')
        .replace('"CleanFilter": "0"', '"CleanFilter": "1"')
        .replace('"WaterTankFull": "0"', '"WaterTankFull": "1"')
        .replace('"StatoWiFi": "1"', '"StatoWiFi": "0"')
    )
    await init_integration(hass, aioclient_mock, fixture)

    remote_state = hass.states.get("binary_sensor.tumble_dryer_remote_control")
    assert remote_state
    assert remote_state.state == "off"

    door_state = hass.states.get("binary_sensor.tumble_dryer_door")
    assert door_state
    # DoorState: 0 (open) -> binary sensor door is on
    assert door_state.state == "on"

    filter_state = hass.states.get("binary_sensor.tumble_dryer_clean_filter")
    assert filter_state
    assert filter_state.state == "on"

    tank_state = hass.states.get("binary_sensor.tumble_dryer_water_tank_full")
    assert tank_state
    assert tank_state.state == "on"


async def test_tumble_dryer_binary_sensors_null_coordinator_data() -> None:
    """Test tumble dryer binary sensors return None when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id="test_dryer_entry", data={})

    sensors = [
        CandyTumbleRemoteControlBinarySensor(coordinator, config_entry),
        CandyTumbleDoorBinarySensor(coordinator, config_entry),
        CandyTumbleCleanFilterBinarySensor(coordinator, config_entry),
        CandyTumbleWaterTankBinarySensor(coordinator, config_entry),
    ]

    for sensor in sensors:
        assert sensor.is_on is None
