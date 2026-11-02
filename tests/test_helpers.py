from unittest.mock import MagicMock

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy import CONF_KEY_USE_ENCRYPTION
from custom_components.candy.const import (
    CONF_KEY_BRAND,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_PURCHASE_DATE,
    CONF_KEY_SERIAL_NUMBER,
    DOMAIN,
    MODE_FULL_CONTROL,
)
from custom_components.candy.helpers import (
    command_settling_delay,
    cycles_remaining,
    dryer_device_info,
    get_appliance_error_notification_strings,
    get_dryer_error_notification_strings,
    get_wash_error_notification_strings,
    is_dualtech,
    is_washer_dryer,
    remote_control_enabled,
    supports_autodose,
    supports_remote_pause,
    supports_scheduled_checkup,
    wash_device_info,
    wash_device_name,
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


def test_wash_device_info_washer_dryer_hoover():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: "192.168.0.1",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_BRAND: "hoover",
            CONF_KEY_IS_WASHER_DRYER: True,
        },
    )
    assert wash_device_name(entry) == "Washer dryer"
    info = wash_device_info(entry)
    assert info["name"] == "Washer dryer"
    assert info["manufacturer"] == "Hoover"


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

    # E12: Drying system fault
    e12_result = get_wash_error_notification_strings(12, "en")
    assert e12_result is not None
    e12_title, e12_message = e12_result
    assert e12_title == "Washing machine error: E12"
    assert e12_message.startswith("E12-Troubles with the drying system")

    # Unknown error code returns None
    assert get_wash_error_notification_strings(99, "en") is None


def test_get_dryer_error_notification_strings():
    # English
    en_result = get_dryer_error_notification_strings(3, "en")
    assert en_result is not None
    title, message = en_result
    assert title == "Tumble dryer error: E03"
    assert message.startswith("E03 -  The water tank is full\n\n")

    # Italian
    it_result = get_dryer_error_notification_strings(3, "it")
    assert it_result is not None
    title, message = it_result
    assert title == "Errore asciugatrice: E03"
    assert message.startswith("E03 -  Tanica raccolta acqua piena\n\n")

    # Fallback to English for unknown language
    fallback_result = get_dryer_error_notification_strings(3, "unknown_lang")
    assert fallback_result is not None
    title, message = fallback_result
    assert title == "Tumble dryer error: E03"
    assert message.startswith("E03 -  The water tank is full\n\n")

    # Unknown error code returns None
    assert get_dryer_error_notification_strings(99, "en") is None

    # Unified function
    unified_wash = get_appliance_error_notification_strings("washer", 2, "en")
    assert unified_wash is not None
    assert unified_wash[0] == "Washing machine error: E02"
    unified_dryer = get_appliance_error_notification_strings("dryer", 3, "en")
    assert unified_dryer is not None
    assert unified_dryer[0] == "Tumble dryer error: E03"


def test_is_washer_dryer_from_config():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_KEY_IS_WASHER_DRYER: True,
        },
    )
    assert is_washer_dryer(entry, None) is True


def test_is_washer_dryer_from_programs_list():
    entry = MockConfigEntry(domain=DOMAIN, data={})
    wash_prog = MagicMock(is_dry=False)
    dry_prog = MagicMock(is_dry=True)
    assert is_washer_dryer(entry, [wash_prog]) is False
    assert is_washer_dryer(entry, [wash_prog, dry_prog]) is True


def test_is_washer_dryer_from_entry_programs():
    dry_prog_dict = {
        "program": {
            "position": 1,
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
    wash_prog_dict = {
        "program": {
            "position": 2,
            "name": "COTTON",
            "command_parameters": [
                {"command_parameter": {"name": "selector_position", "validation": "1"}},
                {"command_parameter": {"name": "pr_code", "validation": "1"}},
                {"command_parameter": {"name": "program_type", "validation": "W"}},
            ],
        }
    }
    entry_wd = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_KEY_PROGRAMS: [wash_prog_dict, dry_prog_dict]},
    )
    assert is_washer_dryer(entry_wd, None) is True

    entry_wm = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_KEY_PROGRAMS: [wash_prog_dict]},
    )
    assert is_washer_dryer(entry_wm, None) is False

    entry_empty = MockConfigEntry(domain=DOMAIN, data={})
    assert is_washer_dryer(entry_empty, None) is False


@pytest.mark.parametrize(
    ("interface_type", "expected"),
    [
        ("3D_DUAL", True),
        ("3d_dual_bi", True),
        ("3D_DUAL_TOP", True),
        ("3D_DUAL_KPAD", True),
        ("3D_DUAL_KPAD_TOP", True),
        ("dual_simple", True),
        ("RAPIDO_4DIG_STM_NEL", False),
        ("BIANCA_SOME_MODEL", False),
        ("", False),
        (None, False),
    ],
)
def test_is_dualtech(interface_type: str | None, expected: bool) -> None:
    assert is_dualtech(interface_type) is expected


@pytest.mark.parametrize(
    ("interface_type", "expected"),
    [
        ("RAPIDO_4DIG_STM_NEL", True),
        ("SMART_PRO", True),
        ("", True),
        (None, True),
        ("BIANCA_TOUCH", False),
        ("bianca_classic", False),
        ("3D_DUAL", False),
        ("3D_DUAL_BI", False),
    ],
)
def test_supports_remote_pause(interface_type: str | None, expected: bool) -> None:
    assert supports_remote_pause(interface_type) is expected


@pytest.mark.parametrize(
    ("interface_type", "is_tumble_dryer", "expected"),
    [
        ("TD_DIGIT_HP_DOOR", True, False),
        ("TD_LED_SOME", True, False),
        ("3D_DUAL", True, False),
        ("RAPIDO", True, False),
        ("RAPIDO_4DIG_STM_NEL", False, True),
        ("BIANCA_TOUCH", False, True),
        ("3D_DUAL", False, True),
        (None, False, True),
    ],
)
def test_supports_scheduled_checkup(
    interface_type: str | None, is_tumble_dryer: bool, expected: bool
) -> None:
    assert supports_scheduled_checkup(interface_type, is_tumble_dryer) is expected


@pytest.mark.parametrize(
    ("interface_type", "expected"),
    [
        (None, 5),
        ("", 5),
        ("3D_DUAL", 15),
        ("3D_DUAL_BI", 15),
        ("dual_simple", 15),
        ("TD_DIGIT_HP_DOOR", 15),
        ("TD_LED_SOME", 15),
        ("RAPIDO_4DIG_STM_NEL", 5),
        ("BIANCA_TOUCH", 5),
        ("SMART_PRO", 5),
    ],
)
def test_command_settling_delay(interface_type: str | None, expected: int) -> None:
    assert command_settling_delay(interface_type) == expected


def test_dryer_device_info():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_IP_ADDRESS: "192.168.0.2",
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_BRAND: "hoover",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_MAC_ADDRESS: "11:22:33:44:55:66",
            CONF_KEY_DEVICE_MODEL: "DXOH9A2TCE",
            CONF_KEY_SERIAL_NUMBER: "SN999888",
        },
    )
    info = dryer_device_info(entry)
    assert info["name"] == "Tumble dryer"
    assert info["manufacturer"] == "Hoover"
    assert (dr.CONNECTION_NETWORK_MAC, "11:22:33:44:55:66") in info["connections"]
    assert info["model"] == "DXOH9A2TCE"
    assert info["serial_number"] == "SN999888"


def test_dryer_device_info_default_brand():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_KEY_BRAND: ""},
    )
    info = dryer_device_info(entry)
    assert info["manufacturer"] == "Candy"


def test_remote_control_enabled():
    mock_wm = MagicMock()
    mock_wm.remote_control = True
    # Non-status object
    assert remote_control_enabled("not_a_status") is False
    assert remote_control_enabled(None) is False


def test_supports_autodose():
    assert supports_autodose(None) is False
    assert supports_autodose("") is False
    assert supports_autodose("RAPIDO_4DIG_STM_AD_NEL") is True
    assert supports_autodose("RAPIDO_4DIG_STM_NEL") is False


def test_is_washer_dryer_corrupt_programs():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_KEY_PROGRAMS: [{"invalid": "format"}]},
    )
    assert is_washer_dryer(entry, None) is False
