"""Tests for various sensors."""

from unittest.mock import patch

from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry, entity_registry
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
from custom_components.candy.client.model import DownloadableProgram
from custom_components.candy.const import (
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_IS_WASHING_MACHINE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
    UNIQUE_ID_WASH_LIQUID_DETERGENT,
    UNIQUE_ID_WASH_POWDER_DETERGENT,
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
            "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "1"}},
                {"command_parameter": {"name": "pr_code", "validation": "136"}},
            ],
        }
    },
    {
        "program": {
            "position": 2,
            "name": "DUAL_WM_WD_PROGRAM_NAME_RAPID_30_MIN",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "2"}},
                {"command_parameter": {"name": "pr_code", "validation": "5"}},
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
    soil_level=0,
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
        .replace('"Pr": "1"', '"Pr": "2"')
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
            statistics_response='{"statusCounters": {"Program1": "10"}}',
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
        .replace('"Pr": "1"', '"Pr": "2"')
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
            statistics_response='{"statusCounters": {"Program1": "10"}}',
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
        .replace('"Pr": "1"', '"Pr": "2"')
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
            statistics_response='{"statusCounters": {"Program1": "10"}}',
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
        .replace('"Pr": "1"', '"Pr": "2"')
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
            statistics_response='{"statusCounters": {"Program1": "10"}}',
            extra_config_data={
                CONF_KEY_PROGRAMS: _TEST_PROGRAMS,
                CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
            },
        )

    state = hass.states.get("sensor.wash_program")
    assert state
    assert state.state == "Rapid 30 Min."
    assert state.attributes["recipe_id"] == "D_999"


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
    assert state.state == "40"
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


async def test_dry_phase_sensor_idle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("sensor.wash_drying_phase")

    assert state
    assert state.state == "off"  # DryT=0
    assert state.attributes["options"] == [
        "off",
        "extra_dry",
        "iron_dry",
        "cupboard_dry",
        "time_120",
        "time_90",
        "time_60",
        "time_30",
    ]


async def test_dry_phase_sensor_running_with_drying_attached(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    running_with_dry = load_fixture("washing_machine/running_wash.json").replace(
        '"DryT": "0"', '"DryT": "3"'
    )
    await init_integration(hass, aioclient_mock, running_with_dry)

    state = hass.states.get("sensor.wash_drying_phase")

    assert state
    assert state.state == "cupboard_dry"


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
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 0,
    CONF_KEY_MAINTENANCE_LAST_FILTER: 0,
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
    """total_cycles=40, last_full_checkup=0, threshold=100 → 60 cycles remaining."""
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
    """total_cycles=40, last_limescale=0, hardness=2 (threshold=100) → 60 remaining."""
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
    """total_cycles=40, last_limescale=0, hardness=5 (threshold=85) → 45 remaining."""
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
    """total_cycles=40, last_filter=0, threshold=100 → 60 remaining."""
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
    # total_cycles=40, threshold=100; last_full_checkup=-60 → elapsed=100 → due
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = -60

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
    # total_cycles=40, last_selfclean=40 → elapsed=0 → full threshold=100
    config = dict(_MAINTENANCE_CONFIG)
    config[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = 40

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
            "position": 1,
            "name": "COTTON",
            "command_parameters": [
                {"command_parameter": {"name": "pr_code", "validation": "136"}},
                {
                    "command_parameter": {
                        "name": "maximum_temperature",
                        "validation": "90",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_temperature",
                        "validation": "40",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_spin_speed",
                        "validation": "1400",
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
                        "validation": "3",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_soil_level",
                        "validation": "2",
                    }
                },
            ],
        }
    }
]

_PROGRAM_WITH_DOSE = [
    {
        "program": {
            "position": 1,
            "name": "COTTON",
            "command_parameters": [
                {"command_parameter": {"name": "pr_code", "validation": "136"}},
                {
                    "command_parameter": {
                        "name": "maximum_temperature",
                        "validation": "90",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_temperature",
                        "validation": "40",
                    }
                },
                {
                    "command_parameter": {
                        "name": "maximum_spin_speed",
                        "validation": "1400",
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
                        "validation": "3",
                    }
                },
                {
                    "command_parameter": {
                        "name": "default_soil_level",
                        "validation": "2",
                    }
                },
                {
                    "command_parameter": {
                        "name": "liquid_detergent_dose",
                        "validation": "2",
                    }
                },
                {
                    "command_parameter": {
                        "name": "powder_detergent_dose",
                        "validation": "3",
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
