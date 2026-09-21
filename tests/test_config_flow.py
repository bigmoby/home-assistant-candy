import asyncio
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client import Encryption
from custom_components.candy.client.cloud import CloudApplianceData, SimplyFiCloudError
from custom_components.candy.client.model import (
    DryerCycleState,
    DryerProgramState,
    MachineState,
    TumbleDryerStatus,
    WashingMachineStatistics,
    WashingMachineStatus,
    WashProgramState,
)
from custom_components.candy.config_flow import MANUAL_IP_OPTION
from custom_components.candy.const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CHECKUP_SCHEDULE_WEEKLY,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_IS_WASHING_MACHINE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_SERIAL_NUMBER,
    CONF_KEY_WATER_HARDNESS,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    UNIQUE_ID_WASH_MAINT_FULL_CHECKUP,
)

_IDLE_WASHING_MACHINE = WashingMachineStatus(
    machine_state=MachineState.IDLE,
    program_state=WashProgramState.STOPPED,
    program=0,
    program_code=None,
    temp=0,
    spin_speed=0,
    remaining_minutes=0,
    remote_control=False,
    fill_percent=None,
    error=None,
    delay_value=None,
    ntc_water=None,
    ntc_drum=None,
    motor_speed_freq=None,
    motor_state=None,
    unbalance_fault=None,
    unbalance_count=None,
    fault_count=None,
    dis_test_res=None,
    soil_level=None,
    recipe_id=None,
    dry_type=None,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bypass_setup_fixture():
    """Prevent setup."""
    with patch(
        "custom_components.candy.async_setup_entry",
        return_value=True,
    ):
        yield


@pytest.fixture(autouse=True)
def _device_probe_washing_machine():
    """Make the device-type probe return a washing machine for all tests."""
    with patch(
        "custom_components.candy.config_flow.CandyClient.status",
        new_callable=AsyncMock,
        return_value=_IDLE_WASHING_MACHINE,
    ):
        yield


@pytest.fixture(autouse=True)
def _statistics_probe():
    """Return total_cycles=40 during config flow setup for all tests."""
    with patch(
        "custom_components.candy.config_flow.CandyClient.statistics_with_retry",
        new_callable=AsyncMock,
        return_value=WashingMachineStatistics(total_cycles=40),
    ):
        yield


@pytest.fixture(name="no_discovery")
def _no_discovery_fixture():
    """Suppress LAN discovery so tests run fast."""
    with (
        patch(
            "custom_components.candy.config_flow.discover_devices",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "custom_components.candy.config_flow.async_get_source_ip",
            new_callable=AsyncMock,
            return_value="192.168.1.100",
        ),
    ):
        yield


@pytest.fixture(name="detect_no_encryption", autouse=False)
def _detect_no_encryption_fixture():
    with patch(
        "custom_components.candy.config_flow.detect_encryption",
        return_value=(Encryption.NO_ENCRYPTION, None),
    ):
        yield


@pytest.fixture(name="detect_encryption_find_key", autouse=False)
def _detect_encryption_find_key_fixture():
    with patch(
        "custom_components.candy.config_flow.detect_encryption",
        return_value=(Encryption.ENCRYPTION, "testkey"),
    ):
        yield


@pytest.fixture(name="detect_encryption_key_not_found", autouse=False)
def _detect_encryption_key_not_found_fixture():
    with patch(
        "custom_components.candy.config_flow.detect_encryption", side_effect=ValueError
    ):
        yield


@pytest.fixture(name="detect_encryption_without_key", autouse=False)
def _detect_encryption_without_key_fixture():
    with patch(
        "custom_components.candy.config_flow.detect_encryption",
        return_value=(Encryption.ENCRYPTION_WITHOUT_KEY, None),
    ):
        yield


# ---------------------------------------------------------------------------
# Existing config flow tests (manual IP path)
# ---------------------------------------------------------------------------


async def test_no_encryption_detected(hass, no_discovery, detect_no_encryption):  # pylint: disable=unused-argument
    """Test a successful config flow when detected encryption is no encryption."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Candy"
    assert result["data"][CONF_IP_ADDRESS] == "192.168.0.66"
    assert result["data"][CONF_KEY_USE_ENCRYPTION] is False
    assert result["data"][CONF_KEY_MODE] == MODE_READ_ONLY
    assert result["result"]


async def test_detected_encryption_and_key_found(
    hass, no_discovery, detect_encryption_find_key
):  # pylint: disable=unused-argument
    """Test a successful config flow when encryption is detected and key is found."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Candy"
    assert result["data"][CONF_IP_ADDRESS] == "192.168.0.66"
    assert result["data"][CONF_KEY_USE_ENCRYPTION] is True
    assert result["data"][CONF_PASSWORD] == "testkey"
    assert result["data"][CONF_KEY_MODE] == MODE_READ_ONLY
    assert result["result"]


async def test_detected_encryption_and_key_not_found(
    hass, no_discovery, detect_encryption_key_not_found
):  # pylint: disable=unused-argument
    """Test a failing config flow when encryption is detected and key is not found."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "detect_encryption"}


async def test_detected_encryption_without_key(
    hass, no_discovery, detect_encryption_without_key
):  # pylint: disable=unused-argument
    """Test a successful config flow when encryption is detected without using a key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Candy"
    assert result["data"][CONF_IP_ADDRESS] == "192.168.0.66"
    assert result["data"][CONF_KEY_USE_ENCRYPTION] is True
    assert result["data"][CONF_PASSWORD] == ""
    assert result["data"][CONF_KEY_MODE] == MODE_READ_ONLY
    assert result["result"]


# ---------------------------------------------------------------------------
# New discovery tests
# ---------------------------------------------------------------------------


async def test_discovery_finds_devices_and_shows_select(hass, detect_no_encryption):  # pylint: disable=unused-argument
    """Test that when discovery finds devices the select step is shown."""
    with (
        patch(
            "custom_components.candy.config_flow.discover_devices",
            new_callable=AsyncMock,
            return_value={"192.168.1.79": "Washing Machine"},
        ),
        patch(
            "custom_components.candy.config_flow.async_get_source_ip",
            new_callable=AsyncMock,
            return_value="192.168.1.100",
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "select"


async def test_discovery_select_device(hass, detect_no_encryption):  # pylint: disable=unused-argument
    """Test selecting a discovered device proceeds to mode selection."""
    with (
        patch(
            "custom_components.candy.config_flow.discover_devices",
            new_callable=AsyncMock,
            return_value={"192.168.1.79": "Washing Machine"},
        ),
        patch(
            "custom_components.candy.config_flow.async_get_source_ip",
            new_callable=AsyncMock,
            return_value="192.168.1.100",
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    assert result["step_id"] == "select"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.1.79"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IP_ADDRESS] == "192.168.1.79"
    assert result["data"][CONF_KEY_USE_ENCRYPTION] is False
    assert result["data"][CONF_KEY_MODE] == MODE_READ_ONLY


async def test_discovery_select_manual_fallback(hass):
    """Test selecting 'manual' from the select step shows the manual IP form."""
    with (
        patch(
            "custom_components.candy.config_flow.discover_devices",
            new_callable=AsyncMock,
            return_value={"192.168.1.79": "Washing Machine"},
        ),
        patch(
            "custom_components.candy.config_flow.async_get_source_ip",
            new_callable=AsyncMock,
            return_value="192.168.1.100",
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    assert result["step_id"] == "select"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: MANUAL_IP_OPTION}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_discovery_no_devices_shows_manual_form(hass, no_discovery):
    """Test that when no devices are found the manual IP form is shown directly."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


# ---------------------------------------------------------------------------
# Full Control flow (mode=FULL_CONTROL → cloud credentials step)
# ---------------------------------------------------------------------------

_MOCK_APPLIANCE = CloudApplianceData(
    mac_address="AA:BB:CC:DD:EE:FF",
    encryption_key="testenckey",
    appliance_model="RO41274DWMSE/1-S",
    serial_number="1234567890123456",
    purchase_date="2022-01-13",
    interface_type="RAPIDO_4DIG_STM_NEL",
    programs=[
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
    ],
    downloadable_programs=[],
)


@pytest.fixture(name="mock_cloud_success")
def _mock_cloud_success_fixture():
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=_MOCK_APPLIANCE,
    ):
        yield


@pytest.fixture(name="mock_cloud_error")
def _mock_cloud_error_fixture():
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        side_effect=SimplyFiCloudError("bad credentials"),
    ):
        yield


async def test_full_control_flow(
    hass, no_discovery, detect_no_encryption, mock_cloud_success
):
    """Full Control setup flow: IP → mode=FULL_CONTROL → cloud credentials → entry created."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    assert result["step_id"] == "mode"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_FULL_CONTROL}
    )
    assert result["step_id"] == "cloud"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"email": "user@example.com", "password": "pass"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "language"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "checkup"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_CHECKUP_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_KEY_MODE] == MODE_FULL_CONTROL
    assert data[CONF_KEY_USE_ENCRYPTION] is True
    assert data[CONF_PASSWORD] == "testenckey"
    assert data[CONF_KEY_DEVICE_MODEL] == "RO41274DWMSE/1-S"
    assert data[CONF_KEY_SERIAL_NUMBER] == "1234567890123456"
    assert len(data[CONF_KEY_PROGRAMS]) == 1
    assert data[CONF_KEY_PROGRAM_LANGUAGE] == "en"
    # Credentials must NOT be stored
    assert "email" not in data
    assert "password_plain" not in data


async def test_full_control_cloud_error(
    hass, no_discovery, detect_no_encryption, mock_cloud_error
):
    """Cloud step shows cloud_auth error when fetch_appliance_data raises."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_FULL_CONTROL}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"email": "bad@example.com", "password": "wrong"}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "cloud"
    assert result["errors"] == {"base": "cloud_auth"}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Maintenance counter flow tests
# ---------------------------------------------------------------------------

_IDLE_TUMBLE_DRYER = TumbleDryerStatus(
    machine_state=MachineState.IDLE,
    program_state=DryerProgramState.STOPPED,
    cycle_state=DryerCycleState.LEVEL_NONE,
    program=0,
    remaining_minutes=0,
    remote_control=False,
    dry_level=0,
    dry_level_selected=0,
    refresh=False,
    need_clean_filter=False,
    water_tank_full=False,
    door_closed=True,
)


async def test_maintenance_step_skipped_for_non_washing_machine(
    hass, no_discovery, detect_no_encryption
):
    """Non-washing-machine devices skip the maintenance step entirely."""
    with patch(
        "custom_components.candy.config_flow.CandyClient.status",
        new_callable=AsyncMock,
        return_value=_IDLE_TUMBLE_DRYER,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert CONF_KEY_IS_WASHING_MACHINE not in result["data"]
    assert CONF_KEY_MAINTENANCE_ENABLED not in result["data"]


async def test_read_only_with_maintenance_disabled(
    hass, no_discovery, detect_no_encryption
):  # pylint: disable=unused-argument
    """Read-Only flow with maintenance counters disabled creates entry without maintenance keys."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )

    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KEY_MAINTENANCE_ENABLED] is False
    assert CONF_KEY_WATER_HARDNESS not in result["data"]


async def test_read_only_with_maintenance_enabled(
    hass, no_discovery, detect_no_encryption
):  # pylint: disable=unused-argument
    """Maintenance flow: user enters remaining cycles, stored as last_reset = total - (threshold - remaining)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )

    assert result["step_id"] == "maintenance_types"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: True,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: True,
        },
    )

    assert result["step_id"] == "hardness"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_WATER_HARDNESS: "2"}
    )

    assert result["step_id"] == "maintenance_baselines"

    # User enters remaining=17 for all (total_cycles=40 from mocked stats)
    # last_reset = total - (threshold - remaining)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 17,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 57,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 17,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_KEY_MAINTENANCE_ENABLED] is True
    assert data[CONF_KEY_WATER_HARDNESS] == 2
    # last_reset = total - (threshold - remaining)
    # full_checkup:  40 - (100 - 17) = 40 - 83 = -43
    # limescale:  40 - (100 - 57) = 40 - 43 = -3   (hardness=2 → threshold=100)
    # filter:     40 - (100 - 17) = 40 - 83 = -43
    assert data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == -43
    assert data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == -3
    assert data[CONF_KEY_MAINTENANCE_LAST_FILTER] == -43
    assert data[CONF_KEY_IS_WASHING_MACHINE] is True


async def test_options_flow_maintenance_settings(
    hass, no_discovery, detect_no_encryption
):  # pylint: disable=unused-argument
    """Options flow maintenance_settings: remaining values are converted to last_reset on save."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="opts-maint-test",
        data={
            CONF_IP_ADDRESS: "192.168.0.66",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
            CONF_KEY_IS_WASHING_MACHINE: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_WATER_HARDNESS: 2,
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 0,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 0,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )

    assert result["step_id"] == "maintenance_types"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: True,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: True,
        },
    )

    assert result["step_id"] == "hardness"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_WATER_HARDNESS: "5"}
    )

    assert result["step_id"] == "maintenance_baselines"

    # stats coordinator not available in this test (setup bypassed) → total_cycles=0
    # last_reset = max(0, 0 - (threshold - remaining)) = 0 for any positive remaining
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 50,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 40,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 60,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_KEY_WATER_HARDNESS] == 5
    assert updated.data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 0
    assert updated.data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 0
    assert updated.data[CONF_KEY_MAINTENANCE_LAST_FILTER] == 0


async def test_options_flow_maintenance_settings_disable(
    hass, no_discovery, detect_no_encryption
):  # pylint: disable=unused-argument
    """Disabling maintenance counters via options flow clears maintenance_enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="opts-maint-disable",
        data={
            CONF_IP_ADDRESS: "192.168.0.66",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
            CONF_KEY_IS_WASHING_MACHINE: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_WATER_HARDNESS: 2,
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 0,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 0,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_KEY_MAINTENANCE_ENABLED] is False


async def test_maintenance_only_full_checkup(hass, no_discovery, detect_no_encryption):  # pylint: disable=unused-argument
    """When both optional counters are disabled, hardness step is skipped and baselines only shows full_checkup."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )

    assert result["step_id"] == "maintenance_types"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: False,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: False,
        },
    )

    # Hardness step skipped — limescale disabled
    assert result["step_id"] == "maintenance_baselines"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 50},
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_KEY_MAINTENANCE_ENABLED] is True
    assert data[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED] is False
    assert data[CONF_KEY_MAINTENANCE_FILTER_ENABLED] is False
    assert CONF_KEY_WATER_HARDNESS not in data
    assert CONF_KEY_MAINTENANCE_LAST_LIMESCALE not in data
    assert CONF_KEY_MAINTENANCE_LAST_FILTER not in data
    # total_cycles=40 from mock; full_checkup remaining=50 → last_reset = 40 - (100 - 50) = -10
    assert data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == -10


async def test_maintenance_limescale_only(hass, no_discovery, detect_no_encryption):  # pylint: disable=unused-argument
    """When only limescale is enabled, hardness is shown but filter field is absent from baselines."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )

    assert result["step_id"] == "maintenance_types"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: True,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: False,
        },
    )

    # Limescale enabled → hardness step shown
    assert result["step_id"] == "hardness"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_WATER_HARDNESS: "2"}
    )

    assert result["step_id"] == "maintenance_baselines"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 17,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 57,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED] is True
    assert data[CONF_KEY_MAINTENANCE_FILTER_ENABLED] is False
    assert CONF_KEY_MAINTENANCE_LAST_FILTER not in data
    # selfclean:  40 - (100 - 17) = -43
    # limescale:  40 - (100 - 57) = -3   (hardness=2 → threshold=100)
    assert data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == -43
    assert data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == -3


# ---------------------------------------------------------------------------
# Options flow — FULL_CONTROL paths
# ---------------------------------------------------------------------------

_FC_BASE_DATA = {
    CONF_IP_ADDRESS: "192.168.0.66",
    CONF_KEY_USE_ENCRYPTION: True,
    CONF_PASSWORD: "key",
    CONF_KEY_MODE: MODE_FULL_CONTROL,
    CONF_KEY_IS_WASHING_MACHINE: True,
}


async def test_options_flow_full_control_init_shows_menu(hass):
    """FULL_CONTROL options flow init shows the action menu."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="fc-menu", data=_FC_BASE_DATA)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_full_control_switch_to_read_only(hass):
    """switch_to_read_only removes programs keys and sets mode to READ_ONLY."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-switch-ro",
        data={
            **_FC_BASE_DATA,
            CONF_KEY_PROGRAMS: [{"program": {}}],
            CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "switch_to_read_only"}
    )
    assert result["step_id"] == "switch_to_read_only"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_KEY_MODE] == MODE_READ_ONLY
    assert CONF_KEY_PROGRAMS not in updated.data
    assert CONF_KEY_DOWNLOADABLE_PROGRAMS not in updated.data


async def test_options_flow_full_control_checkup_disabled(hass):
    """checkup_settings → checkup_enabled=False saves and exits."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-checkup-dis",
        data={**_FC_BASE_DATA, CONF_KEY_CHECKUP_ENABLED: True},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "checkup_settings"}
    )
    assert result["step_id"] == "checkup"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_CHECKUP_ENABLED: False}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_KEY_CHECKUP_ENABLED] is False


async def test_options_flow_full_control_checkup_with_schedule(hass):
    """checkup_settings → checkup_enabled=True proceeds to schedule step."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="fc-checkup-sched", data=_FC_BASE_DATA
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "checkup_settings"}
    )
    assert result["step_id"] == "checkup"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_CHECKUP_ENABLED: True}
    )
    assert result["step_id"] == "checkup_schedule"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_KEY_CHECKUP_SCHEDULE: str(CHECKUP_SCHEDULE_WEEKLY)},
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_KEY_CHECKUP_ENABLED] is True
    assert updated.data[CONF_KEY_CHECKUP_SCHEDULE] == CHECKUP_SCHEDULE_WEEKLY


async def test_options_flow_full_control_update_cloud_data_success(
    hass, mock_cloud_success
):
    """update_cloud_data → success → language form → CREATE_ENTRY."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="fc-cloud-ok", data=_FC_BASE_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "update_cloud_data"}
    )
    assert result["step_id"] == "update_cloud_data"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"email": "user@example.com", "password": "pass"},
    )
    assert result["step_id"] == "language"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_PASSWORD] == "testenckey"  # from _MOCK_APPLIANCE
    assert updated.data[CONF_KEY_DEVICE_MODEL] == "RO41274DWMSE/1-S"


async def test_options_flow_full_control_update_cloud_data_error(
    hass, mock_cloud_error
):
    """update_cloud_data cloud error re-displays the form with cloud_auth error."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="fc-cloud-err", data=_FC_BASE_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "update_cloud_data"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"email": "bad@example.com", "password": "wrong"},
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "update_cloud_data"
    assert result["errors"] == {"base": "cloud_auth"}


async def test_options_flow_non_washing_machine(hass):
    """Options flow for non-washing-machine entry creates entry immediately."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="opts-non-wm",
        data={
            CONF_IP_ADDRESS: "192.168.0.66",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_options_flow_maintenance_limescale_disabled(hass):
    """maintenance_types with limescale=False skips hardness and goes to baselines."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="opts-no-lime",
        data={
            CONF_IP_ADDRESS: "192.168.0.66",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
            CONF_KEY_IS_WASHING_MACHINE: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_WATER_HARDNESS: 2,
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 0,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )
    assert result["step_id"] == "maintenance_types"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: False,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: True,
        },
    )
    # limescale=False → hardness step skipped
    assert result["step_id"] == "maintenance_baselines"


async def test_options_flow_maintenance_baselines_defaults_from_sensor_state(
    hass,
):
    """When the stats coordinator has no data yet, baseline defaults come from the
    live sensor state instead of always falling back to the raw threshold.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="opts-baseline-sensor-default",
        data={
            CONF_IP_ADDRESS: "192.168.0.66",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
            CONF_KEY_IS_WASHING_MACHINE: True,
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_WATER_HARDNESS: 2,
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 0,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 0,
        },
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    ent = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        UNIQUE_ID_WASH_MAINT_FULL_CHECKUP.format(entry.entry_id),
        config_entry=entry,
    )
    hass.states.async_set(ent.entity_id, "37")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: False,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: False,
        },
    )

    assert result["step_id"] == "maintenance_baselines"
    schema_keys = list(result["data_schema"].schema)
    default = next(
        k for k in schema_keys if k == CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP
    ).default()
    assert default == 37


# ---------------------------------------------------------------------------
# Config flow — exception and edge paths
# ---------------------------------------------------------------------------


async def test_config_flow_discovery_exception_fallback(hass):
    """Discovery exception falls back silently to manual IP form."""
    with (
        patch(
            "custom_components.candy.config_flow.async_get_source_ip",
            new_callable=AsyncMock,
            return_value="192.168.1.100",
        ),
        patch(
            "custom_components.candy.config_flow.discover_devices",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_configure_local_statistics_exception(
    hass, no_discovery, detect_no_encryption
):
    """Statistics fetch failure defaults total_cycles to 0 and flow continues to mode."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    with patch(
        "custom_components.candy.config_flow.CandyClient.statistics_with_retry",
        new_callable=AsyncMock,
        side_effect=Exception("stats fail"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "mode"


async def test_configure_local_status_exception(
    hass, no_discovery, detect_no_encryption
):
    """Device status probe failure defaults is_washing_machine=False → immediate entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["step_id"] == "user"

    with patch(
        "custom_components.candy.config_flow.CandyClient.status",
        new_callable=AsyncMock,
        side_effect=Exception("probe fail"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_cloud_step_unexpected_exception(
    hass, no_discovery, detect_no_encryption
):
    """Non-SimplyFiCloudError in cloud step shows cloud_auth error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_FULL_CONTROL}
    )
    assert result["step_id"] == "cloud"

    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        side_effect=RuntimeError("unexpected"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "user@example.com", "password": "pass"},
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "cloud"
    assert result["errors"] == {"base": "cloud_auth"}


async def test_full_control_flow_with_checkup_schedule(
    hass, no_discovery, detect_no_encryption, mock_cloud_success
):
    """Full Control flow with checkup_enabled=True proceeds through checkup_schedule."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_FULL_CONTROL}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"email": "user@example.com", "password": "pass"},
    )
    assert result["step_id"] == "language"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
    )
    assert result["step_id"] == "maintenance"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )
    assert result["step_id"] == "checkup"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_CHECKUP_ENABLED: True}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "checkup_schedule"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_KEY_CHECKUP_SCHEDULE: str(CHECKUP_SCHEDULE_EVERY_CYCLE)},
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KEY_CHECKUP_ENABLED] is True
    assert result["data"][CONF_KEY_CHECKUP_SCHEDULE] == CHECKUP_SCHEDULE_EVERY_CYCLE
