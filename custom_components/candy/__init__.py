"""The Candy integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import copy
from datetime import timedelta
import json
import logging
from typing import Any, cast
from urllib.parse import quote, urlencode

import aiohttp
import async_timeout
from homeassistant.components.persistent_notification import (
    async_create as pn_async_create,
    async_dismiss as pn_async_dismiss,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import CandyClient, parse_wash_programs
from .client.model import (
    CheckUpState,
    DishwasherState,
    DishwasherStatus,
    DryerCycleState,
    DryerProgramState,
    MachineState,
    OvenState,
    OvenStatus,
    TumbleDryerStatus,
    WashingMachineStatistics,
    WashingMachineStatus,
    WashProgramState,
    WineCoolerProgram,
    WineCoolerState,
    WineCoolerStatus,
)
from .const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_LAST_DATE,
    CONF_KEY_CHECKUP_LAST_RESULT,
    CONF_KEY_CHECKUP_PENDING,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_USE_ENCRYPTION,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_CHECKUP_UNSUB,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DATA_KEY_FULL_CHECKUP_UNSUB,
    DATA_KEY_LIMESCALE_UNSUB,
    DATA_KEY_MAINT_UNSUB,
    DATA_KEY_STATS_COORDINATOR,
    DATA_KEY_STATS_REFRESH_UNSUB,
    DATA_KEY_WASH_ERROR_UNSUB,
    DOMAIN,
    MAINTENANCE_FILTER_THRESHOLD,
    MAINTENANCE_FULL_CHECKUP_THRESHOLD,
    MAINTENANCE_HARDNESS_THRESHOLDS,
    MODE_FULL_CONTROL,
    NOTIF_ID_FULL_CHECKUP,
    NOTIF_ID_LIMESCALE,
    NOTIF_ID_MAINT_FILTER,
    NOTIF_ID_MAINT_FULL_CHECKUP,
    NOTIF_ID_MAINT_LIMESCALE,
    NOTIF_ID_WASH_ERROR,
    PLATFORMS,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_OVEN,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_WASH_TOTAL_CYCLES,
    UNIQUE_ID_WASHING_MACHINE,
    UNIQUE_ID_WINE_COOLER,
)
from .helpers import (
    cycles_remaining,
    get_wash_error_notification_strings,
    localized_notification_text,
)

_LOGGER = logging.getLogger(__name__)

# Machine states that strongly suggest the user powered off the device intentionally.
# In these cases, a timeout is treated as "Off" rather than "unavailable".
_OFF_INFERRED_STATES = {
    MachineState.FINISHED1,
    MachineState.FINISHED2,
    MachineState.IDLE,
    WineCoolerState.OFF,
}

# Poll fast while the machine is unreachable (synthetic OFF) so wakeup is detected quickly.
# 60 s while the machine is reachable and running any cycle.
SCAN_INTERVAL_ACTIVE = timedelta(seconds=60)
SCAN_INTERVAL_RESTING = timedelta(seconds=20)


def _make_off_status(
    last_status: WashingMachineStatus
    | TumbleDryerStatus
    | DishwasherStatus
    | OvenStatus
    | WineCoolerStatus,
) -> (
    WashingMachineStatus
    | TumbleDryerStatus
    | DishwasherStatus
    | OvenStatus
    | WineCoolerStatus
):
    """Return a copy of last_status with machine_state set to OFF (or equivalent).

    This synthetic status allows sensors to display "Off" when the device is
    unreachable but was last seen in a Finished or Idle state.
    """
    off_status: (
        WashingMachineStatus
        | TumbleDryerStatus
        | DishwasherStatus
        | OvenStatus
        | WineCoolerStatus
    )
    if isinstance(last_status, DishwasherStatus):
        # Dishwasher uses its own DishwasherState enum — use IDLE as the "Off" equivalent
        off_status = copy.copy(last_status)
        off_status.machine_state = DishwasherState.IDLE
        off_status.remaining_minutes = 0
    elif isinstance(last_status, OvenStatus):
        off_status = copy.copy(last_status)
        off_status.machine_state = OvenState.IDLE
    elif isinstance(last_status, WineCoolerStatus):
        off_status = copy.copy(last_status)
        off_status.machine_state = WineCoolerState.OFF
    else:
        # WashingMachineStatus and TumbleDryerStatus both use MachineState
        off_status = copy.copy(last_status)
        off_status.machine_state = MachineState.OFF
    return off_status


def _restore_last_known_status(
    hass: HomeAssistant,
    config_entry_id: str,
) -> (
    WashingMachineStatus
    | TumbleDryerStatus
    | DishwasherStatus
    | OvenStatus
    | WineCoolerStatus
    | None
):
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
        WashingMachineStatus
        | TumbleDryerStatus
        | DishwasherStatus
        | OvenStatus
        | WineCoolerStatus,
    ]
    candidates: list[tuple[str, StatusFactory]] = [
        (UNIQUE_ID_WASHING_MACHINE.format(config_entry_id), _offline_washing_machine),
        (UNIQUE_ID_TUMBLE_DRYER.format(config_entry_id), _offline_tumble_dryer),
        (UNIQUE_ID_DISHWASHER.format(config_entry_id), _offline_dishwasher),
        (UNIQUE_ID_OVEN.format(config_entry_id), _offline_oven),
        (UNIQUE_ID_WINE_COOLER.format(config_entry_id), _offline_wine_cooler),
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


def _restore_last_known_statistics(
    hass: HomeAssistant,
    config_entry_id: str,
) -> WashingMachineStatistics | None:
    """Read the persisted total-cycles value from HA's state machine.

    Returns a WashingMachineStatistics populated from the last known sensor state,
    or None if the entity was never registered or its state is not a valid integer.
    """
    registry = er.async_get(hass)
    unique_id = UNIQUE_ID_WASH_TOTAL_CYCLES.format(config_entry_id)
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
    return WashingMachineStatistics(total_cycles=int(state.state))


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
        dis_test_res=None,
        checkup_state=None,
        soil_level=None,
        recipe_id=None,
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


def _offline_wine_cooler() -> WineCoolerStatus:
    """Minimal WineCoolerStatus for an offline device (shows Off in sensors)."""
    return WineCoolerStatus(
        machine_state=WineCoolerState.OFF,
        program=WineCoolerProgram.RED_WINE,
        temp=16,
        light=False,
        error=None,
        remote_control=False,
        program_down=None,
        temp_down=None,
    )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Candy from a config entry."""

    ip_address = config_entry.data[CONF_IP_ADDRESS]
    encryption_key = config_entry.data.get(CONF_PASSWORD, "")
    use_encryption = config_entry.data.get(CONF_KEY_USE_ENCRYPTION, True)

    session = async_get_clientsession(hass)
    client = CandyClient(session, ip_address, encryption_key, use_encryption)

    @callback
    def _migrate_unique_ids(entry: er.RegistryEntry) -> dict[str, Any] | None:
        old = f"{config_entry.entry_id}-wash_limestone_button"
        if entry.unique_id == old:
            return {"new_unique_id": f"{config_entry.entry_id}-wash_limescale_button"}
        return None

    await er.async_migrate_entries(hass, config_entry.entry_id, _migrate_unique_ids)

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
        prev_state = getattr(last_known_status, "machine_state", None)
        can_infer_off = (
            prev_state in _OFF_INFERRED_STATES or prev_state == MachineState.OFF
        )
        # When we can fall back to Off, use a short timeout — this cuts the stall caused by
        # the OS TCP retransmit cycle (~13s) for offline devices. 7s is chosen to guarantee
        # the rate limiter (max_rate=1, time_period=3s) clears before the HTTP request starts,
        # plus margin for WiFi jitter and slow firmware. Live devices respond in <100ms.
        poll_timeout = 7 if can_infer_off else 40
        try:
            # Use a single attempt (no backoff) when we can fall back to a cached Off status —
            # retrying a connection error against an offline device just wastes time at startup.
            fetch = client.status() if can_infer_off else client.status_with_retry()
            async with async_timeout.timeout(poll_timeout):
                status = await fetch
                _LOGGER.debug("Fetched status: %s", status)
                last_known_status = status
                coordinator.update_interval = SCAN_INTERVAL_ACTIVE
                return status
        except (TimeoutError, aiohttp.ClientError) as err:
            if can_infer_off:
                _LOGGER.debug(
                    "Device at %s is unreachable (last state: %s). "
                    "Assuming it was powered off.",
                    ip_address,
                    prev_state,
                )
                coordinator.update_interval = SCAN_INTERVAL_RESTING
                return _make_off_status(last_known_status)
            raise UpdateFailed(f"Error communicating with API: {err!r}") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err!r}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_interval=SCAN_INTERVAL_ACTIVE,
        update_method=update_status,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        DATA_KEY_COORDINATOR: coordinator,
        DATA_KEY_CLIENT: client,
    }

    if isinstance(coordinator.data, WashingMachineStatus):
        last_known_statistics = _restore_last_known_statistics(
            hass, config_entry.entry_id
        )

        async def update_statistics() -> WashingMachineStatistics:
            nonlocal last_known_statistics
            if getattr(coordinator.data, "machine_state", None) == MachineState.OFF:
                if last_known_statistics is not None:
                    return last_known_statistics
                raise UpdateFailed("Machine is OFF; statistics unavailable.")
            try:
                async with async_timeout.timeout(40):
                    stats = await client.statistics_with_retry()
                    last_known_statistics = stats
                    return stats
            except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as err:
                if last_known_statistics is not None:
                    _LOGGER.warning(
                        "Failed to fetch statistics (%s); returning last known value.",
                        repr(err),
                    )
                    return last_known_statistics
                raise UpdateFailed(f"Error fetching statistics: {err!r}") from err

        stats_coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_statistics",
            update_interval=timedelta(hours=1),
            update_method=update_statistics,
        )
        machine_is_off = (
            getattr(coordinator.data, "machine_state", None) == MachineState.OFF
        )
        if last_known_statistics is not None:
            # Seed the coordinator with the restored value so we skip the initial
            # network fetch (which would retry 3× against an offline machine).
            stats_coordinator.async_set_updated_data(last_known_statistics)
        elif machine_is_off:
            # Device is off — total_cycles cannot have changed, skip the fetch.
            # The hourly poll will retrieve it once the device is reachable.
            pass
        else:
            await stats_coordinator.async_refresh()
        stats_entity_id = er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, UNIQUE_ID_WASH_TOTAL_CYCLES.format(config_entry.entry_id)
        )
        if stats_coordinator.last_update_success or stats_entity_id is not None:
            hass.data[DOMAIN][config_entry.entry_id][DATA_KEY_STATS_COORDINATOR] = (
                stats_coordinator
            )

        if config_entry.data.get(CONF_KEY_MAINTENANCE_ENABLED):
            unsub = _register_maintenance_notifications(
                hass, config_entry, stats_coordinator
            )
            hass.data[DOMAIN][config_entry.entry_id][DATA_KEY_MAINT_UNSUB] = unsub

        if config_entry.data.get(CONF_KEY_CHECKUP_ENABLED):
            unsub_checkup = _register_checkup_listener(hass, config_entry, coordinator)
            hass.data[DOMAIN][config_entry.entry_id][DATA_KEY_CHECKUP_UNSUB] = (
                unsub_checkup
            )

        unsub_stats_refresh = _register_stats_refresh_listener(
            hass, coordinator, stats_coordinator
        )
        hass.data[DOMAIN][config_entry.entry_id][DATA_KEY_STATS_REFRESH_UNSUB] = (
            unsub_stats_refresh
        )

        unsub_full_checkup = _register_full_checkup_listener(
            hass, config_entry, coordinator, stats_coordinator, client
        )
        hass.data[DOMAIN][config_entry.entry_id][DATA_KEY_FULL_CHECKUP_UNSUB] = (
            unsub_full_checkup
        )

        unsub_wash_error = _register_wash_error_listener(
            hass, config_entry, coordinator
        )
        hass.data[DOMAIN][config_entry.entry_id][DATA_KEY_WASH_ERROR_UNSUB] = (
            unsub_wash_error
        )

        unsub_limescale = _register_limescale_listener(
            hass, config_entry, coordinator, stats_coordinator
        )
        hass.data[DOMAIN][config_entry.entry_id][DATA_KEY_LIMESCALE_UNSUB] = (
            unsub_limescale
        )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


def _register_maintenance_notifications(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    stats_coordinator: DataUpdateCoordinator[Any],
) -> Callable[[], None]:
    entry_id = config_entry.entry_id
    hardness = config_entry.data.get(CONF_KEY_WATER_HARDNESS, 2)
    limescale_threshold = MAINTENANCE_HARDNESS_THRESHOLDS[hardness]
    lang = config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, hass.config.language)

    _MAINTENANCE_ITEMS = [
        (
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
            MAINTENANCE_FULL_CHECKUP_THRESHOLD,
            NOTIF_ID_MAINT_FULL_CHECKUP.format(entry_id),
            localized_notification_text("full_checkup_title", lang),
            localized_notification_text("full_checkup_due_message", lang),
        ),
    ]
    if config_entry.data.get(CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True):
        _MAINTENANCE_ITEMS.append(
            (
                CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
                limescale_threshold,
                NOTIF_ID_MAINT_LIMESCALE.format(entry_id),
                localized_notification_text("limescale_title", lang),
                localized_notification_text("limescale_message", lang),
            )
        )
    if config_entry.data.get(CONF_KEY_MAINTENANCE_FILTER_ENABLED, True):
        _MAINTENANCE_ITEMS.append(
            (
                CONF_KEY_MAINTENANCE_LAST_FILTER,
                MAINTENANCE_FILTER_THRESHOLD,
                NOTIF_ID_MAINT_FILTER.format(entry_id),
                localized_notification_text("filter_title", lang),
                localized_notification_text("filter_due_message", lang),
            )
        )

    def _on_stats_update() -> None:
        stats: WashingMachineStatistics | None = cast(
            WashingMachineStatistics | None, stats_coordinator.data
        )
        if stats is None:
            return
        for last_key, threshold, notif_id, title, message in _MAINTENANCE_ITEMS:
            last = config_entry.data.get(last_key, 0)
            if cycles_remaining(stats.total_cycles, last, threshold) == 0:
                pn_async_create(hass, message, title=title, notification_id=notif_id)

    return stats_coordinator.async_add_listener(_on_stats_update)


_FINISHED_STATES = {MachineState.FINISHED1, MachineState.FINISHED2}


def _register_checkup_listener(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: DataUpdateCoordinator[Any],
) -> Callable[[], None]:
    """Register a coordinator listener that records the check-up timestamp when the cycle finishes."""
    initial = cast(WashingMachineStatus | None, coordinator.data)
    initial_code = (
        initial.dis_test_res.code
        if initial is not None and initial.dis_test_res is not None
        else None
    )
    initial_state = initial.machine_state if initial is not None else None
    initial_pending = config_entry.data.get(CONF_KEY_CHECKUP_PENDING, False)

    prev_result: list[int | None] = [initial_code]
    prev_state: list[MachineState | None] = [initial_state]
    finished_cycle_recorded: list[bool] = [
        initial_state in _FINISHED_STATES and not initial_pending
    ]

    def _on_status_update() -> None:
        status = cast(WashingMachineStatus | None, coordinator.data)
        if status is None:
            return
        curr_state = status.machine_state
        prior_state = prev_state[0]
        prev_state[0] = curr_state

        curr_code = (
            status.dis_test_res.code if status.dis_test_res is not None else None
        )
        prior_code = prev_result[0]
        prev_result[0] = curr_code

        if curr_state not in _FINISHED_STATES:
            finished_cycle_recorded[0] = False

        is_pending = config_entry.data.get(CONF_KEY_CHECKUP_PENDING, False)
        schedule = config_entry.data.get(
            CONF_KEY_CHECKUP_SCHEDULE, CHECKUP_SCHEDULE_EVERY_CYCLE
        )

        if curr_state in _FINISHED_STATES:
            if not finished_cycle_recorded[0]:
                should_record = is_pending or schedule == CHECKUP_SCHEDULE_EVERY_CYCLE
                if should_record and curr_code is not None and curr_code != 0:
                    finished_cycle_recorded[0] = True
                    new_data = dict(config_entry.data)
                    new_data[CONF_KEY_CHECKUP_LAST_DATE] = dt_util.utcnow().timestamp()
                    new_data[CONF_KEY_CHECKUP_LAST_RESULT] = curr_code
                    new_data[CONF_KEY_CHECKUP_PENDING] = False
                    hass.config_entries.async_update_entry(config_entry, data=new_data)
                    return
        elif (
            is_pending
            and curr_state in (MachineState.IDLE, MachineState.OFF)
            and prior_state not in (MachineState.IDLE, MachineState.OFF, None)
        ):
            new_data = dict(config_entry.data)
            new_data[CONF_KEY_CHECKUP_PENDING] = False
            hass.config_entries.async_update_entry(config_entry, data=new_data)
            return

        if (
            curr_code is not None
            and curr_code != 0
            and (prior_code == 0 or prior_code is None)
            and config_entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT) != curr_code
        ):
            new_data = dict(config_entry.data)
            new_data[CONF_KEY_CHECKUP_LAST_RESULT] = curr_code
            hass.config_entries.async_update_entry(config_entry, data=new_data)

    return coordinator.async_add_listener(_on_status_update)


def _register_full_checkup_listener(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: DataUpdateCoordinator[Any],
    stats_coordinator: DataUpdateCoordinator[WashingMachineStatistics],
    client: CandyClient,
) -> Callable[[], None]:
    """Register a coordinator listener that handles Full Check-up completion."""
    initial = cast(WashingMachineStatus | None, coordinator.data)
    prev_state: list[CheckUpState | None] = [
        initial.checkup_state if initial is not None else None
    ]

    def _on_status_update() -> None:
        status = cast(WashingMachineStatus | None, coordinator.data)
        if status is None:
            return
        curr_state = status.checkup_state
        prior_state = prev_state[0]
        prev_state[0] = curr_state

        has_no_error = (status.error in (None, 0)) and (
            status.machine_state != MachineState.ERROR
        )

        if (
            curr_state == CheckUpState.COMPLETED
            and prior_state == CheckUpState.RUNNING
            and has_no_error
        ):
            entry_id = config_entry.entry_id
            lang = config_entry.data.get(
                CONF_KEY_PROGRAM_LANGUAGE, hass.config.language
            )
            title = localized_notification_text("full_checkup_result_title", lang)
            message = localized_notification_text("full_checkup_result_message", lang)
            pn_async_create(
                hass,
                message,
                title=title,
                notification_id=NOTIF_ID_FULL_CHECKUP.format(entry_id),
            )
            pn_async_dismiss(hass, NOTIF_ID_MAINT_FULL_CHECKUP.format(entry_id))

            async def _update_baseline() -> None:
                await stats_coordinator.async_request_refresh()
                total: int | None = None
                if stats_coordinator.data is not None:
                    total = stats_coordinator.data.total_cycles
                else:
                    restored = _restore_last_known_statistics(hass, entry_id)
                    if restored is not None:
                        total = restored.total_cycles

                if total is not None:
                    new_data = dict(config_entry.data)
                    new_data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = total
                    hass.config_entries.async_update_entry(config_entry, data=new_data)
                    stats_coordinator.async_update_listeners()

            hass.async_create_task(_update_baseline())

            if (
                config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL
                and status.remote_control
            ):

                async def _send_reset() -> None:
                    try:
                        await client.send_command(
                            urlencode(
                                {"Write": 1, "StSt": 0, "PrNm": 11}, quote_via=quote
                            )
                        )
                        await asyncio.sleep(5)
                        await coordinator.async_request_refresh()
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to reset appliance check-up state: %s", err
                        )

                hass.async_create_task(_send_reset())

    return coordinator.async_add_listener(_on_status_update)


def _register_limescale_listener(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: DataUpdateCoordinator[Any],
    stats_coordinator: DataUpdateCoordinator[WashingMachineStatistics],
) -> Callable[[], None]:
    """Register a coordinator listener that handles Limescale Cleaning completion."""
    if not config_entry.data.get(CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True):
        return lambda: None

    programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))
    autoclean = next((p for p in programs if "autoclean" in p.name.lower()), None)
    if autoclean is None:
        return lambda: None

    initial = cast(WashingMachineStatus | None, coordinator.data)
    initial_running = (
        initial is not None
        and initial.machine_state in (MachineState.RUNNING, MachineState.PAUSED)
        and (
            initial.program == autoclean.selector_position
            or (
                autoclean.pr_code is not None
                and initial.program_code == autoclean.pr_code
            )
        )
    )
    was_running_autoclean: list[bool] = [initial_running]

    def _on_status_update() -> None:
        status = cast(WashingMachineStatus | None, coordinator.data)
        if status is None:
            return

        curr_state = status.machine_state
        has_no_error = (status.error in (None, 0)) and (
            curr_state != MachineState.ERROR
        )

        is_autoclean = status.program == autoclean.selector_position or (
            autoclean.pr_code is not None and status.program_code == autoclean.pr_code
        )

        if curr_state in (MachineState.RUNNING, MachineState.PAUSED) and is_autoclean:
            was_running_autoclean[0] = True
        elif curr_state in _FINISHED_STATES:
            if was_running_autoclean[0] and has_no_error:
                was_running_autoclean[0] = False
                entry_id = config_entry.entry_id
                lang = config_entry.data.get(
                    CONF_KEY_PROGRAM_LANGUAGE, hass.config.language
                )
                title = localized_notification_text("limescale_result_title", lang)
                message = localized_notification_text("limescale_result_message", lang)
                pn_async_create(
                    hass,
                    message,
                    title=title,
                    notification_id=NOTIF_ID_LIMESCALE.format(entry_id),
                )
                pn_async_dismiss(hass, NOTIF_ID_MAINT_LIMESCALE.format(entry_id))

                async def _update_baseline() -> None:
                    await stats_coordinator.async_request_refresh()
                    total: int | None = None
                    if stats_coordinator.data is not None:
                        total = stats_coordinator.data.total_cycles
                    else:
                        restored = _restore_last_known_statistics(hass, entry_id)
                        if restored is not None:
                            total = restored.total_cycles

                    if total is not None:
                        new_data = dict(config_entry.data)
                        new_data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] = total
                        hass.config_entries.async_update_entry(
                            config_entry, data=new_data
                        )
                        stats_coordinator.async_update_listeners()

                hass.async_create_task(_update_baseline())
        elif curr_state in (MachineState.IDLE, MachineState.OFF):
            was_running_autoclean[0] = False

    return coordinator.async_add_listener(_on_status_update)


def _register_stats_refresh_listener(
    hass: HomeAssistant,
    coordinator: DataUpdateCoordinator[Any],
    stats_coordinator: DataUpdateCoordinator[WashingMachineStatistics],
) -> Callable[[], None]:
    """Refresh statistics when a wash cycle transitions into a finished state."""
    initial = cast(WashingMachineStatus | None, coordinator.data)
    prev_state: list[MachineState | None] = [
        initial.machine_state if initial is not None else None
    ]

    def _on_status_update() -> None:
        status = cast(WashingMachineStatus | None, coordinator.data)
        if status is None:
            return
        curr = status.machine_state
        prev = prev_state[0]
        prev_state[0] = curr
        if curr in _FINISHED_STATES and prev not in _FINISHED_STATES:
            hass.async_create_task(stats_coordinator.async_request_refresh())

    return coordinator.async_add_listener(_on_status_update)


def _register_wash_error_listener(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: DataUpdateCoordinator[Any],
) -> Callable[[], None]:
    """Register a coordinator listener that posts error notifications and dismisses them when cleared."""
    entry_id = config_entry.entry_id
    notif_id = NOTIF_ID_WASH_ERROR.format(entry_id)
    lang = config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, hass.config.language)

    initial = cast(WashingMachineStatus | None, coordinator.data)
    initial_error = initial.error if initial is not None else None
    prev_error: list[int | None] = [initial_error]

    if initial_error is not None and initial_error > 0:
        notif_strings = get_wash_error_notification_strings(initial_error, lang)
        if notif_strings is not None:
            title, message = notif_strings
            pn_async_create(hass, message, title=title, notification_id=notif_id)
        else:
            _LOGGER.warning("Unknown washing machine error code: %s", initial_error)

    def _on_status_update() -> None:
        status = cast(WashingMachineStatus | None, coordinator.data)
        if status is None:
            return
        curr_error = status.error
        prior_error = prev_error[0]
        prev_error[0] = curr_error

        if curr_error == prior_error:
            return

        if curr_error is not None and curr_error > 0:
            notif_strings = get_wash_error_notification_strings(curr_error, lang)
            if notif_strings is not None:
                title, message = notif_strings
                pn_async_create(hass, message, title=title, notification_id=notif_id)
            else:
                _LOGGER.warning("Unknown washing machine error code: %s", curr_error)
        elif prior_error is not None and prior_error > 0:
            pn_async_dismiss(hass, notif_id)

    return coordinator.async_add_listener(_on_status_update)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, {})
        for key in (
            DATA_KEY_MAINT_UNSUB,
            DATA_KEY_CHECKUP_UNSUB,
            DATA_KEY_FULL_CHECKUP_UNSUB,
            DATA_KEY_STATS_REFRESH_UNSUB,
            DATA_KEY_WASH_ERROR_UNSUB,
            DATA_KEY_LIMESCALE_UNSUB,
        ):
            unsub = entry_data.get(key)
            if unsub is not None:
                unsub()
        if not hass.data[DOMAIN]:
            del hass.data[DOMAIN]
    return unload_ok
