"""Config flow for Candy integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import logging
from typing import Any

import async_timeout
from homeassistant import config_entries
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .client import (
    CandyClient,
    detect_encryption,
    discover_devices,
    is_legacy_dishwasher,
    parse_wash_programs,
    supports_dishwasher_statistics,
)
from .client.cloud import CloudApplianceData, SimplyFiCloudError, fetch_appliance_data
from .client.decryption import Encryption
from .client.model import DishwasherStatus, TumbleDryerStatus, WashingMachineStatus
from .const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CHECKUP_SCHEDULE_MONTHLY,
    CHECKUP_SCHEDULE_WEEKLY,
    CONF_INTEGRATION_TITLE,
    CONF_KEY_APPLIANCE_TYPE,
    CONF_KEY_BRAND,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_DISHWASHER_BUZZER,
    CONF_KEY_DISHWASHER_REMEMBER_LAST_CYCLE,
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_DISHWASHER,
    CONF_KEY_IS_TUMBLE_DRYER,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_IS_WASHING_MACHINE,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_PURCHASE_DATE,
    CONF_KEY_SERIAL_NUMBER,
    CONF_KEY_USE_ENCRYPTION,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DATA_KEY_WRITE_PENDING,
    DEFAULT_DISHWASHER_PROGRAMS,
    DISHWASHER_HARDNESS_THRESHOLDS_LED,
    DISHWASHER_HARDNESS_THRESHOLDS_SMOOTH,
    DISHWASHER_MAINTENANCE_FILTER_THRESHOLD,
    DOMAIN,
    MAINTENANCE_FILTER_THRESHOLD,
    MAINTENANCE_FULL_CHECKUP_THRESHOLD,
    MAINTENANCE_HARDNESS_LABELS,
    MAINTENANCE_HARDNESS_THRESHOLDS,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    PROGRAM_LANGUAGES,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_DISHWASHER_MAINT_FILTER,
    UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP,
    UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_WASH_MAINT_FILTER,
    UNIQUE_ID_WASH_MAINT_FULL_CHECKUP,
    UNIQUE_ID_WASH_MAINT_LIMESCALE,
    UNIQUE_ID_WASHING_MACHINE,
)
from .helpers import (
    cycles_remaining,
    is_dishwasher_digit_or_smooth_interface,
    is_dualtech,
    is_dualtech_dryer,
    is_washer_dryer,
    supports_scheduled_checkup,
)

_LOGGER = logging.getLogger(__name__)

STEP_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
    }
)

MODE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KEY_MODE, default=MODE_READ_ONLY): vol.In(
            [MODE_READ_ONLY, MODE_FULL_CONTROL]
        ),
    }
)

CLOUD_SCHEMA = vol.Schema(
    {
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)

MANUAL_IP_OPTION = "manual"

MAINTENANCE_ENABLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KEY_MAINTENANCE_ENABLED, default=False): bool,
    }
)

CHECKUP_ENABLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_KEY_CHECKUP_ENABLED, default=False): bool,
    }
)

CHECKUP_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_KEY_CHECKUP_SCHEDULE, default=str(CHECKUP_SCHEDULE_EVERY_CYCLE)
        ): SelectSelector(
            SelectSelectorConfig(
                options=[
                    str(CHECKUP_SCHEDULE_EVERY_CYCLE),
                    str(CHECKUP_SCHEDULE_WEEKLY),
                    str(CHECKUP_SCHEDULE_MONTHLY),
                ],
                mode=SelectSelectorMode.LIST,
                translation_key="checkup_schedule",
            )
        ),
    }
)


def _hardness_schema(
    current: int,
    is_dishwasher: bool,
    interface_type: str | None,
) -> vol.Schema:
    """Build schema for water hardness selection, interface-aware for dishwashers."""
    if is_dishwasher:
        if is_dishwasher_digit_or_smooth_interface(interface_type):
            levels_count = 8
            trans_key = "dishwasher_water_hardness_digit"
        else:
            levels_count = 6
            trans_key = "dishwasher_water_hardness_led"
        bounded = min(max(current, 0), levels_count - 1)
        options = [
            SelectOptionDict(value=str(i), label=str(i)) for i in range(levels_count)
        ]
    else:
        trans_key = "water_hardness"
        bounded = min(max(current, 0), len(MAINTENANCE_HARDNESS_LABELS) - 1)
        options = [
            SelectOptionDict(value=str(i), label=label)
            for i, label in enumerate(MAINTENANCE_HARDNESS_LABELS)
        ]
    return vol.Schema(
        {
            vol.Required(CONF_KEY_WATER_HARDNESS, default=str(bounded)): SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=trans_key,
                )
            ),
        }
    )


HARDNESS_SCHEMA = _hardness_schema(
    current=2,
    is_dishwasher=False,
    interface_type=None,
)


def _remaining_to_last_reset(remaining: int, total: int, threshold: int) -> int:
    """Convert user-visible remaining cycles into the last_reset value for storage.

    last_reset is total_cycles at the time of the last maintenance action.
    remaining = threshold - (total - last_reset), so last_reset = total - (threshold - remaining).
    Negative values are valid: they represent a virtual reset point before the device existed,
    which correctly tracks a partial cycle from the machine's history.
    """
    return total - (threshold - remaining)


def _current_remaining_cycles(
    hass: HomeAssistant, entry_id: str, unique_id_template: str
) -> int | None:
    """Read the current remaining-cycles value from the sensor's live state.

    Used as the reconfigure-form default when total_cycles is not yet available
    from the stats coordinator, so the form shows the machine's real state
    instead of always defaulting to the threshold.
    """
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, unique_id_template.format(entry_id)
    )
    if entity_id is None:
        return None
    state = hass.states.get(entity_id)
    if state is None or not state.state.isdigit():
        return None
    return int(state.state)


def _baselines_schema(
    total_cycles: int,
    limescale_enabled: bool,
    filter_enabled: bool,
    limescale_threshold: int,
    filter_threshold: int,
) -> vol.Schema:
    """Build schema for remaining-cycles fields with current remaining as defaults."""
    fields: dict[vol.Required, type] = {
        vol.Required(
            CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
            default=cycles_remaining(
                total_cycles, 0, MAINTENANCE_FULL_CHECKUP_THRESHOLD
            ),
        ): int,
    }
    if limescale_enabled:
        fields[
            vol.Required(
                CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
                default=cycles_remaining(total_cycles, 0, limescale_threshold),
            )
        ] = int
    if filter_enabled:
        fields[
            vol.Required(
                CONF_KEY_MAINTENANCE_LAST_FILTER,
                default=cycles_remaining(total_cycles, 0, filter_threshold),
            )
        ] = int
    return vol.Schema(fields)


def _dishwasher_settings_schema(
    interface_type: str | None,
    default_hardness: int = 2,
    default_buzzer: bool = True,
    default_remember_last_cycle: bool = True,
) -> vol.Schema:
    """Build schema for dishwasher hardware settings."""
    is_digit = is_dishwasher_digit_or_smooth_interface(interface_type)
    num_levels = 8 if is_digit else 6
    trans_key = (
        "dishwasher_water_hardness_digit"
        if is_digit
        else "dishwasher_water_hardness_led"
    )
    safe_hardness = min(max(default_hardness, 0), num_levels - 1)
    return vol.Schema(
        {
            vol.Required(
                CONF_KEY_WATER_HARDNESS, default=str(safe_hardness)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[str(i) for i in range(num_levels)],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=trans_key,
                )
            ),
            vol.Required(CONF_KEY_DISHWASHER_BUZZER, default=default_buzzer): bool,
            vol.Required(
                CONF_KEY_DISHWASHER_REMEMBER_LAST_CYCLE,
                default=default_remember_last_cycle,
            ): bool,
        }
    )


def _language_schema(default_lang: str) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_KEY_PROGRAM_LANGUAGE, default=default_lang
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=code, label=label)
                        for code, label in PROGRAM_LANGUAGES.items()
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _get_local_subnet(hass_ip: str) -> str:
    """Return the /24 subnet string for the given IP (e.g. '192.168.1.1' → '192.168.1.0')."""
    parts = hass_ip.split(".")[:3]
    return ".".join(parts) + ".0"


def apply_cloud_appliance_data(
    current_data: dict[str, Any],
    appliance: CloudApplianceData,
    *,
    is_washing_machine: bool,
    is_tumble_dryer: bool,
    is_dishwasher: bool,
) -> dict[str, Any]:
    """Merge Simply-Fi cloud appliance metadata into config entry data for Full Control."""
    new_data = dict(current_data)
    new_data[CONF_KEY_MODE] = MODE_FULL_CONTROL
    if is_washing_machine:
        new_data[CONF_KEY_IS_WASHING_MACHINE] = True
    if is_tumble_dryer:
        new_data[CONF_KEY_IS_TUMBLE_DRYER] = True
    if is_dishwasher:
        new_data[CONF_KEY_IS_DISHWASHER] = True
    if CONF_KEY_USE_ENCRYPTION not in current_data and appliance.encryption_key:
        new_data[CONF_KEY_USE_ENCRYPTION] = True
        new_data[CONF_PASSWORD] = appliance.encryption_key
    if appliance.mac_address:
        new_data[CONF_KEY_MAC_ADDRESS] = appliance.mac_address
    if appliance.appliance_model:
        new_data[CONF_KEY_DEVICE_MODEL] = appliance.appliance_model
    if appliance.serial_number:
        new_data[CONF_KEY_SERIAL_NUMBER] = appliance.serial_number
    if appliance.purchase_date:
        new_data[CONF_KEY_PURCHASE_DATE] = appliance.purchase_date
    new_data[CONF_KEY_PROGRAMS] = (
        DEFAULT_DISHWASHER_PROGRAMS
        if is_dishwasher and not appliance.programs
        else appliance.programs
    )
    new_data[CONF_KEY_DOWNLOADABLE_PROGRAMS] = appliance.downloadable_programs
    if appliance.interface_type:
        new_data[CONF_KEY_INTERFACE_TYPE] = appliance.interface_type
    if appliance.brand:
        new_data[CONF_KEY_BRAND] = appliance.brand
    if appliance.appliance_type:
        new_data[CONF_KEY_APPLIANCE_TYPE] = appliance.appliance_type
        if appliance.appliance_type == "washer_dryer":
            new_data[CONF_KEY_IS_WASHER_DRYER] = True
    elif appliance.programs:
        try:
            parsed = parse_wash_programs(appliance.programs)
            if any(
                p.program_type in ("D", "WD") or p.selector_position_dry is not None
                for p in parsed
            ):
                new_data[CONF_KEY_IS_WASHER_DRYER] = True
        except (KeyError, TypeError, ValueError):
            pass
    return new_data


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle the options flow for the COG icon."""

    def __init__(self) -> None:
        self._pending_data: dict[str, Any] = {}

    def _is_washing_machine(self) -> bool:
        if CONF_KEY_IS_WASHING_MACHINE in self.config_entry.data:
            return bool(self.config_entry.data[CONF_KEY_IS_WASHING_MACHINE])
        registry = er.async_get(self.hass)
        if (
            registry.async_get_entity_id(
                "sensor",
                DOMAIN,
                UNIQUE_ID_WASHING_MACHINE.format(self.config_entry.entry_id),
            )
            is not None
        ):
            return True
        coord = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get(DATA_KEY_COORDINATOR)
        )
        return coord is not None and isinstance(coord.data, WashingMachineStatus)

    def _is_tumble_dryer(self) -> bool:
        if CONF_KEY_IS_TUMBLE_DRYER in self.config_entry.data:
            return bool(self.config_entry.data[CONF_KEY_IS_TUMBLE_DRYER])
        registry = er.async_get(self.hass)
        if (
            registry.async_get_entity_id(
                "sensor",
                DOMAIN,
                UNIQUE_ID_TUMBLE_DRYER.format(self.config_entry.entry_id),
            )
            is not None
        ):
            return True
        coord = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get(DATA_KEY_COORDINATOR)
        )
        return coord is not None and isinstance(coord.data, TumbleDryerStatus)

    def _is_dishwasher(self) -> bool:
        if CONF_KEY_IS_DISHWASHER in self.config_entry.data:
            return bool(self.config_entry.data[CONF_KEY_IS_DISHWASHER])
        registry = er.async_get(self.hass)
        if (
            registry.async_get_entity_id(
                "sensor",
                DOMAIN,
                UNIQUE_ID_DISHWASHER.format(self.config_entry.entry_id),
            )
            is not None
        ):
            return True
        coord = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get(DATA_KEY_COORDINATOR)
        )
        return coord is not None and isinstance(coord.data, DishwasherStatus)

    def _is_controllable(self) -> bool:
        return (
            self._is_washing_machine()
            or self._is_tumble_dryer()
            or self._is_dishwasher()
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Branch based on current mode."""
        mode = self.config_entry.data.get(CONF_KEY_MODE, MODE_READ_ONLY)
        is_washing_machine = self._is_washing_machine()
        is_dryer = self._is_tumble_dryer()
        is_dishwasher = self._is_dishwasher()

        if user_input is not None:
            if user_input["next_step"] == "switch_to_read_only":
                return await self.async_step_switch_to_read_only()
            if user_input["next_step"] == "dishwasher_settings":
                return await self.async_step_dishwasher_settings()
            if user_input["next_step"] == "maintenance_settings":
                return await self.async_step_maintenance()
            if user_input["next_step"] == "checkup_settings":
                return await self.async_step_checkup()
            return await self.async_step_update_cloud_data()

        if mode == MODE_FULL_CONTROL:
            options = ["update_cloud_data", "switch_to_read_only"]
            interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
            if is_dishwasher and not is_legacy_dishwasher(interface_type):
                options.append("dishwasher_settings")
                if supports_dishwasher_statistics(interface_type):
                    options.append("maintenance_settings")
            elif is_washing_machine:
                options.append("maintenance_settings")
            if supports_scheduled_checkup(interface_type, is_dryer):
                options.append("checkup_settings")
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required("next_step"): SelectSelector(
                            SelectSelectorConfig(
                                options=options,
                                mode=SelectSelectorMode.LIST,
                                translation_key="next_step",
                            )
                        )
                    }
                ),
            )

        if not is_washing_machine:
            if is_dryer or is_dishwasher:
                return await self.async_step_update_cloud_data()
            return self.async_create_entry(data={})

        return await self.async_step_maintenance()

    async def async_step_dishwasher_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure dishwasher hardware settings and dispatch changes over LAN."""
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        coord = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get(DATA_KEY_COORDINATOR)
        )
        status: DishwasherStatus | None = (
            coord.data if coord and isinstance(coord.data, DishwasherStatus) else None
        )

        if user_input is None:
            cur_hardness = (
                status.water_hardness
                if status and status.water_hardness is not None
                else self.config_entry.data.get(CONF_KEY_WATER_HARDNESS, 2)
            )
            cur_buzzer = (
                status.buzzer
                if status and status.buzzer is not None
                else self.config_entry.data.get(CONF_KEY_DISHWASHER_BUZZER, True)
            )
            cur_memo = (
                status.remember_last_cycle
                if status and status.remember_last_cycle is not None
                else self.config_entry.data.get(
                    CONF_KEY_DISHWASHER_REMEMBER_LAST_CYCLE, True
                )
            )
            return self.async_show_form(
                step_id="dishwasher_settings",
                data_schema=_dishwasher_settings_schema(
                    interface_type=interface_type,
                    default_hardness=cur_hardness,
                    default_buzzer=cur_buzzer,
                    default_remember_last_cycle=cur_memo,
                ),
            )

        new_hardness = int(user_input[CONF_KEY_WATER_HARDNESS])
        new_buzzer = bool(user_input[CONF_KEY_DISHWASHER_BUZZER])
        new_memo = bool(user_input[CONF_KEY_DISHWASHER_REMEMBER_LAST_CYCLE])

        client: CandyClient | None = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get(DATA_KEY_CLIENT)
        )
        if client is not None:
            commands_to_send: list[
                tuple[str, Callable[[], Coroutine[Any, Any, None]]]
            ] = []
            if status is None or new_hardness != status.water_hardness:
                commands_to_send.append(
                    (
                        "water hardness",
                        lambda: client.set_dishwasher_water_hardness(new_hardness),
                    )
                )
            if status is None or new_buzzer != status.buzzer:
                commands_to_send.append(
                    ("buzzer", lambda: client.set_dishwasher_buzzer(new_buzzer))
                )
            if status is None or new_memo != status.remember_last_cycle:
                commands_to_send.append(
                    (
                        "remember last cycle",
                        lambda: client.set_dishwasher_remember_last_cycle(new_memo),
                    )
                )

            if commands_to_send:
                domain_data = self.hass.data.setdefault(DOMAIN, {}).setdefault(
                    self.config_entry.entry_id, {}
                )
                domain_data[DATA_KEY_WRITE_PENDING] = (
                    domain_data.get(DATA_KEY_WRITE_PENDING, 0) + 1
                )
                try:
                    for idx, (label, cmd_fn) in enumerate(commands_to_send):
                        if idx > 0:
                            await asyncio.sleep(5)
                        try:
                            await cmd_fn()
                        except Exception as err:
                            _LOGGER.warning(
                                "Failed to send %s setting to dishwasher: %s",
                                label,
                                err,
                            )
                    await asyncio.sleep(5)
                finally:
                    domain_data[DATA_KEY_WRITE_PENDING] -= 1

        self._pending_data = dict(self.config_entry.data)
        self._pending_data[CONF_KEY_WATER_HARDNESS] = new_hardness
        self._pending_data[CONF_KEY_DISHWASHER_BUZZER] = new_buzzer
        self._pending_data[CONF_KEY_DISHWASHER_REMEMBER_LAST_CYCLE] = new_memo

        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self._pending_data
        )
        if coord is not None:
            res = coord.async_request_refresh()
            if asyncio.iscoroutine(res):
                await res
        return self.async_create_entry(data={})

    async def async_step_maintenance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether maintenance counters are enabled."""
        if user_input is None:
            current = self.config_entry.data.get(CONF_KEY_MAINTENANCE_ENABLED, False)
            return self.async_show_form(
                step_id="maintenance",
                data_schema=vol.Schema(
                    {vol.Required(CONF_KEY_MAINTENANCE_ENABLED, default=current): bool}
                ),
            )
        self._pending_data = dict(self.config_entry.data)
        self._pending_data[CONF_KEY_MAINTENANCE_ENABLED] = user_input[
            CONF_KEY_MAINTENANCE_ENABLED
        ]
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        is_dryer = self.config_entry.data.get(CONF_KEY_IS_TUMBLE_DRYER, False)
        can_checkup = self.config_entry.data.get(
            CONF_KEY_MODE
        ) == MODE_FULL_CONTROL and supports_scheduled_checkup(interface_type, is_dryer)
        if not user_input[CONF_KEY_MAINTENANCE_ENABLED]:
            if can_checkup:
                return await self.async_step_checkup()
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=self._pending_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id)
            )
            return self.async_create_entry(data={})
        if is_dualtech(self._pending_data.get(CONF_KEY_INTERFACE_TYPE, "")):
            if can_checkup:
                return await self.async_step_checkup()
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=self._pending_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id)
            )
            return self.async_create_entry(data={})
        return await self.async_step_maintenance_types()

    async def async_step_maintenance_types(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which optional counters to enable (limescale, filter)."""
        if user_input is None:
            ls_current = self.config_entry.data.get(
                CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True
            )
            ft_current = self.config_entry.data.get(
                CONF_KEY_MAINTENANCE_FILTER_ENABLED, True
            )
            return self.async_show_form(
                step_id="maintenance_types",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, default=ls_current
                        ): bool,
                        vol.Required(
                            CONF_KEY_MAINTENANCE_FILTER_ENABLED, default=ft_current
                        ): bool,
                    }
                ),
            )
        self._pending_data[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED] = user_input[
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED
        ]
        self._pending_data[CONF_KEY_MAINTENANCE_FILTER_ENABLED] = user_input[
            CONF_KEY_MAINTENANCE_FILTER_ENABLED
        ]
        if self._is_dishwasher():
            if (
                CONF_KEY_WATER_HARDNESS not in self._pending_data
                and user_input[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED]
            ):
                return await self.async_step_hardness()
            return await self.async_step_maintenance_baselines()
        if user_input[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED]:
            return await self.async_step_hardness()
        return await self.async_step_maintenance_baselines()

    async def async_step_hardness(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for water hardness level."""
        if user_input is None:
            current = self.config_entry.data.get(CONF_KEY_WATER_HARDNESS, 2)
            interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
            schema = _hardness_schema(
                current=current,
                is_dishwasher=self._is_dishwasher(),
                interface_type=interface_type,
            )
            return self.async_show_form(step_id="hardness", data_schema=schema)
        self._pending_data[CONF_KEY_WATER_HARDNESS] = int(
            user_input[CONF_KEY_WATER_HARDNESS]
        )
        return await self.async_step_maintenance_baselines()

    async def async_step_maintenance_baselines(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for remaining cycles (what the app shows) for each enabled maintenance item."""
        hardness_index = self._pending_data.get(CONF_KEY_WATER_HARDNESS, 2)
        limescale_enabled = self._pending_data.get(
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True
        )
        filter_enabled = self._pending_data.get(
            CONF_KEY_MAINTENANCE_FILTER_ENABLED, True
        )

        if self._is_dishwasher():
            interface_type = self._pending_data.get(CONF_KEY_INTERFACE_TYPE, "")
            thresholds = (
                DISHWASHER_HARDNESS_THRESHOLDS_SMOOTH
                if is_dishwasher_digit_or_smooth_interface(interface_type)
                else DISHWASHER_HARDNESS_THRESHOLDS_LED
            )
            idx = min(hardness_index, len(thresholds) - 1)
            limescale_threshold = thresholds[idx]
            filter_threshold = DISHWASHER_MAINTENANCE_FILTER_THRESHOLD
        else:
            limescale_threshold = MAINTENANCE_HARDNESS_THRESHOLDS[hardness_index]
            filter_threshold = MAINTENANCE_FILTER_THRESHOLD

        # Read current total_cycles from the live stats coordinator if available
        total_cycles: int = 0
        stats_data = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get(DATA_KEY_STATS_COORDINATOR)
        )
        if stats_data is not None and stats_data.data is not None:
            total_cycles = stats_data.data.total_cycles

        if user_input is None:
            last_sc = self.config_entry.data.get(
                CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP, 0
            )
            last_ls = self.config_entry.data.get(CONF_KEY_MAINTENANCE_LAST_LIMESCALE, 0)
            last_ft = self.config_entry.data.get(CONF_KEY_MAINTENANCE_LAST_FILTER, 0)
            entry_id = self.config_entry.entry_id
            if total_cycles:
                sc_default = cycles_remaining(
                    total_cycles, last_sc, MAINTENANCE_FULL_CHECKUP_THRESHOLD
                )
                ls_default = cycles_remaining(
                    total_cycles, last_ls, limescale_threshold
                )
                ft_default = cycles_remaining(total_cycles, last_ft, filter_threshold)
            else:
                if self._is_dishwasher():
                    uid_sc = UNIQUE_ID_DISHWASHER_MAINT_FULL_CHECKUP
                    uid_ls = UNIQUE_ID_DISHWASHER_MAINT_LIMESCALE
                    uid_ft = UNIQUE_ID_DISHWASHER_MAINT_FILTER
                else:
                    uid_sc = UNIQUE_ID_WASH_MAINT_FULL_CHECKUP
                    uid_ls = UNIQUE_ID_WASH_MAINT_LIMESCALE
                    uid_ft = UNIQUE_ID_WASH_MAINT_FILTER
                current_sc = _current_remaining_cycles(self.hass, entry_id, uid_sc)
                current_ls = _current_remaining_cycles(self.hass, entry_id, uid_ls)
                current_ft = _current_remaining_cycles(self.hass, entry_id, uid_ft)
                sc_default = (
                    current_sc
                    if current_sc is not None
                    else MAINTENANCE_FULL_CHECKUP_THRESHOLD
                )
                ls_default = (
                    current_ls if current_ls is not None else limescale_threshold
                )
                ft_default = current_ft if current_ft is not None else filter_threshold
            fields: dict[vol.Required, type] = {
                vol.Required(
                    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP, default=sc_default
                ): int,
            }
            if limescale_enabled:
                fields[
                    vol.Required(
                        CONF_KEY_MAINTENANCE_LAST_LIMESCALE, default=ls_default
                    )
                ] = int
            if filter_enabled:
                fields[
                    vol.Required(CONF_KEY_MAINTENANCE_LAST_FILTER, default=ft_default)
                ] = int
            return self.async_show_form(
                step_id="maintenance_baselines",
                data_schema=vol.Schema(fields),
            )
        self._pending_data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = (
            _remaining_to_last_reset(
                user_input[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP],
                total_cycles,
                MAINTENANCE_FULL_CHECKUP_THRESHOLD,
            )
        )
        if limescale_enabled:
            self._pending_data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] = (
                _remaining_to_last_reset(
                    user_input[CONF_KEY_MAINTENANCE_LAST_LIMESCALE],
                    total_cycles,
                    limescale_threshold,
                )
            )
        if filter_enabled:
            self._pending_data[CONF_KEY_MAINTENANCE_LAST_FILTER] = (
                _remaining_to_last_reset(
                    user_input[CONF_KEY_MAINTENANCE_LAST_FILTER],
                    total_cycles,
                    filter_threshold,
                )
            )
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        is_dryer = self.config_entry.data.get(CONF_KEY_IS_TUMBLE_DRYER, False)
        if self.config_entry.data.get(
            CONF_KEY_MODE
        ) == MODE_FULL_CONTROL and supports_scheduled_checkup(interface_type, is_dryer):
            return await self.async_step_checkup()
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self._pending_data
        )
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(data={})

    async def async_step_checkup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether automatic self check-up should be enabled."""
        if not self._pending_data:
            self._pending_data = dict(self.config_entry.data)
        if user_input is None:
            current = self._pending_data.get(
                CONF_KEY_CHECKUP_ENABLED,
                self.config_entry.data.get(CONF_KEY_CHECKUP_ENABLED, False),
            )
            return self.async_show_form(
                step_id="checkup",
                data_schema=vol.Schema(
                    {vol.Required(CONF_KEY_CHECKUP_ENABLED, default=current): bool}
                ),
            )
        self._pending_data[CONF_KEY_CHECKUP_ENABLED] = user_input[
            CONF_KEY_CHECKUP_ENABLED
        ]
        if not user_input[CONF_KEY_CHECKUP_ENABLED]:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=self._pending_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.config_entry.entry_id)
            )
            return self.async_create_entry(data={})
        return await self.async_step_checkup_schedule()

    async def async_step_checkup_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how often the automatic check-up should run."""
        if user_input is None:
            current = self._pending_data.get(
                CONF_KEY_CHECKUP_SCHEDULE,
                self.config_entry.data.get(
                    CONF_KEY_CHECKUP_SCHEDULE, CHECKUP_SCHEDULE_EVERY_CYCLE
                ),
            )
            return self.async_show_form(
                step_id="checkup_schedule",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_KEY_CHECKUP_SCHEDULE, default=str(current)
                        ): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    str(CHECKUP_SCHEDULE_EVERY_CYCLE),
                                    str(CHECKUP_SCHEDULE_WEEKLY),
                                    str(CHECKUP_SCHEDULE_MONTHLY),
                                ],
                                mode=SelectSelectorMode.LIST,
                                translation_key="checkup_schedule",
                            )
                        ),
                    }
                ),
            )
        self._pending_data[CONF_KEY_CHECKUP_SCHEDULE] = int(
            user_input[CONF_KEY_CHECKUP_SCHEDULE]
        )
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self._pending_data
        )
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(data={})

    async def async_step_update_cloud_data(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show Simply-Fi credentials form and upgrade/refresh Full Control on submit."""
        if user_input is None:
            return self.async_show_form(
                step_id="update_cloud_data", data_schema=CLOUD_SCHEMA
            )

        errors: dict[str, str] = {}
        try:
            async with async_timeout.timeout(30):
                appliance = await fetch_appliance_data(
                    session=async_get_clientsession(self.hass),
                    email=user_input["email"],
                    password=user_input["password"],
                    device_ip=self.config_entry.data[CONF_IP_ADDRESS],
                )
        except SimplyFiCloudError as err:
            _LOGGER.warning("Simply-Fi cloud fetch failed in options flow: %s", err)
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="update_cloud_data", data_schema=CLOUD_SCHEMA, errors=errors
            )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error in options flow cloud fetch")
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="update_cloud_data", data_schema=CLOUD_SCHEMA, errors=errors
            )

        self._pending_data = apply_cloud_appliance_data(
            dict(self.config_entry.data),
            appliance,
            is_washing_machine=self._is_washing_machine(),
            is_tumble_dryer=self._is_tumble_dryer(),
            is_dishwasher=self._is_dishwasher(),
        )
        return await self.async_step_language()

    async def async_step_language(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which language to use for program names and appliance messages."""
        if user_input is None:
            current_lang = self._pending_data.get(
                CONF_KEY_PROGRAM_LANGUAGE,
                self.config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, "en"),
            )
            return self.async_show_form(
                step_id="language",
                data_schema=_language_schema(current_lang),
            )

        self._pending_data[CONF_KEY_PROGRAM_LANGUAGE] = user_input[
            CONF_KEY_PROGRAM_LANGUAGE
        ]
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self._pending_data
        )
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(data={})

    async def async_step_switch_to_read_only(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Downgrade to Read-Only: remove write entities and clear cloud data."""
        if user_input is None:
            return self.async_show_form(
                step_id="switch_to_read_only", data_schema=vol.Schema({})
            )

        new_data = dict(self.config_entry.data)
        new_data[CONF_KEY_MODE] = MODE_READ_ONLY
        if is_washer_dryer(self.config_entry, None):
            new_data[CONF_KEY_IS_WASHER_DRYER] = True
        new_data.pop(CONF_KEY_PROGRAMS, None)
        new_data.pop(CONF_KEY_DOWNLOADABLE_PROGRAMS, None)

        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        return self.async_create_entry(data={})


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Candy."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow handler."""
        return OptionsFlowHandler()

    def __init__(self) -> None:
        """Initialise config flow."""
        self._discovered: dict[str, str] = {}  # ip -> device type label
        self._ip_address: str = ""
        self._config_data: dict[str, Any] = {}  # accumulated config entry data
        self._is_reconfigure: bool = False
        self._is_washing_machine: bool = False
        self._is_tumble_dryer: bool = False
        self._is_dishwasher: bool = False
        self._dishwasher_status: DishwasherStatus | None = None
        self._total_cycles: int = (
            0  # fetched once after device probe; used for baselines
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle entry reconfiguration to upgrade to Full Control or refresh cloud data."""
        entry = self._get_reconfigure_entry()
        self._is_reconfigure = True
        self._ip_address = entry.data[CONF_IP_ADDRESS]
        self._config_data = dict(entry.data)

        self._is_washing_machine = entry.data.get(CONF_KEY_IS_WASHING_MACHINE, False)
        self._is_tumble_dryer = entry.data.get(CONF_KEY_IS_TUMBLE_DRYER, False)
        self._is_dishwasher = entry.data.get(CONF_KEY_IS_DISHWASHER, False)

        if not (
            self._is_washing_machine or self._is_tumble_dryer or self._is_dishwasher
        ):
            registry = er.async_get(self.hass)
            self._is_washing_machine = (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, UNIQUE_ID_WASHING_MACHINE.format(entry.entry_id)
                )
                is not None
            )
            self._is_tumble_dryer = (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, UNIQUE_ID_TUMBLE_DRYER.format(entry.entry_id)
                )
                is not None
            )
            self._is_dishwasher = (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, UNIQUE_ID_DISHWASHER.format(entry.entry_id)
                )
                is not None
            )

        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=CLOUD_SCHEMA,
            )

        return await self.async_step_cloud(user_input)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — try auto-discovery first."""
        if user_input is None:
            try:
                session = async_get_clientsession(self.hass)
                source_ip = await async_get_source_ip(self.hass)
                if source_ip:
                    subnet = _get_local_subnet(source_ip)
                    async with async_timeout.timeout(15):
                        self._discovered = await discover_devices(session, subnet)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("LAN discovery failed, falling back to manual entry")
                self._discovered = {}

            if self._discovered:
                return await self.async_step_select()

        return await self._handle_manual_ip(user_input)

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a discovered device or choose manual entry."""
        if user_input is not None:
            selected = user_input[CONF_IP_ADDRESS]
            if selected == MANUAL_IP_OPTION:
                return self.async_show_form(
                    step_id="user", data_schema=STEP_DATA_SCHEMA
                )
            return await self._configure_local(selected)

        options = {ip: f"{ip} — {label}" for ip, label in self._discovered.items()}
        options[MANUAL_IP_OPTION] = "Enter IP address manually"

        select_schema = vol.Schema({vol.Required(CONF_IP_ADDRESS): vol.In(options)})
        return self.async_show_form(step_id="select", data_schema=select_schema)

    async def _handle_manual_ip(
        self, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Process a manually entered IP address."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_DATA_SCHEMA)

        errors: dict[str, str] = {}
        try:
            result = await self._configure_local(user_input[CONF_IP_ADDRESS])
        except Exception:  # pylint: disable=broad-except
            errors["base"] = "detect_encryption"
        else:
            return result

        return self.async_show_form(
            step_id="user", data_schema=STEP_DATA_SCHEMA, errors=errors
        )

    async def _configure_local(self, ip: str) -> ConfigFlowResult:
        """Detect encryption for the device and advance to mode selection."""
        errors: dict[str, str] = {}

        try:
            async with async_timeout.timeout(40):
                encryption_type, key = await detect_encryption(
                    session=async_get_clientsession(self.hass),
                    device_ip=ip,
                )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Failed to detect encryption")
            errors["base"] = "detect_encryption"
            return self.async_show_form(
                step_id="user", data_schema=STEP_DATA_SCHEMA, errors=errors
            )

        self._ip_address = ip
        self._config_data = {CONF_IP_ADDRESS: ip}

        if encryption_type == Encryption.ENCRYPTION:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = True
            self._config_data[CONF_PASSWORD] = key
        elif encryption_type == Encryption.NO_ENCRYPTION:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = False
        elif encryption_type == Encryption.ENCRYPTION_WITHOUT_KEY:
            self._config_data[CONF_KEY_USE_ENCRYPTION] = True
            self._config_data[CONF_PASSWORD] = ""

        try:
            client = CandyClient(
                session=async_get_clientsession(self.hass),
                device_ip=ip,
                encryption_key=self._config_data.get(CONF_PASSWORD, "") or "",
                use_encryption=self._config_data.get(CONF_KEY_USE_ENCRYPTION, False),
                interface_type="",
            )
            async with async_timeout.timeout(10):
                status = await client.status()
            self._is_washing_machine = isinstance(status, WashingMachineStatus)
            self._is_tumble_dryer = isinstance(status, TumbleDryerStatus)
            if isinstance(status, DishwasherStatus):
                self._is_dishwasher = True
                self._dishwasher_status = status
            else:
                self._is_dishwasher = False
            if self._is_washing_machine:
                try:
                    async with async_timeout.timeout(20):
                        stats = await client.statistics_with_retry()
                    self._total_cycles = stats.total_cycles
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.debug(
                        "Statistics fetch failed during setup, defaulting total_cycles to 0"
                    )
                    self._total_cycles = 0
        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug("Device type probe failed, assuming non-controllable machine")
            self._is_washing_machine = False
            self._is_tumble_dryer = False
            self._is_dishwasher = False

        if self._is_washing_machine:
            self._config_data[CONF_KEY_IS_WASHING_MACHINE] = True
        if self._is_tumble_dryer:
            self._config_data[CONF_KEY_IS_TUMBLE_DRYER] = True
        if self._is_dishwasher:
            self._config_data[CONF_KEY_IS_DISHWASHER] = True

        return await self.async_step_mode()

    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user whether they want Read-Only or Full Control mode."""
        if not (
            self._is_washing_machine or self._is_tumble_dryer or self._is_dishwasher
        ):
            self._config_data[CONF_KEY_MODE] = MODE_READ_ONLY
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )

        if user_input is None:
            return self.async_show_form(step_id="mode", data_schema=MODE_SCHEMA)

        mode = user_input[CONF_KEY_MODE]
        self._config_data[CONF_KEY_MODE] = mode

        if mode == MODE_FULL_CONTROL:
            return await self.async_step_cloud()

        # Read-only washing machine: ask whether appliance is a washer-dryer
        if self._is_washing_machine:
            return await self.async_step_washer_dryer()

        if self._is_dishwasher:
            self._config_data[CONF_KEY_PROGRAMS] = DEFAULT_DISHWASHER_PROGRAMS
            interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
            if not is_legacy_dishwasher(interface_type):
                return await self.async_step_maintenance()
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )

        return self.async_create_entry(
            title=CONF_INTEGRATION_TITLE, data=self._config_data
        )

    async def async_step_washer_dryer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether the appliance is a washer-dryer in Read-Only mode."""
        if user_input is None:
            return self.async_show_form(
                step_id="washer_dryer",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_KEY_IS_WASHER_DRYER,
                            default=False,
                        ): bool,
                    }
                ),
            )
        is_wd = bool(user_input[CONF_KEY_IS_WASHER_DRYER])
        self._config_data[CONF_KEY_IS_WASHER_DRYER] = is_wd
        self._config_data[CONF_KEY_APPLIANCE_TYPE] = (
            "washer_dryer" if is_wd else "washer"
        )
        return await self.async_step_maintenance()

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect Simply-Fi credentials and fetch appliance data from cloud."""
        step_id = "reconfigure" if self._is_reconfigure else "cloud"
        if user_input is None:
            return self.async_show_form(step_id=step_id, data_schema=CLOUD_SCHEMA)

        errors: dict[str, str] = {}
        try:
            async with async_timeout.timeout(30):
                appliance = await fetch_appliance_data(
                    session=async_get_clientsession(self.hass),
                    email=user_input["email"],
                    password=user_input["password"],
                    device_ip=self._ip_address,
                )
        except SimplyFiCloudError as err:
            _LOGGER.warning("Simply-Fi cloud fetch failed: %s", err)
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id=step_id, data_schema=CLOUD_SCHEMA, errors=errors
            )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error during Simply-Fi cloud fetch")
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id=step_id, data_schema=CLOUD_SCHEMA, errors=errors
            )

        if self._is_reconfigure:
            self._config_data[CONF_KEY_MODE] = MODE_FULL_CONTROL
            if self._is_washing_machine:
                self._config_data[CONF_KEY_IS_WASHING_MACHINE] = True
            if self._is_tumble_dryer:
                self._config_data[CONF_KEY_IS_TUMBLE_DRYER] = True
            if self._is_dishwasher:
                self._config_data[CONF_KEY_IS_DISHWASHER] = True

        # Credentials are NOT stored — only the fetched appliance data
        # Device transport (encryption mode and local key) is detected and verified
        # during local setup; do not overwrite working local transport with cloud keys.
        if (
            CONF_KEY_USE_ENCRYPTION not in self._config_data
            and appliance.encryption_key
        ):
            self._config_data[CONF_KEY_USE_ENCRYPTION] = True
            self._config_data[CONF_PASSWORD] = appliance.encryption_key
        if appliance.mac_address:
            self._config_data[CONF_KEY_MAC_ADDRESS] = appliance.mac_address
        if appliance.appliance_model:
            self._config_data[CONF_KEY_DEVICE_MODEL] = appliance.appliance_model
        if appliance.serial_number:
            self._config_data[CONF_KEY_SERIAL_NUMBER] = appliance.serial_number
        if appliance.purchase_date:
            self._config_data[CONF_KEY_PURCHASE_DATE] = appliance.purchase_date
        self._config_data[CONF_KEY_PROGRAMS] = appliance.programs
        self._config_data[CONF_KEY_DOWNLOADABLE_PROGRAMS] = (
            appliance.downloadable_programs
        )
        if appliance.interface_type:
            self._config_data[CONF_KEY_INTERFACE_TYPE] = appliance.interface_type
        if appliance.brand:
            self._config_data[CONF_KEY_BRAND] = appliance.brand
        if appliance.appliance_type:
            self._config_data[CONF_KEY_APPLIANCE_TYPE] = appliance.appliance_type
            if appliance.appliance_type == "washer_dryer":
                self._config_data[CONF_KEY_IS_WASHER_DRYER] = True
        elif not self._is_tumble_dryer and appliance.programs:
            try:
                parsed = parse_wash_programs(appliance.programs)
                if any(
                    p.program_type in ("D", "WD") or p.selector_position_dry is not None
                    for p in parsed
                ):
                    self._config_data[CONF_KEY_IS_WASHER_DRYER] = True
            except (KeyError, TypeError, ValueError):
                pass
        if self._is_dishwasher and not appliance.programs:
            self._config_data[CONF_KEY_PROGRAMS] = DEFAULT_DISHWASHER_PROGRAMS
        if self._is_tumble_dryer:
            if not is_dualtech_dryer(appliance.interface_type):
                _LOGGER.warning(
                    "Tumble dryer interface '%s' is not supported in Full Control mode; setting mode to Read-Only",
                    appliance.interface_type,
                )
                self._config_data[CONF_KEY_MODE] = MODE_READ_ONLY

        return await self.async_step_language()

    async def async_step_language(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which language to use for program names and appliance messages."""
        if user_input is None:
            existing = self._config_data.get(CONF_KEY_PROGRAM_LANGUAGE)
            default_lang = existing or (
                self.hass.config.language
                if self.hass.config.language in PROGRAM_LANGUAGES
                else "en"
            )
            return self.async_show_form(
                step_id="language",
                data_schema=_language_schema(default_lang),
            )

        self._config_data[CONF_KEY_PROGRAM_LANGUAGE] = user_input[
            CONF_KEY_PROGRAM_LANGUAGE
        ]
        if self._is_reconfigure:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                data=self._config_data,
            )
        if self._is_dishwasher:
            interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
            if not is_legacy_dishwasher(interface_type):
                return await self.async_step_dishwasher_settings()
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )
        if self._is_tumble_dryer:
            interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
            if self._config_data.get(
                CONF_KEY_MODE
            ) == MODE_FULL_CONTROL and supports_scheduled_checkup(interface_type, True):
                return await self.async_step_checkup()
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )
        return await self.async_step_maintenance()

    async def async_step_dishwasher_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for dishwasher hardware settings during onboarding."""
        interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
        if user_input is None:
            cur_hardness = (
                self._dishwasher_status.water_hardness
                if self._dishwasher_status
                and self._dishwasher_status.water_hardness is not None
                else 2
            )
            cur_buzzer = (
                self._dishwasher_status.buzzer
                if self._dishwasher_status
                and self._dishwasher_status.buzzer is not None
                else True
            )
            cur_memo = (
                self._dishwasher_status.remember_last_cycle
                if self._dishwasher_status
                and self._dishwasher_status.remember_last_cycle is not None
                else True
            )
            return self.async_show_form(
                step_id="dishwasher_settings",
                data_schema=_dishwasher_settings_schema(
                    interface_type=interface_type,
                    default_hardness=cur_hardness,
                    default_buzzer=cur_buzzer,
                    default_remember_last_cycle=cur_memo,
                ),
            )

        new_hardness = int(user_input[CONF_KEY_WATER_HARDNESS])
        new_buzzer = bool(user_input[CONF_KEY_DISHWASHER_BUZZER])
        new_memo = bool(user_input[CONF_KEY_DISHWASHER_REMEMBER_LAST_CYCLE])

        self._config_data[CONF_KEY_WATER_HARDNESS] = new_hardness
        self._config_data[CONF_KEY_DISHWASHER_BUZZER] = new_buzzer
        self._config_data[CONF_KEY_DISHWASHER_REMEMBER_LAST_CYCLE] = new_memo

        if (
            self._dishwasher_status is not None
            and self._config_data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL
            and (
                new_hardness != self._dishwasher_status.water_hardness
                or new_buzzer != self._dishwasher_status.buzzer
                or new_memo != self._dishwasher_status.remember_last_cycle
            )
        ):
            try:
                client = CandyClient(
                    session=async_get_clientsession(self.hass),
                    device_ip=self._ip_address,
                    encryption_key=self._config_data.get(CONF_PASSWORD, "") or "",
                    use_encryption=self._config_data.get(
                        CONF_KEY_USE_ENCRYPTION, False
                    ),
                    interface_type=self._config_data.get(CONF_KEY_INTERFACE_TYPE, ""),
                )
                commands_to_send: list[
                    tuple[str, Callable[[], Coroutine[Any, Any, None]]]
                ] = []
                if new_hardness != self._dishwasher_status.water_hardness:
                    commands_to_send.append(
                        (
                            "water hardness",
                            lambda: client.set_dishwasher_water_hardness(new_hardness),
                        )
                    )
                if new_buzzer != self._dishwasher_status.buzzer:
                    commands_to_send.append(
                        (
                            "buzzer",
                            lambda: client.set_dishwasher_buzzer(new_buzzer),
                        )
                    )
                if new_memo != self._dishwasher_status.remember_last_cycle:
                    commands_to_send.append(
                        (
                            "remember last cycle",
                            lambda: client.set_dishwasher_remember_last_cycle(new_memo),
                        )
                    )
                for idx, (label, cmd_fn) in enumerate(commands_to_send):
                    if idx > 0:
                        await asyncio.sleep(5)
                    try:
                        await cmd_fn()
                    except Exception as err:
                        _LOGGER.warning(
                            "Failed to dispatch initial %s setting to dishwasher: %s",
                            label,
                            err,
                        )
                if commands_to_send:
                    await asyncio.sleep(5)
            except Exception as err:
                _LOGGER.warning(
                    "Failed to dispatch initial dishwasher settings to appliance: %s",
                    err,
                )

        interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
        if supports_dishwasher_statistics(interface_type):
            return await self.async_step_maintenance()
        return self.async_create_entry(
            title=CONF_INTEGRATION_TITLE, data=self._config_data
        )

    async def async_step_maintenance(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether maintenance counters should be enabled."""
        if user_input is None:
            return self.async_show_form(
                step_id="maintenance", data_schema=MAINTENANCE_ENABLE_SCHEMA
            )
        self._config_data[CONF_KEY_MAINTENANCE_ENABLED] = user_input[
            CONF_KEY_MAINTENANCE_ENABLED
        ]
        interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
        can_checkup = self._config_data.get(
            CONF_KEY_MODE
        ) == MODE_FULL_CONTROL and supports_scheduled_checkup(
            interface_type, self._is_tumble_dryer
        )
        if not user_input[CONF_KEY_MAINTENANCE_ENABLED]:
            if can_checkup:
                return await self.async_step_checkup()
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )
        if is_dualtech(interface_type):
            if can_checkup:
                return await self.async_step_checkup()
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )
        return await self.async_step_maintenance_types()

    async def async_step_maintenance_types(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which optional counters to enable (limescale, filter)."""
        if user_input is None:
            return self.async_show_form(
                step_id="maintenance_types",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, default=True
                        ): bool,
                        vol.Required(
                            CONF_KEY_MAINTENANCE_FILTER_ENABLED, default=True
                        ): bool,
                    }
                ),
            )
        self._config_data[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED] = user_input[
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED
        ]
        self._config_data[CONF_KEY_MAINTENANCE_FILTER_ENABLED] = user_input[
            CONF_KEY_MAINTENANCE_FILTER_ENABLED
        ]
        if self._is_dishwasher:
            if (
                CONF_KEY_WATER_HARDNESS not in self._config_data
                and user_input[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED]
            ):
                return await self.async_step_hardness()
            return await self.async_step_maintenance_baselines()
        if user_input[CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED]:
            return await self.async_step_hardness()
        return await self.async_step_maintenance_baselines()

    async def async_step_hardness(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for water hardness level."""
        if user_input is None:
            current = self._config_data.get(CONF_KEY_WATER_HARDNESS, 2)
            interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
            schema = _hardness_schema(
                current=current,
                is_dishwasher=self._is_dishwasher,
                interface_type=interface_type,
            )
            return self.async_show_form(step_id="hardness", data_schema=schema)
        self._config_data[CONF_KEY_WATER_HARDNESS] = int(
            user_input[CONF_KEY_WATER_HARDNESS]
        )
        return await self.async_step_maintenance_baselines()

    async def async_step_maintenance_baselines(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for remaining cycles (what the app shows) for each enabled maintenance item."""
        hardness_index = self._config_data.get(CONF_KEY_WATER_HARDNESS, 2)
        limescale_enabled = self._config_data.get(
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True
        )
        filter_enabled = self._config_data.get(
            CONF_KEY_MAINTENANCE_FILTER_ENABLED, True
        )

        if self._is_dishwasher:
            interface_type = self._config_data.get(CONF_KEY_INTERFACE_TYPE, "")
            thresholds = (
                DISHWASHER_HARDNESS_THRESHOLDS_SMOOTH
                if is_dishwasher_digit_or_smooth_interface(interface_type)
                else DISHWASHER_HARDNESS_THRESHOLDS_LED
            )
            idx = min(hardness_index, len(thresholds) - 1)
            limescale_threshold = thresholds[idx]
            filter_threshold = DISHWASHER_MAINTENANCE_FILTER_THRESHOLD
        else:
            limescale_threshold = MAINTENANCE_HARDNESS_THRESHOLDS[hardness_index]
            filter_threshold = MAINTENANCE_FILTER_THRESHOLD

        if user_input is None:
            return self.async_show_form(
                step_id="maintenance_baselines",
                data_schema=_baselines_schema(
                    total_cycles=self._total_cycles,
                    limescale_enabled=limescale_enabled,
                    filter_enabled=filter_enabled,
                    limescale_threshold=limescale_threshold,
                    filter_threshold=filter_threshold,
                ),
            )
        self._config_data[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP] = (
            _remaining_to_last_reset(
                user_input[CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP],
                self._total_cycles,
                MAINTENANCE_FULL_CHECKUP_THRESHOLD,
            )
        )
        if limescale_enabled:
            self._config_data[CONF_KEY_MAINTENANCE_LAST_LIMESCALE] = (
                _remaining_to_last_reset(
                    user_input[CONF_KEY_MAINTENANCE_LAST_LIMESCALE],
                    self._total_cycles,
                    limescale_threshold,
                )
            )
        if filter_enabled:
            self._config_data[CONF_KEY_MAINTENANCE_LAST_FILTER] = (
                _remaining_to_last_reset(
                    user_input[CONF_KEY_MAINTENANCE_LAST_FILTER],
                    self._total_cycles,
                    filter_threshold,
                )
            )
        if self._config_data.get(
            CONF_KEY_MODE
        ) == MODE_FULL_CONTROL and supports_scheduled_checkup(
            self._config_data.get(CONF_KEY_INTERFACE_TYPE, ""),
            self._is_tumble_dryer,
        ):
            return await self.async_step_checkup()
        return self.async_create_entry(
            title=CONF_INTEGRATION_TITLE, data=self._config_data
        )

    async def async_step_checkup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether automatic self check-up should be enabled."""
        if user_input is None:
            return self.async_show_form(
                step_id="checkup", data_schema=CHECKUP_ENABLE_SCHEMA
            )
        self._config_data[CONF_KEY_CHECKUP_ENABLED] = user_input[
            CONF_KEY_CHECKUP_ENABLED
        ]
        if not user_input[CONF_KEY_CHECKUP_ENABLED]:
            return self.async_create_entry(
                title=CONF_INTEGRATION_TITLE, data=self._config_data
            )
        return await self.async_step_checkup_schedule()

    async def async_step_checkup_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how often the automatic check-up should run."""
        if user_input is None:
            return self.async_show_form(
                step_id="checkup_schedule", data_schema=CHECKUP_SCHEDULE_SCHEMA
            )
        self._config_data[CONF_KEY_CHECKUP_SCHEDULE] = int(
            user_input[CONF_KEY_CHECKUP_SCHEDULE]
        )
        return self.async_create_entry(
            title=CONF_INTEGRATION_TITLE, data=self._config_data
        )
