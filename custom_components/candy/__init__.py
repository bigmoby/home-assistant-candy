"""The Candy integration."""

from __future__ import annotations

from collections.abc import Callable
import copy
from datetime import timedelta
import logging
from typing import Union

import aiohttp
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CandyClient
from .client.model import (
    DishwasherState,
    DishwasherStatus,
    DryerCycleState,
    DryerProgramState,
    MachineState,
    OvenState,
    OvenStatus,
    TumbleDryerStatus,
    WashingMachineStatus,
    WashProgramState,
)
from .const import (
    CONF_KEY_USE_ENCRYPTION,
    DATA_KEY_COORDINATOR,
    DOMAIN,
    PLATFORMS,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_OVEN,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_WASHING_MACHINE,
)

_LOGGER = logging.getLogger(__name__)

# Machine states that strongly suggest the user powered off the device intentionally.
# In these cases, a timeout is treated as "Off" rather than "unavailable".
_OFF_INFERRED_STATES = {
    MachineState.FINISHED1,
    MachineState.FINISHED2,
    MachineState.IDLE,
}


def _make_off_status(
    last_status: Union[
        WashingMachineStatus, TumbleDryerStatus, DishwasherStatus, OvenStatus
    ],
) -> Union[WashingMachineStatus, TumbleDryerStatus, DishwasherStatus, OvenStatus]:
    """Return a copy of last_status with machine_state set to OFF (or equivalent).

    This synthetic status allows sensors to display "Off" when the device is
    unreachable but was last seen in a Finished or Idle state.
    """
    off_status: Union[
        WashingMachineStatus, TumbleDryerStatus, DishwasherStatus, OvenStatus
    ]
    if isinstance(last_status, DishwasherStatus):
        # Dishwasher uses its own DishwasherState enum — use IDLE as the "Off" equivalent
        off_status = copy.copy(last_status)
        off_status.machine_state = DishwasherState.IDLE
        off_status.remaining_minutes = 0
    elif isinstance(last_status, OvenStatus):
        off_status = copy.copy(last_status)
        off_status.machine_state = OvenState.IDLE
    else:
        # WashingMachineStatus and TumbleDryerStatus both use MachineState
        off_status = copy.copy(last_status)
        off_status.machine_state = MachineState.OFF
    return off_status


def _restore_last_known_status(
    hass: HomeAssistant,
    config_entry_id: str,
) -> Union[WashingMachineStatus, TumbleDryerStatus, DishwasherStatus, OvenStatus, None]:
    """Try to reconstruct the last known device status from HA's entity registry and state machine.

    HA restores entity states from the recorder database on startup, so even before
    the integration successfully polls the device, we can read the last persisted state.
    This allows the integration to load gracefully when the device is offline at startup.

    Returns a minimal synthetic "Off" status object if restoration succeeds, else None.
    """
    registry = er.async_get(hass)

    # Map each "main" unique_id to a factory for a synthetic offline status
    StatusFactory = Callable[
        [],
        Union[WashingMachineStatus, TumbleDryerStatus, DishwasherStatus, OvenStatus],
    ]
    candidates: list[tuple[str, StatusFactory]] = [
        (UNIQUE_ID_WASHING_MACHINE.format(config_entry_id), _offline_washing_machine),
        (UNIQUE_ID_TUMBLE_DRYER.format(config_entry_id), _offline_tumble_dryer),
        (UNIQUE_ID_DISHWASHER.format(config_entry_id), _offline_dishwasher),
        (UNIQUE_ID_OVEN.format(config_entry_id), _offline_oven),
    ]

    for unique_id, factory in candidates:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id is not None:
            state = hass.states.get(entity_id)
            _LOGGER.debug(
                "Restored entity %s last state: %s",
                entity_id,
                state.state if state else "unknown",
            )
            return factory()

    return None


def _offline_washing_machine() -> WashingMachineStatus:
    """Minimal WashingMachineStatus for an offline device (shows Off in sensors)."""
    return WashingMachineStatus(
        machine_state=MachineState.OFF,
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
    )


def _offline_tumble_dryer() -> TumbleDryerStatus:
    """Minimal TumbleDryerStatus for an offline device (shows Off in sensors)."""
    return TumbleDryerStatus(
        machine_state=MachineState.OFF,
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


def _offline_dishwasher() -> DishwasherStatus:
    """Minimal DishwasherStatus for an offline device (shows Idle in sensors)."""
    return DishwasherStatus(
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


def _offline_oven() -> OvenStatus:
    """Minimal OvenStatus for an offline device (shows Idle in sensors)."""
    return OvenStatus(
        machine_state=OvenState.IDLE,
        program=0,
        selection=0,
        temp=0.0,
        temp_reached=False,
        program_length_minutes=None,
        remote_control=False,
    )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Candy from a config entry."""

    ip_address = config_entry.data[CONF_IP_ADDRESS]
    encryption_key = config_entry.data.get(CONF_PASSWORD, "")
    use_encryption = config_entry.data.get(CONF_KEY_USE_ENCRYPTION, True)

    session = async_get_clientsession(hass)
    client = CandyClient(session, ip_address, encryption_key, use_encryption)

    # Attempt to restore the last known status from HA's entity registry + state machine.
    # HA persists entity states in its recorder database and restores them on startup,
    # so we can read the last known device type and pre-populate last_known_status.
    # This allows the integration to load gracefully even when the device is offline.
    last_known_status = _restore_last_known_status(hass, config_entry.entry_id)
    if last_known_status is not None:
        _LOGGER.debug(
            "Pre-populated last_known_status from HA state machine: %s",
            type(last_known_status).__name__,
        )

    async def update_status():
        nonlocal last_known_status
        try:
            async with async_timeout.timeout(40):
                status = await client.status_with_retry()
                _LOGGER.debug("Fetched status: %s", status)
                last_known_status = status
                return status
        except (TimeoutError, aiohttp.ClientError) as err:
            # Network / timeout error: check if we can infer "Off" from last known state
            prev_state = getattr(last_known_status, "machine_state", None)
            if prev_state in _OFF_INFERRED_STATES or prev_state == MachineState.OFF:
                _LOGGER.warning(
                    "Device at %s is unreachable (last state: %s). "
                    "Assuming it was powered off.",
                    ip_address,
                    prev_state,
                )
                return _make_off_status(last_known_status)
            raise UpdateFailed(f"Error communicating with API: {repr(err)}") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {repr(err)}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_interval=timedelta(seconds=60),
        update_method=update_status,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        DATA_KEY_COORDINATOR: coordinator
    }

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        del hass.data[DOMAIN]

    return unload_ok
