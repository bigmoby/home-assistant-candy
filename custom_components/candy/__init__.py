"""The Candy integration."""

from __future__ import annotations

import copy
from datetime import timedelta
import logging
from typing import Union

import aiohttp
import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import CandyClient
from .client.model import (
    DishwasherState,
    DishwasherStatus,
    MachineState,
    OvenState,
    OvenStatus,
    TumbleDryerStatus,
    WashingMachineStatus,
)
from .const import CONF_KEY_USE_ENCRYPTION, DATA_KEY_COORDINATOR, DOMAIN, PLATFORMS

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


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Candy from a config entry."""

    ip_address = config_entry.data[CONF_IP_ADDRESS]
    encryption_key = config_entry.data.get(CONF_PASSWORD, "")
    use_encryption = config_entry.data.get(CONF_KEY_USE_ENCRYPTION, True)

    session = async_get_clientsession(hass)
    client = CandyClient(session, ip_address, encryption_key, use_encryption)

    last_known_status = None

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
            if prev_state in _OFF_INFERRED_STATES:
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
