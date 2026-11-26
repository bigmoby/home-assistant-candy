from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo

from .client import is_legacy_dishwasher, is_modern_dishwasher, parse_wash_programs
from .client.dryer_commands import is_dualtech_dryer_interface
from .client.model import (
    _PROGRAM_NAMES,
    DishwasherProgram,
    DishwasherStatistics,
    DishwasherStatus,
    TumbleDryerStatus,
    WashingMachineStatistics,
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
    DEVICE_NAME_DISHWASHER,
    DEVICE_NAME_TUMBLE_DRYER,
    DEVICE_NAME_WASHER_DRYER,
    DEVICE_NAME_WASHING_MACHINE,
    DISHWASHER_PROGRAM_NAME_KEYS,
    DISHWASHER_PROGRAM_PANEL,
    DISHWASHER_PROGRAMS,
    DISHWASHER_TELEMETRY_TO_KEYS,
    DOMAIN,
    DRY_TARGET_TO_VALUE,
    DUALTECH_DRY_TARGET_TO_VALUE,
    DUALTECH_VALUE_TO_DRY_TARGET,
    MODE_FULL_CONTROL,
    SUGGESTED_AREA_BATHROOM,
    SUGGESTED_AREA_KITCHEN,
    UNIQUE_ID_DISHWASHER_TOTAL_CYCLES,
    UNIQUE_ID_WASH_TOTAL_CYCLES,
    VALUE_TO_DRY_TARGET,
)

_LOGGER = logging.getLogger(__name__)

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
        isinstance(data, (WashingMachineStatus, TumbleDryerStatus, DishwasherStatus))
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


def is_dishwasher_digit_or_smooth_interface(interface_type: str | None) -> bool:
    """Return True if the dishwasher interface uses the 8-level scale (0..7)."""
    if not interface_type:
        return False
    up = interface_type.upper()
    return "SMOOTH" in up or "DIGIT" in up


def dry_target_value_for_interface(target_name: str, interface_type: str | None) -> int:
    """Return numeric wire parameter value for drying target and interface type."""
    if is_dualtech(interface_type):
        return DUALTECH_DRY_TARGET_TO_VALUE.get(target_name, 0)
    return DRY_TARGET_TO_VALUE.get(target_name, 0)


def dry_target_label_for_interface(raw_code: int, interface_type: str | None) -> str:
    """Return drying target label string for raw telemetry code and interface type."""
    if is_dualtech(interface_type):
        return DUALTECH_VALUE_TO_DRY_TARGET.get(raw_code, "no_dry")
    return VALUE_TO_DRY_TARGET.get(raw_code, "no_dry")


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
    return not (
        is_tumble_dryer
        or is_modern_dishwasher(interface_type)
        or is_legacy_dishwasher(interface_type)
    )


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
    return _device_info(
        config_entry, wash_device_name(config_entry), SUGGESTED_AREA_BATHROOM
    )


def dishwasher_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    return _device_info(config_entry, DEVICE_NAME_DISHWASHER, SUGGESTED_AREA_KITCHEN)


def _device_info(
    config_entry: ConfigEntry, name: str, suggested_area: str
) -> DeviceInfo:
    brand = config_entry.data.get(CONF_KEY_BRAND, "candy")
    manufacturer = brand.capitalize() if brand else "Candy"
    info = DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=name,
        manufacturer=manufacturer,
        suggested_area=suggested_area,
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
    if appliance_type == "washer":
        prefix = "wash"
    elif appliance_type == "dryer":
        prefix = "dryer"
    elif appliance_type == "dishwasher":
        prefix = "dishwasher"
    else:
        raise ValueError(f"Unsupported appliance_type: {appliance_type}")
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


def get_dishwasher_error_notification_strings(
    error_code: int, language: str
) -> tuple[str, str] | None:
    """Return (title, message) for dishwasher error, or None if unknown code."""
    return get_appliance_error_notification_strings("dishwasher", error_code, language)


def get_dishwasher_checkup_result_strings(language: str) -> tuple[str, str]:
    """Return (title, message) for dishwasher full check-up result notification."""
    title = localized_notification_text(
        "dishwasher_full_checkup_result_title", language
    )
    message = localized_notification_text(
        "dishwasher_full_checkup_result_message", language
    )
    return title, message


def get_dishwasher_maintenance_strings(
    maint_type: str, language: str
) -> tuple[str, str]:
    """Return (title, message) for dishwasher maintenance notifications."""
    if maint_type == "filter":
        title = localized_notification_text("dishwasher_filter_title", language)
        message = localized_notification_text("dishwasher_filter_due_message", language)
    elif maint_type == "limescale":
        title = localized_notification_text("dishwasher_limescale_title", language)
        message = localized_notification_text(
            "dishwasher_limescale_due_message", language
        )
    elif maint_type == "checkup":
        title = localized_notification_text(
            "dishwasher_full_checkup_result_title", language
        )
        message = localized_notification_text("full_checkup_due_message", language)
    else:
        raise ValueError(f"Unsupported dishwasher maintenance type: {maint_type}")
    return title, message


def get_dishwasher_warning_strings(warning_type: str, language: str) -> tuple[str, str]:
    """Return (title, message) for dishwasher consumable warnings."""
    if warning_type == "salt":
        title = localized_notification_text("dishwasher_salt_empty_title", language)
        message = localized_notification_text("dishwasher_salt_empty_message", language)
    elif warning_type == "rinse":
        title = localized_notification_text("dishwasher_rinse_empty_title", language)
        message = localized_notification_text(
            "dishwasher_rinse_empty_message", language
        )
    else:
        raise ValueError(f"Unsupported dishwasher warning type: {warning_type}")
    return title, message


def resolve_dishwasher_program_name(
    program_identifier: str,
    language: str,
) -> str:
    """Resolve localized friendly program name for select key or hardware register."""
    if not program_identifier:
        return ""
    # 1. Match select option key (e.g. eco_45)
    name_key = DISHWASHER_PROGRAM_NAME_KEYS.get(program_identifier)
    if name_key is not None:
        trans = _PROGRAM_NAMES.get(name_key, {})
        resolved = _lookup_translation(trans, language)
        if resolved:
            return resolved

    # 2. Match hardware telemetry register (e.g. P8, P2, P1+)
    telemetry_match = DISHWASHER_TELEMETRY_TO_KEYS.get(program_identifier)
    if telemetry_match is not None:
        trans = _PROGRAM_NAMES.get(telemetry_match[0], {})
        resolved = _lookup_translation(trans, language)
        if resolved:
            return resolved

    # 3. Fallback to raw program identifier
    return program_identifier


def resolve_dishwasher_program_description(
    program_identifier: str,
    language: str,
) -> str | None:
    """Resolve localized multi-line description for select key or hardware register."""
    if not program_identifier:
        return None
    # 1. Match select option key (e.g. eco_45)
    name_key = DISHWASHER_PROGRAM_NAME_KEYS.get(program_identifier)
    if name_key is not None:
        desc_key = f"{name_key}_DESCRIPTION"
        trans = _PROGRAM_NAMES.get(desc_key, {})
        return _lookup_translation(trans, language)

    # 2. Match hardware telemetry register (e.g. P8, P2, P1+)
    telemetry_match = DISHWASHER_TELEMETRY_TO_KEYS.get(program_identifier)
    if telemetry_match is not None:
        trans = _PROGRAM_NAMES.get(telemetry_match[1], {})
        return _lookup_translation(trans, language)

    # 3. Direct description key or candidate keys
    for candidate_key in (
        f"{program_identifier}_DESCRIPTION",
        f"DW_{program_identifier}_DESCRIPTION",
    ):
        trans = _PROGRAM_NAMES.get(candidate_key, {})
        resolved = _lookup_translation(trans, language)
        if resolved:
            return resolved

    # 4. Search _PROGRAM_NAMES for program whose localized name matches program_identifier
    for k, v in _PROGRAM_NAMES.items():
        if not k.endswith("_DESCRIPTION") and isinstance(v, dict):
            if any(name == program_identifier for name in v.values()):
                desc_trans = _PROGRAM_NAMES.get(f"{k}_DESCRIPTION", {})
                resolved = _lookup_translation(desc_trans, language)
                if resolved:
                    return resolved

    return None


def _lookup_translation(
    translations: dict[str, str],
    language: str,
) -> str | None:
    if not translations:
        return None
    lang_lower = language.lower()
    if lang_lower in translations:
        return translations[lang_lower]
    if "en" in translations:
        return translations["en"]
    return next(iter(translations.values()), None)


def find_dishwasher_program(
    programs: list[DishwasherProgram],
    program_identifier: str,
    language: str,
) -> DishwasherProgram | None:
    """Find a DishwasherProgram matching an option name, translation key, register code, or cycle id."""
    if not program_identifier or program_identifier == DISHWASHER_PROGRAM_PANEL:
        return None
    for p in programs:
        if (
            p.localized_name(language) == program_identifier
            or p.name == program_identifier
            or (
                program_identifier in DISHWASHER_PROGRAMS
                and f"P{p.cycle_id}" == DISHWASHER_PROGRAMS[program_identifier]
            )
            or f"P{p.cycle_id}" == program_identifier
            or str(p.cycle_id) == program_identifier.lstrip("P").rstrip("+-")
        ):
            return p
    return None


def restore_last_known_statistics(
    hass: HomeAssistant,
    config_entry_id: str,
    is_dishwasher: bool,
) -> WashingMachineStatistics | DishwasherStatistics | None:
    """Read the persisted total-cycles value from HA's state machine.

    Returns a WashingMachineStatistics or DishwasherStatistics populated from the
    last known sensor state, or None if the entity was never registered or its state
    is not a valid integer.
    """
    registry = er.async_get(hass)
    unique_id = (
        UNIQUE_ID_DISHWASHER_TOTAL_CYCLES.format(config_entry_id)
        if is_dishwasher
        else UNIQUE_ID_WASH_TOTAL_CYCLES.format(config_entry_id)
    )
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    if state is None or not state.state.isdigit():
        return None
    _LOGGER.debug(
        "Restored total_cycles from HA state machine: %s = %s",
        entity_id,
        state.state,
    )
    if is_dishwasher:
        return DishwasherStatistics(total_cycles=int(state.state))
    return WashingMachineStatistics(total_cycles=int(state.state))
