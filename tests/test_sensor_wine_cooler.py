"""Tests for Candy Wine Cooler sensors."""

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN

from .common import TEST_IP, init_integration


async def test_main_sensor_on(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await init_integration(
        hass, aioclient_mock, load_fixture("wine_cooler/on_single_zone.json")
    )

    state = hass.states.get("sensor.wine_cooler")

    assert state
    assert state.state == "On"
    assert state.attributes == {
        "program": "Red wine",
        "target_temperature": 16,
        "light": True,
        "remote_control": True,
        "error": None,
        "friendly_name": "Wine cooler",
        "icon": "mdi:glass-wine",
    }


async def test_program_sensor(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await init_integration(
        hass, aioclient_mock, load_fixture("wine_cooler/on_single_zone.json")
    )

    state = hass.states.get("sensor.wine_cooler_program")

    assert state
    assert state.state == "Red wine"
    assert state.attributes == {
        "friendly_name": "Wine cooler Program",
        "icon": "mdi:bottle-wine",
    }


async def test_temp_sensor(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await init_integration(
        hass, aioclient_mock, load_fixture("wine_cooler/on_single_zone.json")
    )

    state = hass.states.get("sensor.wine_cooler_target_temperature")

    assert state
    assert state.state == "16"
    assert state.attributes == {
        "device_class": "temperature",
        "state_class": "measurement",
        "unit_of_measurement": "°C",
        "friendly_name": "Wine cooler Target temperature",
        "icon": "mdi:thermometer",
    }


async def test_light_sensor(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await init_integration(
        hass, aioclient_mock, load_fixture("wine_cooler/on_single_zone.json")
    )

    state = hass.states.get("sensor.wine_cooler_light")

    assert state
    assert state.state == "On"
    assert state.attributes == {
        "friendly_name": "Wine cooler Light",
        "icon": "mdi:lightbulb",
    }


async def test_error_sensor_none(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("wine_cooler/on_single_zone.json")
    )

    state = hass.states.get("sensor.wine_cooler_error_code")

    assert state
    assert state.state == "None"
    assert state.attributes == {
        "friendly_name": "Wine cooler Error code",
        "icon": "mdi:alert-circle",
    }


async def test_off_state(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await init_integration(hass, aioclient_mock, load_fixture("wine_cooler/off.json"))

    state = hass.states.get("sensor.wine_cooler")
    assert state
    assert state.state == "Off"

    light_state = hass.states.get("sensor.wine_cooler_light")
    assert light_state
    assert light_state.state == "Off"
    assert light_state.attributes["icon"] == "mdi:lightbulb-off"

    prog_state = hass.states.get("sensor.wine_cooler_program")
    assert prog_state
    assert prog_state.state == "White wine"


async def test_dual_zone(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await init_integration(
        hass, aioclient_mock, load_fixture("wine_cooler/dual_zone.json")
    )

    state = hass.states.get("sensor.wine_cooler")
    assert state
    assert state.attributes["target_temperature_zone_down"] == 12
    assert state.attributes["program_zone_down"] == "White wine"

    temp_down = hass.states.get("sensor.wine_cooler_lower_zone_target_temperature")
    assert temp_down
    assert temp_down.state == "12"
    assert temp_down.attributes["unit_of_measurement"] == "°C"

    prog_down = hass.states.get("sensor.wine_cooler_lower_zone_program")
    assert prog_down
    assert prog_down.state == "White wine"


async def test_main_sensor_device_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("wine_cooler/on_single_zone.json")
    )

    reg = entity_registry.async_get(hass)
    entity = reg.async_get("sensor.wine_cooler")
    assert entity

    dev_reg = device_registry.async_get(hass)
    device = dev_reg.async_get(entity.device_id)
    assert device
    assert device.name == "Wine cooler"
    assert device.manufacturer == "Candy"
    assert device.suggested_area == "Kitchen"


async def test_offline_startup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="123-456",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
        },
    )
    entry.add_to_hass(hass)

    reg = entity_registry.async_get(hass)
    wc_entry = reg.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}-wine_cooler",
        config_entry=entry,
    )

    # Device is unreachable at startup
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        exc=TimeoutError,
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(wc_entry.entity_id)
    assert state is not None
    assert state.state == "Off"


async def test_temp_sensor_fallback_from_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test that r4='0' falls back to program default temperature."""
    payload = '{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"0","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"0"}}'
    await init_integration(hass, aioclient_mock, payload)

    temp_state = hass.states.get("sensor.wine_cooler_target_temperature")
    assert temp_state is not None
    assert temp_state.state == "16"
