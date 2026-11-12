import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client import Encryption
from custom_components.candy.client.cloud import CloudApplianceData, SimplyFiCloudError
from custom_components.candy.client.model import (
    DishwasherState,
    DishwasherStatus,
    DryerCycleState,
    DryerProgramState,
    MachineState,
    TumbleDryerStatus,
    WashingMachineStatistics,
    WashingMachineStatus,
    WashProgramState,
)
from custom_components.candy.config_flow import (
    MANUAL_IP_OPTION,
    _current_remaining_cycles,
    _remaining_to_last_reset,
)
from custom_components.candy.const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CHECKUP_SCHEDULE_WEEKLY,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_TUMBLE_DRYER,
    CONF_KEY_IS_WASHER_DRYER,
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
    DATA_KEY_STATS_COORDINATOR,
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
    checkup_state=None,
    soil_level=None,
    recipe_id=None,
    dry_target=None,
    detergent_on=None,
    softener_on=None,
    detergent_empty=None,
    softener_empty=None,
    detergent_reserve=None,
    softener_reserve=None,
    detergent_cycles_remaining=None,
    softener_cycles_remaining=None,
    water_hardness=None,
    extra_dose_active=None,
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
    """Return total_cycles=388 during config flow setup for all tests."""
    with patch(
        "custom_components.candy.config_flow.CandyClient.statistics_with_retry",
        new_callable=AsyncMock,
        return_value=WashingMachineStatistics(total_cycles=388),
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
    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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
    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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
    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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
    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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
                "position": 16,
                "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
                "command_parameters": [
                    {"command_parameter": {"name": "pr_code", "validation": "65"}},
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
                ],
            }
        }
    ],
    downloadable_programs=[],
    brand="candy",
    appliance_type="washer",
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
    error=None,
    delay_value=None,
    checkup_state=None,
    recipe_id=None,
    time=None,
    rapido=None,
)

_IDLE_DISHWASHER = DishwasherStatus(
    machine_state=DishwasherState.IDLE,
    program="",
    remaining_minutes=0,
    delayed_start_hours=None,
    door_open=False,
    door_open_allowed=None,
    eco_mode=False,
    remote_control=False,
    salt_empty=False,
    rinse_aid_empty=False,
)


async def test_maintenance_step_skipped_for_non_washing_machine(
    hass, no_discovery, detect_no_encryption
):
    """Non-washing-machine devices skip the maintenance step entirely."""
    with patch(
        "custom_components.candy.config_flow.CandyClient.status",
        new_callable=AsyncMock,
        return_value=_IDLE_DISHWASHER,
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


async def test_tumble_dryer_read_only_skips_maintenance(
    hass, no_discovery, detect_no_encryption
):
    """Tumble dryer in Read-Only mode skips maintenance step and creates entry."""
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
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "mode"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert CONF_KEY_IS_WASHING_MACHINE not in result["data"]
    assert CONF_KEY_MAINTENANCE_ENABLED not in result["data"]


async def test_tumble_dryer_full_control_skips_checkup_schedule(
    hass, no_discovery, detect_no_encryption
):
    """Tumble dryer in Full Control mode skips checkup scheduling and creates entry directly after language."""
    dryer_appliance = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="GVSH9A2DCE-80",
        serial_number="1234567890123456",
        purchase_date="2022-01-01",
        interface_type="TD_DIGIT_HP_DOOR",
        programs=[],
        downloadable_programs=[],
        brand="candy",
        appliance_type="dryer",
    )
    with (
        patch(
            "custom_components.candy.config_flow.CandyClient.status",
            new_callable=AsyncMock,
            return_value=_IDLE_TUMBLE_DRYER,
        ),
        patch(
            "custom_components.candy.config_flow.fetch_appliance_data",
            new_callable=AsyncMock,
            return_value=dryer_appliance,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "mode"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MODE: MODE_FULL_CONTROL}
        )
        assert result["step_id"] == "cloud"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "user@example.com", "password": "pass"},
        )
        assert result["step_id"] == "language"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert CONF_KEY_CHECKUP_ENABLED not in result["data"]
    assert CONF_KEY_CHECKUP_SCHEDULE not in result["data"]
    assert result["data"].get(CONF_KEY_IS_TUMBLE_DRYER) is True


async def test_tumble_dryer_unsupported_interface_reverts_to_read_only(
    hass, no_discovery, detect_no_encryption
):
    """Tumble dryer with unsupported (non-DualTech) interface reverts Full Control to Read-Only mode."""
    dryer_appliance = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="GVSH9A2DCE-80",
        serial_number="1234567890123456",
        purchase_date="2022-01-01",
        interface_type="TD_SMARTPRO_WIFIBLE",
        programs=[],
        downloadable_programs=[],
        brand="candy",
        appliance_type="dryer",
    )
    with (
        patch(
            "custom_components.candy.config_flow.CandyClient.status",
            new_callable=AsyncMock,
            return_value=_IDLE_TUMBLE_DRYER,
        ),
        patch(
            "custom_components.candy.config_flow.fetch_appliance_data",
            new_callable=AsyncMock,
            return_value=dryer_appliance,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "mode"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MODE: MODE_FULL_CONTROL}
        )
        assert result["step_id"] == "cloud"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"email": "user@example.com", "password": "pass"},
        )
        assert result["step_id"] == "language"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"].get(CONF_KEY_MODE) == MODE_READ_ONLY
    assert result["data"].get(CONF_KEY_IS_TUMBLE_DRYER) is True


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

    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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

    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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

    # User enters remaining=17 for all (total_cycles=388 from mocked stats)
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
    # full_checkup:  388 - (100 - 17) = 388 - 83 = 305
    # limescale:  388 - (100 - 57) = 388 - 43 = 345   (hardness=2 → threshold=100)
    # filter:     388 - (100 - 17) = 388 - 83 = 305
    assert data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 305
    assert data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 345
    assert data[CONF_KEY_MAINTENANCE_LAST_FILTER] == 305
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

    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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
    # total_cycles=388 from mock; full_checkup remaining=50 → last_reset = 388 - (100 - 50) = 338
    assert data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 338


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

    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
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
    # selfclean:  388 - (100 - 17) = 305
    # limescale:  388 - (100 - 57) = 345   (hardness=2 → threshold=100)
    assert data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] == 305
    assert data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] == 345


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


async def test_options_flow_switch_to_read_only_preserves_washer_dryer(hass):
    """switch_to_read_only preserves is_washer_dryer flag even after programs are popped."""
    dry_prog = {
        "program": {
            "position": 16,
            "name": "HIGH_DRY",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "16",
                    }
                },
                {"command_parameter": {"name": "pr_code", "validation": "45"}},
                {"command_parameter": {"name": "program_type", "validation": "D"}},
            ],
        }
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-switch-ro-wd",
        data={
            **_FC_BASE_DATA,
            CONF_KEY_PROGRAMS: [dry_prog],
            CONF_KEY_DOWNLOADABLE_PROGRAMS: [],
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "switch_to_read_only"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    updated = hass.config_entries.async_get_entry(entry.entry_id)
    assert updated.data[CONF_KEY_MODE] == MODE_READ_ONLY
    assert updated.data.get(CONF_KEY_IS_WASHER_DRYER) is True
    assert CONF_KEY_PROGRAMS not in updated.data


async def test_full_control_cloud_detects_washer_dryer_from_appliance_type(
    hass, no_discovery, detect_no_encryption
):
    """Cloud setup sets CONF_KEY_IS_WASHER_DRYER when appliance_type is washer_dryer."""
    appliance_wd = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="WD_MODEL",
        serial_number="1234567890123456",
        purchase_date="2022-01-01",
        interface_type="RAPIDO",
        programs=[],
        downloadable_programs=[],
        brand="candy",
        appliance_type="washer_dryer",
    )
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=appliance_wd,
    ):
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_CHECKUP_ENABLED: False}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"].get(CONF_KEY_IS_WASHER_DRYER) is True


async def test_full_control_cloud_does_not_set_washer_dryer_when_appliance_type_washer(
    hass, no_discovery, detect_no_encryption
):
    """Cloud setup keeps CONF_KEY_IS_WASHER_DRYER False when appliance_type is washer even if catalog has dry program."""
    dry_prog = {
        "program": {
            "position": 16,
            "name": "HIGH_DRY",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "16",
                    }
                },
                {"command_parameter": {"name": "pr_code", "validation": "45"}},
                {"command_parameter": {"name": "program_type", "validation": "D"}},
            ],
        }
    }
    appliance_washer = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="WASHER_MODEL",
        serial_number="1234567890123456",
        purchase_date="2022-01-01",
        interface_type="RAPIDO",
        programs=[dry_prog],
        downloadable_programs=[],
        brand="candy",
        appliance_type="washer",
    )
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=appliance_washer,
    ):
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_CHECKUP_ENABLED: False}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"].get(CONF_KEY_IS_WASHER_DRYER) is not True


async def test_full_control_cloud_detects_washer_dryer_from_hardware_parameters_fallback(
    hass, no_discovery, detect_no_encryption
):
    """Cloud setup falls back to structured hardware parameters when appliance_type is blank."""
    dry_prog = {
        "program": {
            "position": 16,
            "name": "HIGH_DRY",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "16",
                    }
                },
                {"command_parameter": {"name": "pr_code", "validation": "45"}},
                {"command_parameter": {"name": "program_type", "validation": "D"}},
            ],
        }
    }
    appliance_untyped = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="WD_MODEL",
        serial_number="1234567890123456",
        purchase_date="2022-01-01",
        interface_type="RAPIDO",
        programs=[dry_prog],
        downloadable_programs=[],
        brand="candy",
        appliance_type="",
    )
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=appliance_untyped,
    ):
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_CHECKUP_ENABLED: False}
        )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"].get(CONF_KEY_IS_WASHER_DRYER) is True


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


async def test_options_flow_tumble_dryer_omits_checkup_settings(hass):
    """Options flow for full-control tumble dryer omits checkup_settings option."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-dryer-options",
        data={
            **_FC_BASE_DATA,
            CONF_KEY_IS_WASHING_MACHINE: False,
            CONF_KEY_IS_TUMBLE_DRYER: True,
            CONF_KEY_INTERFACE_TYPE: "TD_DIGIT_HP_DOOR",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"].schema
    next_step_field = schema["next_step"]
    assert "checkup_settings" not in next_step_field.config["options"]
    assert "maintenance_settings" not in next_step_field.config["options"]


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


async def test_read_only_flow_with_washer_dryer_selection(
    hass, no_discovery, detect_no_encryption
):
    """Test Read-Only flow when user indicates the appliance is a washer-dryer."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )
    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: True}
    )
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KEY_IS_WASHER_DRYER] is True
    assert result["data"][CONF_KEY_MODE] == MODE_READ_ONLY


async def test_read_only_flow_with_washer_dryer_unselected(
    hass, no_discovery, detect_no_encryption
):
    """Test Read-Only flow when user indicates appliance is standard washing machine."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MODE: MODE_READ_ONLY}
    )
    assert result["step_id"] == "washer_dryer"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_IS_WASHER_DRYER: False}
    )
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KEY_IS_WASHER_DRYER] is False
    assert result["data"][CONF_KEY_MODE] == MODE_READ_ONLY


async def test_full_control_dualtech_skips_counter_types_when_maintenance_enabled(
    hass, no_discovery, detect_no_encryption
):
    """DualTech appliances skip maintenance_types and water_hardness when maintenance is enabled."""
    dualtech_appliance = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="HBDOS695",
        serial_number="1234567890123456",
        purchase_date="2022-01-13",
        interface_type="3D_DUAL",
        programs=_MOCK_APPLIANCE.programs,
        downloadable_programs=[],
        brand="hoover",
        appliance_type="washer",
    )
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=dualtech_appliance,
    ):
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "maintenance"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
        )

        # Directly skips maintenance_types and water_hardness to checkup
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "checkup"


def test_remaining_to_last_reset_and_current_remaining_cycles(hass):
    """Test helper functions in config_flow."""
    # 1. total == 0 returns 0 (line 164)
    assert _remaining_to_last_reset(50, 0, 100) == 0

    # 2. total > 0 calculates properly, including negative values
    assert _remaining_to_last_reset(80, 10, 100) == -10
    assert _remaining_to_last_reset(50, 100, 100) == 50

    # 3. _current_remaining_cycles:
    # Entity not in registry -> None
    assert (
        _current_remaining_cycles(hass, "test_id", UNIQUE_ID_WASH_MAINT_FULL_CHECKUP)
        is None
    )

    # Entity in registry, but hass.states.get is None (line 184)
    registry = er.async_get(hass)
    unique_id = UNIQUE_ID_WASH_MAINT_FULL_CHECKUP.format("test_id")
    registry.async_get_or_create("sensor", DOMAIN, unique_id)
    assert (
        _current_remaining_cycles(hass, "test_id", UNIQUE_ID_WASH_MAINT_FULL_CHECKUP)
        is None
    )

    # Entity state is non-numeric (line 184)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    hass.states.async_set(entity_id, "unavailable")
    assert (
        _current_remaining_cycles(hass, "test_id", UNIQUE_ID_WASH_MAINT_FULL_CHECKUP)
        is None
    )

    # Entity state is valid numeric
    hass.states.async_set(entity_id, "42")
    assert (
        _current_remaining_cycles(hass, "test_id", UNIQUE_ID_WASH_MAINT_FULL_CHECKUP)
        == 42
    )


async def test_options_flow_maintenance_settings_branch(hass):
    """Test user selecting maintenance_settings in options flow init (line 265)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-opts-maint",
        data=_FC_BASE_DATA,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "maintenance_settings"}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "maintenance"


async def test_options_flow_maintenance_disabled_with_checkup(hass):
    """Test options flow maintenance disabled advancing to checkup (line 319)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-opts-maint-dis-checkup",
        data={
            **_FC_BASE_DATA,
            CONF_KEY_INTERFACE_TYPE: "RAPIDO",
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "maintenance_settings"}
    )
    assert result["step_id"] == "maintenance"

    # Maintenance disabled with can_checkup=True advances to checkup (line 319)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: False}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "checkup"


async def test_options_flow_dualtech_maintenance_paths(hass):
    """Test options flow maintenance for DualTech appliances (lines 328-336)."""
    # 1. Dualtech with can_checkup=True advances to checkup (line 329)
    entry_can_checkup = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-opts-dualtech-checkup",
        data={
            **_FC_BASE_DATA,
            CONF_KEY_INTERFACE_TYPE: "3D_DUAL",
        },
    )
    entry_can_checkup.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry_can_checkup.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "maintenance_settings"}
    )
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "checkup"

    # 2. Dualtech with can_checkup=False (read-only mode) saves entry directly (lines 330-336)
    entry_no_checkup = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ro-opts-dualtech-maint",
        data={
            CONF_IP_ADDRESS: "192.168.0.66",
            CONF_KEY_MODE: MODE_READ_ONLY,
            CONF_KEY_IS_WASHING_MACHINE: True,
            CONF_KEY_INTERFACE_TYPE: "3D_DUAL",
        },
    )
    entry_no_checkup.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry_no_checkup.entry_id)
    assert result["step_id"] == "maintenance"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
    )
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_options_flow_maintenance_baselines_with_stats_data_and_checkup(hass):
    """Test options flow maintenance baselines with stats data and advance to checkup (lines 426, 436-444, 515)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="fc-opts-stats-baselines",
        data={
            **_FC_BASE_DATA,
            CONF_KEY_INTERFACE_TYPE: "RAPIDO",
            CONF_KEY_WATER_HARDNESS: 2,
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 0,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 0,
        },
    )
    entry.add_to_hass(hass)

    # Provide stats coordinator data with total_cycles > 0 (line 426)
    mock_stats_coord = MagicMock()
    mock_stats_coord.data = WashingMachineStatistics(total_cycles=150)
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})[
        DATA_KEY_STATS_COORDINATOR
    ] = mock_stats_coord

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "maintenance_settings"}
    )
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
        result["flow_id"],
        user_input={CONF_KEY_WATER_HARDNESS: "2"},
    )
    assert result["step_id"] == "maintenance_baselines"

    # Verify defaults were calculated using cycles_remaining from total_cycles (lines 436-444)
    schema_keys = list(result["data_schema"].schema)
    sc_default = next(
        k for k in schema_keys if k == CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP
    ).default()
    # 100 - (150 - 0) = -50 -> overdue -> 0
    assert sc_default == 0

    # Submitting baselines advances to checkup (line 515)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 100,
            CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 100,
            CONF_KEY_MAINTENANCE_LAST_FILTER: 100,
        },
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "checkup"


async def test_options_flow_update_cloud_data_exceptions_and_washer_dryer(hass):
    """Test options flow cloud update exception handling and washer-dryer detection (lines 620-623, 649, 652-654)."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="fc-cloud-opts-err", data=_FC_BASE_DATA
    )
    entry.add_to_hass(hass)

    # 1. Unexpected Exception in fetch_appliance_data (lines 620-623)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "update_cloud_data"}
    )
    assert result["step_id"] == "update_cloud_data"

    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Unexpected connection crash"),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={"email": "user@example.com", "password": "pass"},
        )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "update_cloud_data"
    assert result["errors"] == {"base": "cloud_auth"}

    # 2. appliance_type == 'washer_dryer' and malformed programs (lines 649, 652-654)
    wd_appliance = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="WD_MODEL",
        serial_number="1234567890123456",
        purchase_date="2022-01-01",
        interface_type="RAPIDO",
        programs=[{"invalid": "data"}],
        downloadable_programs=[],
        brand="candy",
        appliance_type="washer_dryer",
    )
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=wd_appliance,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={"email": "user@example.com", "password": "pass"},
        )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "language"

    # 3. Programs contain dry program -> sets is_washer_dryer when appliance_type is blank
    dry_prog = {
        "program": {
            "position": 16,
            "name": "HIGH_DRY",
            "command_parameters": [
                {
                    "command_parameter": {
                        "name": "selector_position",
                        "validation": "16",
                    }
                },
                {"command_parameter": {"name": "pr_code", "validation": "45"}},
                {"command_parameter": {"name": "program_type", "validation": "D"}},
            ],
        }
    }
    wd_appliance_dry = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="WD_MODEL",
        serial_number="1234567890123456",
        purchase_date="2022-01-01",
        interface_type="RAPIDO",
        programs=[dry_prog],
        downloadable_programs=[],
        brand="candy",
        appliance_type="",
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step": "update_cloud_data"}
    )
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=wd_appliance_dry,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={"email": "user@example.com", "password": "pass"},
        )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "language"


async def test_config_flow_configure_local_exception(hass, no_discovery):
    """Test async_step_user when _configure_local raises unexpected exception (lines 780-781, 785)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.candy.config_flow.ConfigFlow._configure_local",
        side_effect=RuntimeError("Local socket failure"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_IP_ADDRESS: "192.168.0.66"}
        )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "detect_encryption"}


async def test_config_flow_cloud_washer_dryer_and_malformed_programs(
    hass, no_discovery, detect_no_encryption
):
    """Test cloud step with appliance_type washer_dryer and malformed programs (lines 951, 963-964)."""
    appliance = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="HBDOS695",
        serial_number="1234567890123456",
        purchase_date="2022-01-13",
        interface_type="3D_DUAL",
        programs=[{"invalid": "data"}],
        downloadable_programs=[],
        brand="candy",
        appliance_type="washer_dryer",
    )
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=appliance,
    ):
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
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "language"


async def test_config_flow_dryer_advances_to_checkup_when_supported(
    hass, no_discovery, detect_no_encryption
):
    """Test dryer advancing to checkup step when scheduled checkup is supported (line 992)."""
    dryer_appliance = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="CSOE",
        serial_number="1234567890123456",
        purchase_date="2022-01-13",
        interface_type="TD_DIGIT_6D",
        programs=[],
        downloadable_programs=[],
        brand="candy",
        appliance_type="dryer",
    )
    with (
        patch(
            "custom_components.candy.config_flow.CandyClient.status",
            new_callable=AsyncMock,
            return_value=TumbleDryerStatus(
                machine_state=MachineState.IDLE,
                program=0,
                program_state=DryerProgramState.STOPPED,
                cycle_state=DryerCycleState.LEVEL_NONE,
                remaining_minutes=0,
                remote_control=False,
                dry_level=0,
                dry_level_selected=0,
                refresh=False,
                need_clean_filter=False,
                water_tank_full=False,
                door_closed=True,
                error=None,
                delay_value=0,
                checkup_state=None,
                recipe_id=None,
                time=None,
                rapido=None,
            ),
        ),
        patch(
            "custom_components.candy.config_flow.fetch_appliance_data",
            new_callable=AsyncMock,
            return_value=dryer_appliance,
        ),
        patch(
            "custom_components.candy.config_flow.supports_scheduled_checkup",
            return_value=True,
        ),
    ):
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "checkup"


async def test_config_flow_dualtech_maintenance_without_checkup(
    hass, no_discovery, detect_no_encryption
):
    """Test DualTech appliance creates entry when maintenance enabled and can_checkup is False (line 1024)."""
    dualtech_appliance = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="testenckey",
        appliance_model="HBDOS695",
        serial_number="1234567890123456",
        purchase_date="2022-01-13",
        interface_type="3D_DUAL",
        programs=_MOCK_APPLIANCE.programs,
        downloadable_programs=[],
        brand="hoover",
        appliance_type="washer",
    )
    with (
        patch(
            "custom_components.candy.config_flow.fetch_appliance_data",
            new_callable=AsyncMock,
            return_value=dualtech_appliance,
        ),
        patch(
            "custom_components.candy.config_flow.supports_scheduled_checkup",
            return_value=False,
        ),
    ):
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )
        assert result["step_id"] == "maintenance"

        # Maintenance enabled with can_checkup=False creates entry directly (line 1024)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_MAINTENANCE_ENABLED: True}
        )
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_config_flow_maintenance_baselines_advance_to_checkup(
    hass, no_discovery, detect_no_encryption
):
    """Test ConfigFlow maintenance baselines submission advancing to checkup (line 1119)."""
    with patch(
        "custom_components.candy.config_flow.fetch_appliance_data",
        new_callable=AsyncMock,
        return_value=_MOCK_APPLIANCE,
    ):
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_KEY_PROGRAM_LANGUAGE: "en"}
        )
        assert result["step_id"] == "maintenance"

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
            result["flow_id"],
            user_input={CONF_KEY_WATER_HARDNESS: "2"},
        )
        assert result["step_id"] == "maintenance_baselines"

        # Submitting baselines advances to checkup (line 1119)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 100,
                CONF_KEY_MAINTENANCE_LAST_LIMESCALE: 100,
                CONF_KEY_MAINTENANCE_LAST_FILTER: 100,
            },
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "checkup"
