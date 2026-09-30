from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy import CONF_KEY_USE_ENCRYPTION
from custom_components.candy.const import (
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PURCHASE_DATE,
    CONF_KEY_SERIAL_NUMBER,
    DOMAIN,
    MODE_FULL_CONTROL,
)
from custom_components.candy.helpers import (
    cycles_remaining,
    get_wash_error_notification_strings,
    wash_device_info,
)


@pytest.mark.parametrize(
    ("total", "last_reset", "threshold", "expected"),
    [
        # Just reset — full threshold remaining
        (100, 100, 100, 100),
        # Partway through — counts down normally
        (110, 100, 100, 90),
        (150, 100, 100, 50),
        (199, 100, 100, 1),
        # Exactly at threshold — due
        (200, 100, 100, 0),
        # Overdue by 1 — still 0 (not 99)
        (201, 100, 100, 0),
        # Overdue by a full extra threshold — still 0
        (300, 100, 100, 0),
        # Overdue by more — still 0
        (500, 100, 100, 0),
        # Negative elapsed (last_reset > total, e.g. after manual reset past current count)
        (50, 100, 100, 100),
        # Zero elapsed
        (100, 100, 50, 50),
        # Different threshold
        (85, 0, 85, 0),
        (84, 0, 85, 1),
        (86, 0, 85, 0),
    ],
)
def test_cycles_remaining(total, last_reset, threshold, expected):
    assert cycles_remaining(total, last_reset, threshold) == expected


def test_wash_device_info_with_mac_address():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: "192.168.0.1",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
        },
    )
    info = wash_device_info(entry)
    assert "connections" in info
    assert (dr.CONNECTION_NETWORK_MAC, "AA:BB:CC:DD:EE:FF") in info["connections"]


def test_wash_device_info_full_control():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: "192.168.0.1",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_DEVICE_MODEL: "RO41274DWMSE",
            CONF_KEY_SERIAL_NUMBER: "SN123456",
            CONF_KEY_PURCHASE_DATE: "2024-01-15",
        },
    )
    info = wash_device_info(entry)
    assert info["model"] == "RO41274DWMSE"
    assert info["serial_number"] == "SN123456"
    assert "hw_version" not in info


def test_get_wash_error_notification_strings():
    # English
    en_result = get_wash_error_notification_strings(2, "en")
    assert en_result is not None
    title, message = en_result
    assert title == "Washing machine error: E02"
    assert message.startswith("E02-Troubles with loading water\n\n")

    # Italian
    it_result = get_wash_error_notification_strings(2, "it")
    assert it_result is not None
    title, message = it_result
    assert title == "Errore lavatrice: E02"
    assert message.startswith("E02-Problema di carico acqua\n\n")

    # Fallback to English for unknown language
    fallback_result = get_wash_error_notification_strings(2, "unknown_lang")
    assert fallback_result is not None
    title, message = fallback_result
    assert title == "Washing machine error: E02"
    assert message.startswith("E02-Troubles with loading water\n\n")

    # Unknown error code returns None
    assert get_wash_error_notification_strings(99, "en") is None
