"""Unit tests for the dishwasher binary sensor platform."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.binary_sensor import (
    DishwasherAutoCleanBinarySensor,
    DishwasherDoorBinarySensor,
    DishwasherRememberLastCycleBinarySensor,
    DishwasherRemoteControlBinarySensor,
    DishwasherRinseAidEmptyBinarySensor,
    DishwasherSaltEmptyBinarySensor,
)
from custom_components.candy.const import (
    UNIQUE_ID_DISHWASHER_DOOR,
    UNIQUE_ID_DISHWASHER_MAINT_CLEAN,
    UNIQUE_ID_DISHWASHER_REMEMBER_LAST_CYCLE,
    UNIQUE_ID_DISHWASHER_REMOTE_CONTROL,
    UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY,
    UNIQUE_ID_DISHWASHER_SALT_EMPTY,
)

from .common import init_integration

_READY = "dishwasher/remote_ready.json"


def _fixture_with_overrides(name: str, **overrides: str) -> str:
    data = json.loads(load_fixture(name))
    data["statusDWash"].update(overrides)
    return json.dumps(data)


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, unique_id.format(entry.entry_id)
    )
    assert entity_id is not None
    return entity_id


async def test_dishwasher_binary_sensors_normal(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test binary sensors in normal ready state (no errors, door shut, remote on)."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))

    salt_id = _entity_id(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_SALT_EMPTY)
    rinse_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY
    )
    door_id = _entity_id(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_DOOR)
    remote_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_REMOTE_CONTROL
    )
    clean_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_MAINT_CLEAN
    )
    memo_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_REMEMBER_LAST_CYCLE
    )

    salt_state = hass.states.get(salt_id)
    rinse_state = hass.states.get(rinse_id)
    door_state = hass.states.get(door_id)
    remote_state = hass.states.get(remote_id)
    clean_state = hass.states.get(clean_id)
    memo_state = hass.states.get(memo_id)

    assert salt_state.state == "off"
    assert salt_state.attributes["device_class"] == BinarySensorDeviceClass.PROBLEM

    assert rinse_state.state == "off"
    assert rinse_state.attributes["device_class"] == BinarySensorDeviceClass.PROBLEM

    assert door_state.state == "off"
    assert door_state.attributes["device_class"] == BinarySensorDeviceClass.DOOR

    assert remote_state.state == "on"

    assert clean_state.state == "off"
    assert clean_state.attributes["device_class"] == BinarySensorDeviceClass.PROBLEM

    assert memo_state.state == "off"


async def test_dishwasher_binary_sensors_alerts(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test binary sensors when warning flags and door open are reported."""
    payload = _fixture_with_overrides(
        _READY,
        MissSalt="1",
        MissRinse="1",
        OpenDoor="1",
        StatoWiFi="0",
        r8="1",
        r9="H_CLEAN_REQUIRED",
    )
    entry = await init_integration(hass, aioclient_mock, payload)

    salt_id = _entity_id(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_SALT_EMPTY)
    rinse_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY
    )
    door_id = _entity_id(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_DOOR)
    remote_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_REMOTE_CONTROL
    )
    clean_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_MAINT_CLEAN
    )
    memo_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_REMEMBER_LAST_CYCLE
    )

    assert hass.states.get(salt_id).state == "on"
    assert hass.states.get(rinse_id).state == "on"
    assert hass.states.get(door_id).state == "on"
    assert hass.states.get(remote_id).state == "off"
    assert hass.states.get(clean_id).state == "on"
    assert hass.states.get(memo_id).state == "on"


async def test_dishwasher_binary_sensors_diagnostic_category(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify diagnostic consumable sensors have DIAGNOSTIC entity category."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    registry = er.async_get(hass)

    salt_id = _entity_id(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_SALT_EMPTY)
    rinse_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY
    )
    remote_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_REMOTE_CONTROL
    )
    clean_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_MAINT_CLEAN
    )
    memo_id = _entity_id(
        hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_REMEMBER_LAST_CYCLE
    )

    assert registry.async_get(salt_id).entity_category == EntityCategory.DIAGNOSTIC
    assert registry.async_get(rinse_id).entity_category == EntityCategory.DIAGNOSTIC
    assert registry.async_get(remote_id).entity_category == EntityCategory.DIAGNOSTIC
    assert registry.async_get(clean_id).entity_category == EntityCategory.DIAGNOSTIC
    assert registry.async_get(memo_id).entity_category == EntityCategory.DIAGNOSTIC


def test_dishwasher_binary_sensors_none_data() -> None:
    """Verify dishwasher binary sensors return None when coordinator data is None."""
    coord = MagicMock()
    coord.data = None
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_dw_none")
    sensors = [
        DishwasherSaltEmptyBinarySensor(coord, entry),
        DishwasherRinseAidEmptyBinarySensor(coord, entry),
        DishwasherDoorBinarySensor(coord, entry),
        DishwasherRemoteControlBinarySensor(coord, entry),
        DishwasherAutoCleanBinarySensor(coord, entry),
        DishwasherRememberLastCycleBinarySensor(coord, entry),
    ]
    for sensor in sensors:
        assert sensor.is_on is None
