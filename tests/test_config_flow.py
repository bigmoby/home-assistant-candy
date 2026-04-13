from unittest.mock import AsyncMock, patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
import pytest

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client import Encryption
from custom_components.candy.config_flow import MANUAL_IP_OPTION

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bypass_setup_fixture():  # noqa: PT004
    """Prevent setup."""
    with patch(
        "custom_components.candy.async_setup_entry",
        return_value=True,
    ):
        yield


@pytest.fixture(name="no_discovery")
def _no_discovery_fixture():  # noqa: PT004
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
def _detect_no_encryption_fixture():  # noqa: PT004
    with patch(
        "custom_components.candy.config_flow.detect_encryption",
        return_value=(Encryption.NO_ENCRYPTION, None),
    ):
        yield


@pytest.fixture(name="detect_encryption_find_key", autouse=False)
def _detect_encryption_find_key_fixture():  # noqa: PT004
    with patch(
        "custom_components.candy.config_flow.detect_encryption",
        return_value=(Encryption.ENCRYPTION, "testkey"),
    ):
        yield


@pytest.fixture(name="detect_encryption_key_not_found", autouse=False)
def _detect_encryption_key_not_found_fixture():  # noqa: PT004
    with patch(
        "custom_components.candy.config_flow.detect_encryption", side_effect=ValueError
    ):
        yield


@pytest.fixture(name="detect_encryption_without_key", autouse=False)
def _detect_encryption_without_key_fixture():  # noqa: PT004
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

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Candy"
    assert result["data"] == {
        CONF_IP_ADDRESS: "192.168.0.66",
        CONF_KEY_USE_ENCRYPTION: False,
    }
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

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Candy"
    assert result["data"] == {
        CONF_IP_ADDRESS: "192.168.0.66",
        CONF_KEY_USE_ENCRYPTION: True,
        CONF_PASSWORD: "testkey",
    }
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

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Candy"
    assert result["data"] == {
        CONF_IP_ADDRESS: "192.168.0.66",
        CONF_KEY_USE_ENCRYPTION: True,
        CONF_PASSWORD: "",
    }
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
    """Test selecting a discovered device creates the entry correctly."""
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

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IP_ADDRESS] == "192.168.1.79"
    assert result["data"][CONF_KEY_USE_ENCRYPTION] is False


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
