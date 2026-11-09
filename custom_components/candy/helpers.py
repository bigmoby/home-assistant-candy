from __future__ import annotations

import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo

from .client import parse_wash_programs
from .client.dryer_commands import is_dualtech_dryer_interface
from .client.model import (
    TumbleDryerStatus,
    WashingMachineStatus,
    WashingMachineWashProgram,
)
from .const import (
    CONF_KEY_APPLIANCE_TYPE,
    CONF_KEY_BRAND,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_SERIAL_NUMBER,
    DEVICE_NAME_TUMBLE_DRYER,
    DEVICE_NAME_WASHER_DRYER,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    MODE_FULL_CONTROL,
    SUGGESTED_AREA_BATHROOM,
)

_NOTIFICATION_STRINGS: dict[str, dict[str, str]] = json.loads(
    (Path(__file__).parent / "client" / "notification_strings.json").read_text(
        encoding="utf-8"
    )
)


def localized_notification_text(key: str, language: str) -> str:
    """Return the notification string for key, falling back to English."""
    translations = _NOTIFICATION_STRINGS[key]
    return translations.get(language, translations["en"])


def remote_control_enabled(data: object) -> bool:
    """Return True when the appliance accepts remote commands."""
    return (
        isinstance(data, (WashingMachineStatus, TumbleDryerStatus))
        and data.remote_control
    )


def is_dualtech(interface_type: str | None) -> bool:
    """Return True if the interface_type belongs to the DualTech appliance family."""
    if not interface_type:
        return False
    return "DUAL" in interface_type.upper()


def is_dualtech_dryer(interface_type: str | None) -> bool:
    """Return True if the interface_type belongs to a DualTech tumble dryer."""
    return is_dualtech_dryer_interface(interface_type)


def command_settling_delay(interface_type: str | None) -> int:
    """Return the post-command settling delay in seconds for the interface type."""
    if not interface_type:
        return 5
    if is_dualtech(interface_type) or is_dualtech_dryer(interface_type):
        return 15
    return 5


def supports_remote_pause(interface_type: str | None) -> bool:
    """Return True if the appliance interface supports remote pause/resume."""
    if not interface_type:
        return True
    return not (
        interface_type.upper().startswith("BIANCA") or is_dualtech(interface_type)
    )


def supports_autodose(interface_type: str | None) -> bool:
    """Return True if the appliance interface supports autodose."""
    if not interface_type:
        return False
    return "_AD" in interface_type.upper()


def supports_scheduled_checkup(
    interface_type: str | None,
    is_tumble_dryer: bool,
) -> bool:
    """Return True if the appliance supports running automatic background check-up during cycles."""
    return not is_tumble_dryer


def cycles_remaining(total: int, last_reset: int, threshold: int) -> int:
    """Return cycles until next maintenance alert, or 0 when due (including overdue).

    Returns 0 for any elapsed >= threshold so notifications fire on every wash
    until the user manually resets the counter.
    """
    elapsed = total - last_reset
    if elapsed <= 0:
        return threshold
    if elapsed >= threshold:
        return 0
    return threshold - elapsed


def is_washer_dryer(
    config_entry: ConfigEntry,
    programs: list[WashingMachineWashProgram] | None,
) -> bool:
    """Return True if the config entry represents a washer-dryer appliance."""
    if config_entry.data.get(CONF_KEY_IS_WASHER_DRYER, False):
        return True
    if config_entry.data.get(CONF_KEY_APPLIANCE_TYPE) == "washer_dryer":
        return True
    if programs is not None:
        return any(
            p.program_type in ("D", "WD") or p.selector_position_dry is not None
            for p in programs
        )
    raw_programs = config_entry.data.get(CONF_KEY_PROGRAMS, [])
    if raw_programs:
        try:
            return any(
                p.program_type in ("D", "WD") or p.selector_position_dry is not None
                for p in parse_wash_programs(raw_programs)
            )
        except (KeyError, TypeError, ValueError):
            return False
    return False


def wash_device_name(config_entry: ConfigEntry) -> str:
    if is_washer_dryer(config_entry, None):
        return DEVICE_NAME_WASHER_DRYER
    return DEVICE_NAME_WASHING_MACHINE


def wash_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    brand = config_entry.data.get(CONF_KEY_BRAND, "candy")
    manufacturer = brand.capitalize() if brand else "Candy"
    info = DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=wash_device_name(config_entry),
        manufacturer=manufacturer,
        suggested_area=SUGGESTED_AREA_BATHROOM,
    )
    if config_entry.data.get(CONF_KEY_MAC_ADDRESS):
        info["connections"] = {
            (
                dr.CONNECTION_NETWORK_MAC,
                config_entry.data[CONF_KEY_MAC_ADDRESS],
            )
        }
    if config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL:
        if config_entry.data.get(CONF_KEY_DEVICE_MODEL):
            info["model"] = config_entry.data[CONF_KEY_DEVICE_MODEL]
        if config_entry.data.get(CONF_KEY_SERIAL_NUMBER):
            info["serial_number"] = config_entry.data[CONF_KEY_SERIAL_NUMBER]
    return info


def dryer_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    brand = config_entry.data.get(CONF_KEY_BRAND, "candy")
    manufacturer = brand.capitalize() if brand else "Candy"
    info = DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=DEVICE_NAME_TUMBLE_DRYER,
        manufacturer=manufacturer,
        suggested_area=SUGGESTED_AREA_BATHROOM,
    )
    if config_entry.data.get(CONF_KEY_MAC_ADDRESS):
        info["connections"] = {
            (
                dr.CONNECTION_NETWORK_MAC,
                config_entry.data[CONF_KEY_MAC_ADDRESS],
            )
        }
    if config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL:
        if config_entry.data.get(CONF_KEY_DEVICE_MODEL):
            info["model"] = config_entry.data[CONF_KEY_DEVICE_MODEL]
        if config_entry.data.get(CONF_KEY_SERIAL_NUMBER):
            info["serial_number"] = config_entry.data[CONF_KEY_SERIAL_NUMBER]
    return info


def get_appliance_error_notification_strings(
    appliance_type: str, error_code: int, language: str
) -> tuple[str, str] | None:
    """Return (title, message) for appliance error, or None if unknown code."""
    prefix = "wash" if appliance_type == "washer" else "dryer"
    msg_key = f"{prefix}_error_{error_code}_message"
    if msg_key not in _NOTIFICATION_STRINGS:
        return None
    base_title = localized_notification_text(f"{prefix}_error_title", language)
    title = f"{base_title}: E{error_code:02d}"
    message = localized_notification_text(msg_key, language)
    return title, message


def get_wash_error_notification_strings(
    error_code: int, language: str
) -> tuple[str, str] | None:
    """Return (title, message) for washing machine error, or None if unknown code."""
    return get_appliance_error_notification_strings("washer", error_code, language)


def get_dryer_error_notification_strings(
    error_code: int, language: str
) -> tuple[str, str] | None:
    """Return (title, message) for tumble dryer error, or None if unknown code."""
    return get_appliance_error_notification_strings("dryer", error_code, language)
