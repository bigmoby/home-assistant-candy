"""Device trigger platform for Candy washing machines."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import voluptuous as vol

from .client.model import (
    MachineState,
    TumbleDryerStatus,
    WashingMachineStatistics,
    WashingMachineStatus,
)
from .const import (
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
    MAINTENANCE_FILTER_THRESHOLD,
    MAINTENANCE_FULL_CHECKUP_THRESHOLD,
    MAINTENANCE_HARDNESS_THRESHOLDS,
)
from .helpers import cycles_remaining

TRIGGER_TYPES = frozenset(
    {
        "washing_started",
        "washing_completed",
        "drying_started",
        "drying_completed",
        "clean_filter_needed",
        "water_tank_full",
        "error_reported",
        "maintenance_full_checkup_due",
        "maintenance_limescale_due",
        "maintenance_filter_due",
    }
)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES)}
)

_FINISHED_STATES = frozenset({MachineState.FINISHED1, MachineState.FINISHED2})


def _config_entry_id_for_device(hass: HomeAssistant, device_id: str) -> str | None:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    if hasattr(device, "config_entry_id"):
        entry_id = device.config_entry_id
        if entry_id is not None:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN:
                return entry_id
        return None
    for eid in getattr(device, "config_entries", ()):
        entry = hass.config_entries.async_get_entry(eid)
        if entry is not None and entry.domain == DOMAIN:
            return eid
    return None


async def async_get_triggers(
    hass: HomeAssistant, device_id: str | None = None
) -> list[dict[str, Any]]:
    """Return device triggers available for this Candy device.

    Called with device_id by the device automation system, or without device_id
    by HA's trigger platform registration (in which case we have no general types).
    """
    if device_id is None:
        return []
    config_entry_id = _config_entry_id_for_device(hass, device_id)
    if config_entry_id is None:
        return []

    entry = hass.config_entries.async_get_entry(config_entry_id)
    if entry is None:
        return []

    coordinator = (
        hass.data.get(DOMAIN, {}).get(config_entry_id, {}).get(DATA_KEY_COORDINATOR)
    )
    if coordinator is None or not isinstance(
        coordinator.data, (WashingMachineStatus, TumbleDryerStatus)
    ):
        return []

    base: dict[str, Any] = {
        CONF_PLATFORM: "device",
        CONF_DOMAIN: DOMAIN,
        CONF_DEVICE_ID: device_id,
    }

    if isinstance(coordinator.data, TumbleDryerStatus):
        return [
            {**base, CONF_TYPE: "drying_started"},
            {**base, CONF_TYPE: "drying_completed"},
            {**base, CONF_TYPE: "clean_filter_needed"},
            {**base, CONF_TYPE: "water_tank_full"},
            {**base, CONF_TYPE: "error_reported"},
        ]

    triggers = [
        {**base, CONF_TYPE: "washing_started"},
        {**base, CONF_TYPE: "washing_completed"},
        {**base, CONF_TYPE: "error_reported"},
    ]

    if entry.data.get(CONF_KEY_MAINTENANCE_ENABLED):
        triggers.append({**base, CONF_TYPE: "maintenance_full_checkup_due"})
        if entry.data.get(CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True):
            triggers.append({**base, CONF_TYPE: "maintenance_limescale_due"})
        if entry.data.get(CONF_KEY_MAINTENANCE_FILTER_ENABLED, True):
            triggers.append({**base, CONF_TYPE: "maintenance_filter_due"})

    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: Any,
    trigger_info: dict[str, Any],
) -> CALLBACK_TYPE:
    """Attach a trigger and return an unsubscribe callable."""
    trigger_type: str = config[CONF_TYPE]
    device_id: str = config[CONF_DEVICE_ID]

    config_entry_id = _config_entry_id_for_device(hass, device_id)
    if config_entry_id is None:
        return lambda: None

    entry = hass.config_entries.async_get_entry(config_entry_id)
    if entry is None:
        return lambda: None

    domain_data = hass.data.get(DOMAIN, {}).get(config_entry_id, {})
    coordinator: DataUpdateCoordinator[Any] | None = domain_data.get(
        DATA_KEY_COORDINATOR
    )
    if coordinator is None:
        return lambda: None

    trigger_variables = {
        **trigger_info.get("trigger_data", {}),
        CONF_PLATFORM: "device",
        CONF_DOMAIN: DOMAIN,
        CONF_TYPE: trigger_type,
    }
    job = HassJob(action, f"candy device trigger {trigger_type}")

    @callback
    def _fire() -> None:
        hass.async_run_hass_job(job, {"trigger": trigger_variables})

    if trigger_type in {
        "washing_started",
        "washing_completed",
        "drying_started",
        "drying_completed",
        "error_reported",
    }:
        return _attach_state_trigger(
            hass, coordinator, trigger_type, trigger_variables, job
        )

    if trigger_type in {"clean_filter_needed", "water_tank_full"}:
        return _attach_dryer_warning_trigger(coordinator, trigger_type, _fire)

    stats_coordinator: DataUpdateCoordinator[Any] | None = domain_data.get(
        DATA_KEY_STATS_COORDINATOR
    )
    if stats_coordinator is None:
        return lambda: None

    return _attach_maintenance_trigger(stats_coordinator, entry, trigger_type, _fire)


def _attach_state_trigger(
    hass: HomeAssistant,
    coordinator: DataUpdateCoordinator[Any],
    trigger_type: str,
    trigger_variables: dict[str, Any],
    job: HassJob,
) -> CALLBACK_TYPE:
    initial = cast(WashingMachineStatus | TumbleDryerStatus | None, coordinator.data)
    prev_state: list[MachineState | None] = [
        initial.machine_state if initial is not None else None
    ]

    @callback
    def _on_update() -> None:
        status = cast(WashingMachineStatus | TumbleDryerStatus | None, coordinator.data)
        if status is None:
            return
        curr = status.machine_state
        prev = prev_state[0]
        prev_state[0] = curr

        if trigger_type in {"washing_started", "drying_started"}:
            should_fire = curr == MachineState.RUNNING and prev not in {
                MachineState.RUNNING,
                MachineState.PAUSED,
            }
        elif trigger_type in {"washing_completed", "drying_completed"}:
            should_fire = curr in _FINISHED_STATES and prev not in _FINISHED_STATES
        else:  # error_reported
            should_fire = curr == MachineState.ERROR and prev != MachineState.ERROR

        if should_fire:
            hass.async_run_hass_job(job, {"trigger": trigger_variables})

    return coordinator.async_add_listener(_on_update)


def _attach_dryer_warning_trigger(
    coordinator: DataUpdateCoordinator[Any],
    trigger_type: str,
    fire: Callable[[], None],
) -> CALLBACK_TYPE:
    initial = cast(TumbleDryerStatus | None, coordinator.data)
    initial_val = False
    if initial is not None:
        if trigger_type == "clean_filter_needed":
            initial_val = initial.need_clean_filter
        else:
            initial_val = initial.water_tank_full

    prev_val: list[bool] = [initial_val]

    @callback
    def _on_update() -> None:
        status = cast(TumbleDryerStatus | None, coordinator.data)
        if status is None:
            return
        if trigger_type == "clean_filter_needed":
            curr = status.need_clean_filter
        else:
            curr = status.water_tank_full
        prev = prev_val[0]
        prev_val[0] = curr

        if curr and not prev:
            fire()

    return coordinator.async_add_listener(_on_update)


def _attach_maintenance_trigger(
    stats_coordinator: DataUpdateCoordinator[Any],
    config_entry: ConfigEntry,
    trigger_type: str,
    fire: Callable[[], None],
) -> CALLBACK_TYPE:
    hardness = config_entry.data.get(CONF_KEY_WATER_HARDNESS, 2)
    threshold_by_type = {
        "maintenance_full_checkup_due": MAINTENANCE_FULL_CHECKUP_THRESHOLD,
        "maintenance_limescale_due": MAINTENANCE_HARDNESS_THRESHOLDS[hardness],
        "maintenance_filter_due": MAINTENANCE_FILTER_THRESHOLD,
    }
    last_key_by_type = {
        "maintenance_full_checkup_due": CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
        "maintenance_limescale_due": CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
        "maintenance_filter_due": CONF_KEY_MAINTENANCE_LAST_FILTER,
    }
    last_key = last_key_by_type[trigger_type]
    threshold = threshold_by_type[trigger_type]

    def _current_remaining() -> int | None:
        stats = cast(WashingMachineStatistics | None, stats_coordinator.data)
        if stats is None:
            return None
        # Re-read last from config_entry.data so counter resets are reflected
        last = config_entry.data.get(last_key, 0)
        return cycles_remaining(stats.total_cycles, last, threshold)

    initial_stats = cast(WashingMachineStatistics | None, stats_coordinator.data)
    prev_remaining: list[int | None] = [
        _current_remaining() if initial_stats is not None else None
    ]

    @callback
    def _on_stats_update() -> None:
        curr = _current_remaining()
        prev = prev_remaining[0]
        prev_remaining[0] = curr
        if curr == 0 and prev != 0:
            fire()

    return stats_coordinator.async_add_listener(_on_stats_update)
