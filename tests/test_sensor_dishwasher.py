"""Tests for various sensors."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy.client.model import DishwasherStatistics, DishwasherStatus
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_WRITE_PENDING,
    DOMAIN,
)
from custom_components.candy.sensor import (
    CandyDishwasherBuzzerSensor,
    CandyDishwasherCycleStatusSensor,
    CandyDishwasherErrorSensor,
    CandyDishwasherLifetimeCyclesSensor,
    CandyDishwasherMaintFilterSensor,
    CandyDishwasherMaintFullCheckupSensor,
    CandyDishwasherMaintLimescaleSensor,
    CandyDishwasherProgramDescriptionSensor,
    CandyDishwasherProgramSensor,
    CandyDishwasherRemainingTimeSensor,
    CandyDishwasherSensor,
    CandyDishwasherTotalCyclesSensor,
    CandyDishwasherWaterHardnessSensor,
)

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
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("dishwasher/idle.json"),
        statistics_response='{"statusCounters": {"Program1": "10"}}',
    )

    state = hass.states.get("sensor.dishwasher_program")

    assert state
    assert state.state == "Hygienic 75°C"
    assert state.attributes["raw_program"] == "P1+"
    assert "antibacterial" in state.attributes["description"].lower()
    assert state.attributes["friendly_name"] == "Dishwasher Program"
    assert state.attributes["icon"] == "mdi:glass-wine"

    desc_state = hass.states.get("sensor.dishwasher_program_description")
    assert desc_state
    assert "antibacterial" in desc_state.state.lower()
    assert desc_state.attributes["friendly_name"] == "Dishwasher Program description"
    assert desc_state.attributes["icon"] == "mdi:information-outline"


async def test_program_description_updates_on_select(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("dishwasher/idle.json"),
        statistics_response='{"statusCounters": {"Program1": "10"}}',
    )
    desc_sensor = hass.states.get("sensor.dishwasher_program_description")
    assert desc_sensor
    assert "antibacterial" in desc_sensor.state.lower()

    # Find the select entity and change it to rapid_24
    select_entity_id = None
    for state_obj in hass.states.async_all("select"):
        if "program" in state_obj.entity_id:
            select_entity_id = state_obj.entity_id
            break
    assert select_entity_id is not None

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_entity_id, "option": "rapid_24"},
        blocking=True,
    )

    desc_sensor = hass.states.get("sensor.dishwasher_program_description")
    assert desc_sensor
    assert "super fast" in desc_sensor.state.lower()


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
    assert state.attributes["delayed_start_minutes"] == 240
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


def test_dishwasher_sensors_none_data() -> None:
    """Verify dishwasher sensors safely return None/empty when coordinator.data is None."""
    coord = MagicMock()
    coord.data = None
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_dw_sensors_none")

    main_s = CandyDishwasherSensor(coord, entry)
    main_s.hass = MagicMock()
    main_s.hass.data = {DOMAIN: {entry.entry_id: {}}}
    assert main_s.native_value is None
    assert main_s.extra_state_attributes == {}

    prog_s = CandyDishwasherProgramSensor(coord, entry)
    assert prog_s.native_value is None

    desc_s = CandyDishwasherProgramDescriptionSensor(coord, entry)
    assert desc_s.native_value is None

    time_s = CandyDishwasherRemainingTimeSensor(coord, entry)
    assert time_s.native_value is None

    cycle_s = CandyDishwasherCycleStatusSensor(coord, entry)
    assert cycle_s.native_value is None

    hardness_s = CandyDishwasherWaterHardnessSensor(coord, entry)
    assert hardness_s.native_value is None

    buzzer_s = CandyDishwasherBuzzerSensor(coord, entry)
    assert buzzer_s.native_value is None


async def test_dishwasher_restore_sensors_restoration(hass: HomeAssistant) -> None:
    """Verify dishwasher restore sensors properly restore last state when coordinator data is None."""
    coord = MagicMock()
    coord.data = None
    coord.last_update_success = False
    device_coord = MagicMock()
    device_coord.data = None

    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_dw_restore")
    entry.add_to_hass(hass)

    # 1. Error sensor
    err_sensor = CandyDishwasherErrorSensor(coord, entry)
    err_sensor.hass = hass
    mock_err_data = MagicMock()
    mock_err_data.native_value = "E3"
    err_sensor.async_get_last_sensor_data = AsyncMock(return_value=mock_err_data)  # type: ignore[assignment]
    await err_sensor.async_added_to_hass()
    assert err_sensor.native_value == "E3"
    assert err_sensor.available is True

    # 2. Total cycles sensor
    total_sensor = CandyDishwasherTotalCyclesSensor(coord, entry)
    total_sensor.hass = hass
    mock_total_data = MagicMock()
    mock_total_data.native_value = 150
    total_sensor.async_get_last_sensor_data = AsyncMock(return_value=mock_total_data)  # type: ignore[assignment]
    await total_sensor.async_added_to_hass()
    assert total_sensor.native_value == 150
    assert total_sensor.available is True

    # 3. Maint full checkup sensor
    checkup_sensor = CandyDishwasherMaintFullCheckupSensor(coord, entry)
    checkup_sensor.hass = hass
    mock_checkup_data = MagicMock()
    mock_checkup_data.native_value = 35
    checkup_sensor.async_get_last_sensor_data = AsyncMock(
        return_value=mock_checkup_data
    )  # type: ignore[assignment]
    await checkup_sensor.async_added_to_hass()
    assert checkup_sensor.native_value == 35
    assert checkup_sensor.available is True

    # 4. Maint limescale sensor
    lime_sensor = CandyDishwasherMaintLimescaleSensor(coord, entry, device_coord)
    lime_sensor.hass = hass
    mock_lime_data = MagicMock()
    mock_lime_data.native_value = 40
    lime_sensor.async_get_last_sensor_data = AsyncMock(return_value=mock_lime_data)  # type: ignore[assignment]
    await lime_sensor.async_added_to_hass()
    assert lime_sensor.native_value == 40
    assert lime_sensor.available is True

    # 5. Maint filter sensor
    filter_sensor = CandyDishwasherMaintFilterSensor(coord, entry)
    filter_sensor.hass = hass
    mock_filter_data = MagicMock()
    mock_filter_data.native_value = 12
    filter_sensor.async_get_last_sensor_data = AsyncMock(return_value=mock_filter_data)  # type: ignore[assignment]
    await filter_sensor.async_added_to_hass()
    assert filter_sensor.native_value == 12
    assert filter_sensor.available is True


def test_dishwasher_maint_limescale_sensor_led_scale_and_clamped_hardness() -> None:
    """Verify limescale sensor uses LED thresholds when not smooth/digit and clamps out-of-range hardness."""
    coord = MagicMock()
    coord.data = DishwasherStatistics(total_cycles=100)
    device_coord = MagicMock()
    device_status = MagicMock(spec=DishwasherStatus)
    device_status.water_hardness = 99  # Out of range, will be clamped
    device_coord.data = device_status

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_dw_lime_led",
        data={
            CONF_KEY_INTERFACE_TYPE: "DishwasherInterfaceTypeFSLED",
            CONF_KEY_WATER_HARDNESS: 99,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 0,
        },
    )
    sensor = CandyDishwasherMaintLimescaleSensor(coord, entry, device_coord)
    # Threshold for LED at clamped index (len - 1 = 5) is 40
    # cycles_remaining(100, 0, 40) -> 0
    assert sensor.native_value == 0
