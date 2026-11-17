import json
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy.binary_sensor import (
    CandyWashDetergentEmptyBinarySensor,
    CandyWashDetergentReserveBinarySensor,
    CandyWashRemoteControlBinarySensor,
    CandyWashSoftenerEmptyBinarySensor,
    CandyWashSoftenerReserveBinarySensor,
)
from custom_components.candy.const import CONF_KEY_INTERFACE_TYPE, DOMAIN

from .common import init_integration

_REMOTE_CONTROL = "binary_sensor.remote_control"


async def test_remote_control_on_when_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get(_REMOTE_CONTROL)
    assert state is not None
    assert state.state == "on"


async def test_remote_control_off_when_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    status = load_fixture("washing_machine/idle.json").replace(
        '"WiFiStatus": "1"', '"WiFiStatus": "0"'
    )
    await init_integration(hass, aioclient_mock, status)

    state = hass.states.get(_REMOTE_CONTROL)
    assert state is not None
    assert state.state == "off"


async def test_autodose_binary_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    raw_status = load_fixture("washing_machine/idle.json")
    data = json.loads(raw_status)
    data["statusLavatrice"]["DetWarn"] = "1"
    data["statusLavatrice"]["SoftWarn"] = "0"
    data["statusLavatrice"]["DetPreW"] = "0"
    data["statusLavatrice"]["SoftPreW"] = "1"
    status_with_autodose = json.dumps(data)

    await init_integration(
        hass,
        aioclient_mock,
        status_with_autodose,
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={CONF_KEY_INTERFACE_TYPE: "red_devil_axi_ad"},
    )

    det_empty = hass.states.get("binary_sensor.washing_machine_detergent_empty")
    assert det_empty is not None
    assert det_empty.state == "on"

    soft_empty = hass.states.get("binary_sensor.washing_machine_softener_empty")
    assert soft_empty is not None
    assert soft_empty.state == "off"

    det_res = hass.states.get("binary_sensor.washing_machine_detergent_low")
    assert det_res is not None
    assert det_res.state == "off"

    soft_res = hass.states.get("binary_sensor.washing_machine_softener_low")
    assert soft_res is not None
    assert soft_res.state == "on"


async def test_autodose_binary_sensors_not_created_when_not_supported(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={CONF_KEY_INTERFACE_TYPE: "bianca"},
    )

    assert hass.states.get("binary_sensor.washing_machine_detergent_empty") is None
    assert hass.states.get("binary_sensor.washing_machine_softener_empty") is None


async def test_washing_machine_binary_sensors_null_coordinator_data() -> None:
    """Test washing machine binary sensors return None when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    config_entry = MockConfigEntry(domain=DOMAIN, entry_id="test_wm_entry", data={})

    sensors = [
        CandyWashRemoteControlBinarySensor(coordinator, config_entry),
        CandyWashDetergentEmptyBinarySensor(coordinator, config_entry),
        CandyWashSoftenerEmptyBinarySensor(coordinator, config_entry),
        CandyWashDetergentReserveBinarySensor(coordinator, config_entry),
        CandyWashSoftenerReserveBinarySensor(coordinator, config_entry),
    ]

    for sensor in sensors:
        assert sensor.is_on is None
