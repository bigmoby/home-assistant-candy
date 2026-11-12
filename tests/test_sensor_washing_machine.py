import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.sensor import SensorDeviceClass, SensorExtraStoredData
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import (
    device_registry,
    device_registry as dr,
    entity_registry,
    entity_registry as er,
)
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    load_fixture,
    mock_restore_cache_with_extra_data,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import (
    CONF_KEY_USE_ENCRYPTION,
    SCAN_INTERVAL_ACTIVE,
    SCAN_INTERVAL_RESTING,
)
from custom_components.candy.client.model import DownloadableProgram, MachineState
from custom_components.candy.const import (
    CONF_KEY_BRAND,
    CONF_KEY_CHECKUP_LAST_RESULT,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_IS_WASHING_MACHINE,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_PURCHASE_DATE,
    CONF_KEY_SERIAL_NUMBER,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
    MODE_FULL_CONTROL,
    UNIQUE_ID_WASH_DETERGENT_CYCLES,
    UNIQUE_ID_WASH_LIQUID_DETERGENT,
    UNIQUE_ID_WASH_POWDER_DETERGENT,
    UNIQUE_ID_WASH_PURCHASE_DATE,
    UNIQUE_ID_WASH_SOFTENER_CYCLES,
    UNIQUE_ID_WASHING_MACHINE,
)
from custom_components.candy.sensor import (
    CandyBaseSensor,
    CandyWashCheckUpResultSensor,
    CandyWashDetergentCyclesSensor,
    CandyWashDryTargetSensor,
    CandyWashErrorSensor,
    CandyWashingMachineSensor,
    CandyWashMaintFilterSensor,
    CandyWashMaintFullCheckupSensor,
    CandyWashMaintLimescaleSensor,
    CandyWashPurchaseDateSensor,
    CandyWashScheduledFinishSensor,
    CandyWashScheduledStartSensor,
    CandyWashSoftenerCyclesSensor,
    async_setup_entry,
)

from .common import TEST_IP, init_integration


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


_TEST_PROGRAMS = [
    {
        "program": {
            "position": 1,
            "name": "DUAL_WM_WD_PROGRAM_NAME_SPECIAL_39",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "1"}},
                {"command_parameter": {"name": "pr_code", "validation": "136"}},
            ],
        }
    },
    {
        "program": {
            "position": 8,
            "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_30_MIN",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "7"}},
                {"command_parameter": {"name": "pr_code", "validation": "71"}},
            ],
        }
    },
]

_TEST_NFC_NEW_CLOTHES = DownloadableProgram(
    position=33,
    name="DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_NEW_CLOTHES",
    parent=6,
    temperature=20,
    spin_speed=1000,
    soil_level=2,
    options=0,
    steam=0,
    translations={"en": "New Clothes"},
    category_translations={"en": "Special"},
    description_translations={"en": "Wash new clothes."},
)


async def test_program_sensor_standard_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test wash program sensor displaying standard program name when RecipeId is 0."""
    status_payload = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "7"')
        .replace('"PrCode": "136"', '"PrCode": "71"')
        .replace('"RecipeId": "0"', '"RecipeId": "0"')
    )
    with patch(
        "custom_components.candy.sensor.load_downloadable_programs",
        return_value=[_TEST_NFC_NEW_CLOTHES],
    ):
        await init_integration(
            hass,
            aioclient_mock,
            status_payload,
            statistics_response='{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}',
            extra_config_data={
                CONF_KEY_PROGRAMS: _TEST_PROGRAMS,
                CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            },
        )

    state = hass.states.get("sensor.wash_program")
    assert state
    assert state.state == "Rapid 30 Min."
    assert state.attributes.get("recipe_id") is None


async def test_program_sensor_special_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test wash program sensor displaying downloadable program name when RecipeId is D_33."""
    status_payload = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "7"')
        .replace('"PrCode": "136"', '"PrCode": "71"')
        .replace('"RecipeId": "0"', '"RecipeId": "D_33"')
    )
    with patch(
        "custom_components.candy.sensor.load_downloadable_programs",
        return_value=[_TEST_NFC_NEW_CLOTHES],
    ):
        await init_integration(
            hass,
            aioclient_mock,
            status_payload,
            statistics_response='{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}',
            extra_config_data={
                CONF_KEY_PROGRAMS: _TEST_PROGRAMS,
                CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            },
        )

    state = hass.states.get("sensor.wash_program")
    assert state
    assert state.state == "New Clothes"
    assert state.attributes["recipe_id"] == "D_33"


async def test_program_sensor_special_program_numeric_recipe_id(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test wash program sensor matching downloadable program with numeric string RecipeId."""
    status_payload = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "7"')
        .replace('"PrCode": "136"', '"PrCode": "71"')
        .replace('"RecipeId": "0"', '"RecipeId": "33"')
    )
    with patch(
        "custom_components.candy.sensor.load_downloadable_programs",
        return_value=[_TEST_NFC_NEW_CLOTHES],
    ):
        await init_integration(
            hass,
            aioclient_mock,
            status_payload,
            statistics_response='{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}',
            extra_config_data={
                CONF_KEY_PROGRAMS: _TEST_PROGRAMS,
                CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            },
        )

    state = hass.states.get("sensor.wash_program")
    assert state
    assert state.state == "New Clothes"
    assert state.attributes["recipe_id"] == "33"


async def test_program_sensor_special_program_unknown_recipe_id_fallback(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test fallback to standard base program when RecipeId is not in downloadable catalog."""
    status_payload = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "7"')
        .replace('"PrCode": "136"', '"PrCode": "71"')
        .replace('"RecipeId": "0"', '"RecipeId": "D_999"')
    )
    with patch(
        "custom_components.candy.sensor.load_downloadable_programs",
        return_value=[_TEST_NFC_NEW_CLOTHES],
    ):
        await init_integration(
            hass,
            aioclient_mock,
            status_payload,
            statistics_response='{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}',
            extra_config_data={
                CONF_KEY_PROGRAMS: _TEST_PROGRAMS,
                CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            },
        )

    state = hass.states.get("sensor.wash_program")
    assert state
    assert state.state == "Rapid 30 Min."
    assert state.attributes["recipe_id"] == "D_999"


async def test_program_sensor_legacy_downloadable_position_match(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test displaying downloadable program name when matched by dial position with RecipeId 0."""
    status_payload = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "33"')
        .replace('"RecipeId": "0"', '"RecipeId": "0"')
    )
    with patch(
        "custom_components.candy.sensor.load_downloadable_programs",
        return_value=[_TEST_NFC_NEW_CLOTHES],
    ):
        await init_integration(
            hass,
            aioclient_mock,
            status_payload,
            statistics_response='{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}',
            extra_config_data={
                CONF_KEY_PROGRAMS: _TEST_PROGRAMS,
                CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            },
        )

    state = hass.states.get("sensor.wash_program")
    assert state
    assert state.state == "New Clothes"


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
        "device_class": "duration",
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
        "device_class": "duration",
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


async def test_total_cycles_sensor(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
    )

    state = hass.states.get("sensor.total_wash_cycles")

    assert state
    assert state.state == "388"
    assert state.attributes == {
        "friendly_name": "Total wash cycles",
        "icon": "mdi:counter",
        "state_class": "total_increasing",
    }


async def test_total_cycles_sensor_absent_without_statistics(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("sensor.total_wash_cycles")

    assert state is None


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
    config_entries = hass.config_entries.async_entries(DOMAIN)
    assert config_entries
    entry_id = config_entries[0].entry_id
    coordinator = hass.data[DOMAIN][entry_id][DATA_KEY_COORDINATOR]

    with patch(
        "custom_components.candy.client.CandyClient.status",
        side_effect=TimeoutError,
    ):
        for _ in range(3):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    state = hass.states.get("sensor.washing_machine")
    assert state
    assert state.state == "Off"


async def test_total_cycles_shows_cached_value_after_offline_startup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Total cycles sensor should show last known value when stats fetch fails at startup."""
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

    # Pre-register the total cycles entity so the integration knows it existed before.
    # Capture the returned entry to get the actual entity_id assigned by HA.
    registry = entity_registry.async_get(hass)
    cycles_entry = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}-wash_total_cycles",
        config_entry=entry,
    )

    # Seed the RestoreSensor cache using the actual entity_id HA assigned
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(cycles_entry.entity_id, "40"),
                SensorExtraStoredData(
                    native_value=40, native_unit_of_measurement=None
                ).as_dict(),
            )
        ],
    )

    # Device status is reachable, but statistics endpoint is not registered (offline)
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=load_fixture("washing_machine/idle.json"),
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(cycles_entry.entity_id)
    assert state is not None
    assert state.state == "40"


async def test_soil_level_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("sensor.wash_stain_level")

    assert state
    assert state.state == "unknown"  # SLevel=0 has no label
    assert state.attributes == {
        "friendly_name": "Wash stain level",
        "icon": "mdi:water-opacity",
        "options": ["low", "normal", "high"],
        "device_class": "enum",
    }


async def test_soil_level_sensor_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/running_wash.json")
    )

    state = hass.states.get("sensor.wash_stain_level")

    assert state
    assert state.state == "normal"  # SLevel=2


async def test_statistics_not_fetched_when_machine_is_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Stats coordinator must not call the device when machine_state is OFF."""
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
    )

    config_entries = hass.config_entries.async_entries(DOMAIN)
    entry_id = config_entries[0].entry_id
    coordinator = hass.data[DOMAIN][entry_id][DATA_KEY_COORDINATOR]
    stats_coordinator = hass.data[DOMAIN][entry_id][DATA_KEY_STATS_COORDINATOR]

    # Simulate device going offline — coordinator now holds MachineState.OFF
    with patch(
        "custom_components.candy.client.CandyClient.status",
        side_effect=TimeoutError,
    ):
        for _ in range(3):
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    # Now trigger a stats poll; network must NOT be called
    with patch(
        "custom_components.candy.client.CandyClient.fetch_statistics",
        side_effect=AssertionError(
            "fetch_statistics must not be called when machine is off"
        ),
    ):
        await stats_coordinator.async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("sensor.total_wash_cycles")
    assert state is not None
    assert state.state.isdigit()


# ---------------------------------------------------------------------------
# Maintenance counter sensor tests
# ---------------------------------------------------------------------------

_MAINTENANCE_CONFIG = {
    CONF_KEY_IS_WASHING_MACHINE: True,
    CONF_KEY_MAINTENANCE_ENABLED: True,
    CONF_KEY_WATER_HARDNESS: 2,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 348,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 348,
    CONF_KEY_MAINTENANCE_LAST_FILTER: 348,
}


async def test_maintenance_sensors_absent_when_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data={
            CONF_KEY_IS_WASHING_MACHINE: True,
            CONF_KEY_MAINTENANCE_ENABLED: False,
        },
    )

    assert (
        hass.states.get("sensor.washing_machine_check_up_maintenance_remaining_cycles")
        is None
    )
    assert (
        hass.states.get("sensor.washing_machine_limescale_maintenance_remaining_cycles")
        is None
    )
    assert (
        hass.states.get("sensor.washing_machine_filter_maintenance_remaining_cycles")
        is None
    )


async def test_maintenance_sensors_absent_without_statistics(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        extra_config_data=_MAINTENANCE_CONFIG,
    )

    assert (
        hass.states.get("sensor.washing_machine_check_up_maintenance_remaining_cycles")
        is None
    )
    assert (
        hass.states.get("sensor.washing_machine_limescale_maintenance_remaining_cycles")
        is None
    )
    assert (
        hass.states.get("sensor.washing_machine_filter_maintenance_remaining_cycles")
        is None
    )


async def test_full_checkup_sensor(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """total_cycles=388, last_full_checkup=348, threshold=100 → 60 cycles remaining."""
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data=_MAINTENANCE_CONFIG,
    )

    state = hass.states.get(
        "sensor.washing_machine_check_up_maintenance_remaining_cycles"
    )
    assert state
    assert state.state == "60"
    assert state.attributes["icon"] == "mdi:washing-machine"


async def test_limescale_sensor_medium_hardness(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """total_cycles=388, last_limescale=348, hardness=2 (threshold=100) → 60 remaining."""
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data=_MAINTENANCE_CONFIG,
    )

    state = hass.states.get(
        "sensor.washing_machine_limescale_maintenance_remaining_cycles"
    )
    assert state
    assert state.state == "60"
    assert state.attributes["icon"] == "mdi:water-alert"


async def test_limescale_sensor_very_hard_water(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """total_cycles=388, last_limescale=348, hardness=5 (threshold=85) → 45 remaining."""
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_WATER_HARDNESS] = 5

    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data=config,
    )

    state = hass.states.get(
        "sensor.washing_machine_limescale_maintenance_remaining_cycles"
    )
    assert state
    assert state.state == "45"


async def test_filter_sensor(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    """total_cycles=388, last_filter=348, threshold=100 → 60 remaining."""
    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data=_MAINTENANCE_CONFIG,
    )

    state = hass.states.get(
        "sensor.washing_machine_filter_maintenance_remaining_cycles"
    )
    assert state
    assert state.state == "60"
    assert state.attributes["icon"] == "mdi:filter-check"


async def test_maintenance_sensor_shows_zero_when_due(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When elapsed == threshold (multiple), sensor shows 0 (due now)."""
    # total_cycles=388, threshold=100; last_full_checkup=288 → elapsed=100 → due
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = 288

    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data=config,
    )

    state = hass.states.get(
        "sensor.washing_machine_check_up_maintenance_remaining_cycles"
    )
    assert state
    assert state.state == "0"


async def test_maintenance_sensor_full_threshold_when_just_reset(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """When last_reset == total_cycles (just reset), sensor shows the full threshold."""
    # total_cycles=388, last_selfclean=388 → elapsed=0 → full threshold=100
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = 388

    await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data=config,
    )

    state = hass.states.get(
        "sensor.washing_machine_check_up_maintenance_remaining_cycles"
    )
    assert state
    assert state.state == "100"


# ---------------------------------------------------------------------------
# Detergent sensor gating: present only when catalog data contains dose values
# ---------------------------------------------------------------------------

_PROGRAM_NO_DOSE = [
    {
        "program": {
            "position": 7,
            "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_14_MIN",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "7",
                    }
                },
                {
                    "command_parameter": {
                        "name": "pr_code",
                        "validation": "39",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_temperature",
                        "validation": "30",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_temperature",
                        "validation": "30",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_spin_speed",
                        "validation": "1200",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_spin_speed",
                        "validation": "800",
                    }
                },
                {
                    "command_parameter": {
                        "name": "minimum_soil_level",
                        "validation": "1",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_soil_level",
                        "validation": "1",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_soil_level",
                        "validation": "1",
                    }
                },
            ],
        }
    }
]

_PROGRAM_WITH_DOSE = [
    {
        "program": {
            "position": 16,
            "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "14",
                    }
                },
                {
                    "command_parameter": {
                        "name": "pr_code",
                        "validation": "65",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_temperature",
                        "validation": "90",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_temperature",
                        "validation": "60",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_spin_speed",
                        "validation": "1200",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_spin_speed",
                        "validation": "1200",
                    }
                },
                {
                    "command_parameter": {
                        "name": "minimum_soil_level",
                        "validation": "1",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_soil_level",
                        "validation": "3",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_soil_level",
                        "validation": "3",
                    }
                },
                {
                    "command_parameter": {
                        "name": "liquid_detergent_dose",
                        "validation": "4",
                    }
                },
                {
                    "command_parameter": {
                        "name": "powder_detergent_dose",
                        "validation": "4",
                    }
                },
            ],
        }
    }
]


def _detergent_entity_id(
    hass: HomeAssistant, entry_id: str, uid_tpl: str
) -> str | None:
    reg = entity_registry.async_get(hass)
    return reg.async_get_entity_id("sensor", DOMAIN, uid_tpl.format(entry_id))


async def test_detergent_sensors_absent_without_dose_data(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Detergent sensors must not be registered when no program has dose values."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data={CONF_KEY_PROGRAMS: _PROGRAM_NO_DOSE},
    )
    assert (
        _detergent_entity_id(hass, entry.entry_id, UNIQUE_ID_WASH_LIQUID_DETERGENT)
        is None
    )
    assert (
        _detergent_entity_id(hass, entry.entry_id, UNIQUE_ID_WASH_POWDER_DETERGENT)
        is None
    )


async def test_detergent_sensors_present_with_dose_data(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Detergent sensors must be registered when catalog data includes dose values."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response=load_fixture("washing_machine/statistics.json"),
        extra_config_data={CONF_KEY_PROGRAMS: _PROGRAM_WITH_DOSE},
    )
    assert (
        _detergent_entity_id(hass, entry.entry_id, UNIQUE_ID_WASH_LIQUID_DETERGENT)
        is not None
    )
    assert (
        _detergent_entity_id(hass, entry.entry_id, UNIQUE_ID_WASH_POWDER_DETERGENT)
        is not None
    )


# ---------------------------------------------------------------------------
# Adaptive polling interval tests
# ---------------------------------------------------------------------------


async def test_poll_interval_active_when_reachable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Coordinator uses 60 s interval after a successful poll."""
    entry = await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    assert coordinator.update_interval == SCAN_INTERVAL_ACTIVE


async def test_poll_interval_resting_when_unreachable(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Coordinator switches to 20 s interval when device becomes unreachable."""
    entry = await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with patch(
        "custom_components.candy.client.CandyClient.status",
        side_effect=TimeoutError,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert coordinator.update_interval == SCAN_INTERVAL_RESTING


async def test_poll_interval_restores_active_on_recovery(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Coordinator returns to 60 s interval once the device responds again."""
    entry = await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    with patch(
        "custom_components.candy.client.CandyClient.status",
        side_effect=TimeoutError,
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert coordinator.update_interval == SCAN_INTERVAL_RESTING

    # Device comes back online — aioclient_mock URL is still registered from init
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.update_interval == SCAN_INTERVAL_ACTIVE


async def test_washer_dryer_sensor_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test washer dryer entities, naming, manufacturer, and dry target sensor."""
    fixture = load_fixture("washing_machine/idle.json").replace(
        '"DryT": "0"', '"DryT": "1"'
    )
    entry = await init_integration(
        hass,
        aioclient_mock,
        fixture,
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={
            CONF_KEY_IS_WASHER_DRYER: True,
            CONF_KEY_BRAND: "hoover",
        },
    )

    dev_reg = device_registry.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Washer dryer"
    assert device.manufacturer == "Hoover"

    main_state = hass.states.get("sensor.washer_dryer")
    assert main_state is not None
    assert main_state.state == "Idle"
    assert main_state.attributes["friendly_name"] == "Washer dryer"

    dry_target_state = hass.states.get(
        "sensor.washer_dryer_dry_target"
    ) or hass.states.get("sensor.dry_target")
    assert dry_target_state is not None
    assert dry_target_state.state == "extra_dry"
    assert dry_target_state.attributes["friendly_name"] == "Washer dryer Dry target"


async def test_washer_dryer_sensor_wool_dry_target(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test washer dryer dry target sensor reports wool_dry when DryT is 9."""
    fixture = load_fixture("washing_machine/idle.json").replace(
        '"DryT": "0"', '"DryT": "9"'
    )
    await init_integration(
        hass,
        aioclient_mock,
        fixture,
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={
            CONF_KEY_IS_WASHER_DRYER: True,
            CONF_KEY_BRAND: "hoover",
        },
    )

    dry_target_state = hass.states.get(
        "sensor.washer_dryer_dry_target"
    ) or hass.states.get("sensor.dry_target")
    assert dry_target_state is not None
    assert dry_target_state.state == "wool_dry"


async def test_washer_dryer_sensor_not_created_for_washing_machine(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Standard washing machines do not create dry target sensor and keep standard name."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response='{"statusCounters": {"Program1": "10"}}',
    )

    dev_reg = device_registry.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Washing machine"
    assert device.manufacturer == "Candy"

    main_state = hass.states.get("sensor.washing_machine")
    assert main_state is not None
    assert main_state.state == "Idle"
    assert main_state.attributes["friendly_name"] == "Washing machine"

    dry_target_state = (
        hass.states.get("sensor.washer_dryer_dry_target")
        or hass.states.get("sensor.washing_machine_dry_target")
        or hass.states.get("sensor.wash_dry_target")
    )
    assert dry_target_state is None


async def test_program_sensor_disambiguation_multi_programs_same_selector(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test wash program sensor correctly disambiguates between drying programs sharing selector 16."""
    multi_programs = [
        {
            "program": {
                "position": 16,
                "name": "DUAL_WM_WD_PROGRAM_NAME_HIGH_DRY",
                "command_parameters": [
                    {
                        "command_parameter": {
                            "name": "selector_position",
                            "validation": "16",
                        }
                    },
                    {"command_parameter": {"name": "pr_code", "validation": "45"}},
                ],
            }
        },
        {
            "program": {
                "position": 17,
                "name": "DUAL_WM_WD_PROGRAM_NAME_LOW_DRY",
                "command_parameters": [
                    {
                        "command_parameter": {
                            "name": "selector_position",
                            "validation": "16",
                        }
                    },
                    {"command_parameter": {"name": "pr_code", "validation": "75"}},
                ],
            }
        },
    ]

    # 1. Appliance reports Pr=16 and PrCode=75 (Low Dry)
    low_dry_payload = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "16"')
        .replace('"PrCode": "136"', '"PrCode": "75"')
    )
    entry = await init_integration(
        hass,
        aioclient_mock,
        low_dry_payload,
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={
            CONF_KEY_PROGRAMS: multi_programs,
            CONF_KEY_IS_WASHER_DRYER: True,
        },
    )

    state = hass.states.get("sensor.wash_program")
    assert state is not None
    assert state.state == "Low Heat Dry"

    # 2. Appliance updates to Pr=16 and PrCode=45 (High Dry)
    high_dry_payload = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "16"')
        .replace('"PrCode": "136"', '"PrCode": "45"')
    )
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=high_dry_payload
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.wash_program")
    assert state is not None
    assert state.state == "High Heat Dry"


async def test_wash_program_sensor_one_fi_extra(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test wash program sensor displays One-Fi Extra when appliance is set to position 15."""
    one_fi_program = [
        {
            "program": {
                "position": 15,
                "name": "DUAL_WM_WD_PROGRAM_NAME_ONE_FI_EXTRA",
                "command_parameters": [
                    {
                        "command_parameter": {
                            "name": "selector_position",
                            "validation": "15",
                        }
                    },
                ],
            }
        }
    ]

    idle_pos_15 = (
        load_fixture("washing_machine/idle.json")
        .replace('"Pr": "1"', '"Pr": "15"')
        .replace('"PrCode": "136"', '"PrCode": "0"')
    )
    await init_integration(
        hass,
        aioclient_mock,
        idle_pos_15,
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={
            CONF_KEY_PROGRAMS: one_fi_program,
            CONF_KEY_IS_WASHER_DRYER: True,
        },
    )

    state = hass.states.get("sensor.wash_program")
    assert state is not None
    assert state.state == "One-Fi Extra"


async def test_autodose_cycles_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    raw_status = load_fixture("washing_machine/idle.json")
    data = json.loads(raw_status)
    data["statusLavatrice"]["DPrgCnt"] = "25"
    data["statusLavatrice"]["SPrgCnt"] = "18"
    status_with_autodose = json.dumps(data)

    entry = await init_integration(
        hass,
        aioclient_mock,
        status_with_autodose,
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={CONF_KEY_INTERFACE_TYPE: "red_devil_axi_ad"},
    )

    registry = er.async_get(hass)
    det_cycles_id = registry.async_get_entity_id(
        "sensor", DOMAIN, UNIQUE_ID_WASH_DETERGENT_CYCLES.format(entry.entry_id)
    )
    soft_cycles_id = registry.async_get_entity_id(
        "sensor", DOMAIN, UNIQUE_ID_WASH_SOFTENER_CYCLES.format(entry.entry_id)
    )

    assert det_cycles_id is not None
    assert soft_cycles_id is not None

    det_state = hass.states.get(det_cycles_id)
    assert det_state is not None
    assert det_state.state == "25"

    soft_state = hass.states.get(soft_cycles_id)
    assert soft_state is not None
    assert soft_state.state == "18"


async def test_async_setup_entry_purchase_date_and_invalid_type(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test setup with purchase date sensor in full control and invalid machine type."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture("washing_machine/idle.json"),
        statistics_response='{"statusCounters": {"Program1": "10"}}',
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PURCHASE_DATE: "2023-01-01",
        },
    )
    reg = er.async_get(hass)
    entity_id = reg.async_get_entity_id(
        "sensor", DOMAIN, UNIQUE_ID_WASH_PURCHASE_DATE.format(entry.entry_id)
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "2023-01-01"

    # Invalid machine type raises TypeError
    bad_entry = MockConfigEntry(domain=DOMAIN, entry_id="bad_entry", data={})
    hass.data.setdefault(DOMAIN, {})[bad_entry.entry_id] = {
        DATA_KEY_COORDINATOR: MagicMock(data="unknown_machine_type")
    }
    with pytest.raises(TypeError, match="Unable to determine machine type"):
        await async_setup_entry(hass, bad_entry, MagicMock())


def test_candy_base_sensor_device_info_and_abstractmethods() -> None:
    """Test CandyBaseSensor device info attributes and abstract method fallbacks."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_entry",
        data={
            CONF_KEY_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_DEVICE_MODEL: "ModelX",
            CONF_KEY_SERIAL_NUMBER: "SN12345",
        },
    )
    sensor = CandyWashingMachineSensor(MagicMock(), entry)
    info = sensor.device_info
    assert info["connections"] == {(dr.CONNECTION_NETWORK_MAC, "AA:BB:CC:DD:EE:FF")}
    assert info["model"] == "ModelX"
    assert info["serial_number"] == "SN12345"

    assert CandyBaseSensor.device_name(sensor) is None
    assert CandyBaseSensor.suggested_area(sensor) is None


def test_candy_washing_machine_sensor_unique_id_washer_dryer_migration(
    hass: HomeAssistant,
) -> None:
    """Test washer-dryer unique_id fallback when old washing machine entity exists."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="wd_entry",
        data={CONF_KEY_IS_WASHER_DRYER: True},
    )
    entry.add_to_hass(hass)
    sensor = CandyWashingMachineSensor(MagicMock(), entry)
    sensor.hass = hass

    registry = er.async_get(hass)
    old_id = UNIQUE_ID_WASHING_MACHINE.format(entry.entry_id)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        old_id,
        config_entry=entry,
        suggested_object_id="candy_washing_machine",
    )
    assert sensor.unique_id == old_id


def test_candy_wash_dry_target_sensor_none_data() -> None:
    """Test CandyWashDryTargetSensor returns None when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = CandyWashDryTargetSensor(
        coordinator, MockConfigEntry(domain=DOMAIN, entry_id="e1", data={})
    )
    assert sensor.native_value is None


async def test_candy_wash_error_sensor_restoration(hass: HomeAssistant) -> None:
    """Test error sensor restoration and state fallback when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.last_update_success = False
    sensor = CandyWashErrorSensor(
        coordinator, MockConfigEntry(domain=DOMAIN, entry_id="e1", data={})
    )
    sensor.hass = hass
    last_data = MagicMock()
    last_data.native_value = 5
    sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)

    await sensor.async_added_to_hass()
    assert sensor.available is True
    assert sensor.native_value == 5


def test_candy_wash_autodose_cycles_sensors_none_data() -> None:
    """Test detergent and softener cycles sensors return None when coordinator data is None."""
    coordinator = MagicMock()
    coordinator.data = None
    entry = MockConfigEntry(domain=DOMAIN, entry_id="e1", data={})

    det_sensor = CandyWashDetergentCyclesSensor(coordinator, entry)
    assert det_sensor.native_value is None

    soft_sensor = CandyWashSoftenerCyclesSensor(coordinator, entry)
    assert soft_sensor.native_value is None


async def test_candy_wash_checkup_result_sensor_restoration_and_cached(
    hass: HomeAssistant,
) -> None:
    """Test checkup result restoration and cached result fallback."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.last_update_success = False
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="e1",
        data={CONF_KEY_CHECKUP_LAST_RESULT: 1},
    )
    sensor = CandyWashCheckUpResultSensor(coordinator, entry)
    sensor.hass = hass

    last_data = MagicMock()
    last_data.native_value = "ok"
    sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)

    await sensor.async_added_to_hass()
    assert sensor.available is True
    assert sensor._restored_state == "ok"

    # Status has dis_test_res code 0, fallback to cached entry config
    status = MagicMock()
    status.dis_test_res = MagicMock(code=0)
    coordinator.data = status
    assert sensor.native_value == "ok"


def test_candy_wash_purchase_date_sensor() -> None:
    """Test CandyWashPurchaseDateSensor properties and None handling."""
    coordinator = MagicMock()
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="e1",
        data={CONF_KEY_PURCHASE_DATE: "2023-05-20"},
    )
    sensor = CandyWashPurchaseDateSensor(coordinator, entry)
    assert sensor.device_name() is not None
    assert sensor.suggested_area() is not None
    assert sensor.available is True
    assert sensor.unique_id == UNIQUE_ID_WASH_PURCHASE_DATE.format("e1")
    assert sensor.device_class == SensorDeviceClass.DATE
    assert sensor.native_value == dt.date(2023, 5, 20)
    assert sensor.icon == "mdi:calendar"

    empty_sensor = CandyWashPurchaseDateSensor(
        coordinator,
        MockConfigEntry(
            domain=DOMAIN, entry_id="e2", data={CONF_KEY_PURCHASE_DATE: ""}
        ),
    )
    assert empty_sensor.native_value is None


async def test_candy_wash_maintenance_sensors_restoration(hass: HomeAssistant) -> None:
    """Test maintenance sensors restore values properly when coordinator data is None."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="e1", data={})
    for sensor_cls in (
        CandyWashMaintFullCheckupSensor,
        CandyWashMaintLimescaleSensor,
        CandyWashMaintFilterSensor,
    ):
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.last_update_success = False
        sensor = sensor_cls(coordinator, entry)
        sensor.hass = hass
        last_data = MagicMock()
        last_data.native_value = "25"
        sensor.async_get_last_sensor_data = AsyncMock(return_value=last_data)

        await sensor.async_added_to_hass()
        assert sensor.available is True
        assert sensor._restored_value == 25
        assert sensor.native_value == 25


def test_candy_wash_scheduled_start_and_finish_sensors(hass: HomeAssistant) -> None:
    """Test scheduled start and finish sensors edge cases returning None."""
    coordinator = MagicMock()
    entry = MockConfigEntry(domain=DOMAIN, entry_id="e1", data={})

    # Scheduled start with delay <= 0
    start_sensor = CandyWashScheduledStartSensor(coordinator, entry)
    start_sensor.hass = hass
    with patch("custom_components.candy.sensor._read_delay_minutes", return_value=0):
        assert start_sensor.native_value is None

    # Scheduled finish sensor
    finish_sensor = CandyWashScheduledFinishSensor(coordinator, entry)
    finish_sensor.hass = hass

    # Running with remaining minutes <= 0
    status_running = MagicMock()
    status_running.machine_state = MachineState.RUNNING
    status_running.remaining_minutes = 0
    coordinator.data = status_running
    assert finish_sensor.native_value is None

    # Idle with estimated duration is None
    status_idle = MagicMock()
    status_idle.machine_state = MachineState.IDLE
    coordinator.data = status_idle
    with patch.object(finish_sensor, "_estimated_duration_minutes", return_value=None):
        assert finish_sensor.native_value is None

    # Machine state other
    status_error = MagicMock()
    status_error.machine_state = MachineState.ERROR
    coordinator.data = status_error
    assert finish_sensor.native_value is None
