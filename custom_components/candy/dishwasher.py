"""Dishwasher controls: remote start/stop and the settings used by the next start.

Dishwashers need no cloud data: commands only require the local key, and the
machine itself gates them with the remote control switch on its panel.

Program and options are applied by the machine only together with
StartStop=1 (sending them alone is acknowledged but ignored), so the select,
switches and number below hold the settings for the next start in Home
Assistant and the start button sends them all at once.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote, urlencode

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import CandyClient
from .client.model import DishwasherStatus
from .const import (
    DATA_KEY_DISHWASHER_START_OPTIONS,
    DATA_KEY_WRITE_PENDING,
    DISHWASHER_PROGRAM_PANEL,
    DISHWASHER_PROGRAMS,
    DOMAIN,
    UNIQUE_ID_DISHWASHER_DELAY_NUMBER,
    UNIQUE_ID_DISHWASHER_DOOR,
    UNIQUE_ID_DISHWASHER_ECO_SWITCH,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
    UNIQUE_ID_DISHWASHER_REMOTE_CONTROL,
    UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY,
    UNIQUE_ID_DISHWASHER_SALT_EMPTY,
    UNIQUE_ID_DISHWASHER_START_BUTTON,
    UNIQUE_ID_DISHWASHER_STOP_BUTTON,
    UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH,
)
from .helpers import dishwasher_device_info

# The delay is sent in steps of 30 minutes and read back in minutes
_DELAY_STEP_MINUTES = 30
_DELAY_MAX_MINUTES = 24 * 60


@dataclass
class DishwasherStartOptions:
    """Settings for the next remote start. None means "as set on the panel"."""

    program: str = DISHWASHER_PROGRAM_PANEL
    eco: bool | None = None
    three_in_one: bool | None = None
    delay_minutes: int = 0


def dishwasher_start_command(
    status: DishwasherStatus, options: DishwasherStartOptions
) -> str:
    """Build the start command from the panel state and the chosen options."""
    if options.program == DISHWASHER_PROGRAM_PANEL:
        program = status.program
    else:
        program = DISHWASHER_PROGRAMS[options.program]
    option = "0"
    if program.endswith("+"):
        option = "p"
    elif program.endswith("-"):
        option = "m"
    eco = status.eco_mode if options.eco is None else options.eco
    three_in_one = (
        status.three_in_one if options.three_in_one is None else options.three_in_one
    )
    params = {
        "DelayStart": options.delay_minutes // _DELAY_STEP_MINUTES,
        "ExtraDry": int(status.extra_dry),
        "OpenDoorOpt": int(bool(status.door_open_allowed)),
        "TreinUno": int(three_in_one),
        "Eco": int(eco),
        "Program": program.rstrip("+-"),
        "MetaCarico": int(status.half_load),
        "OpzProg": option,
        "w1": 1,
        "StartStop": 1,
    }
    return urlencode(params, quote_via=quote)


def _start_options(entity: CoordinatorEntity, config_id: str) -> DishwasherStartOptions:
    return entity.hass.data[DOMAIN][config_id].setdefault(
        DATA_KEY_DISHWASHER_START_OPTIONS, DishwasherStartOptions()
    )


def dishwasher_buttons(
    coordinator: DataUpdateCoordinator, config_entry: ConfigEntry, client: CandyClient
) -> list[ButtonEntity]:
    return [
        DishwasherStartButton(coordinator, config_entry, client),
        DishwasherStopButton(coordinator, config_entry, client),
    ]


def dishwasher_selects(
    coordinator: DataUpdateCoordinator, config_entry: ConfigEntry
) -> list[SelectEntity]:
    return [DishwasherProgramSelect(coordinator, config_entry)]


def dishwasher_switches(
    coordinator: DataUpdateCoordinator, config_entry: ConfigEntry
) -> list[SwitchEntity]:
    return [
        DishwasherEcoSwitch(coordinator, config_entry),
        DishwasherThreeInOneSwitch(coordinator, config_entry),
    ]


def dishwasher_numbers(
    coordinator: DataUpdateCoordinator, config_entry: ConfigEntry
) -> list[NumberEntity]:
    return [DishwasherDelayNumber(coordinator, config_entry)]


def dishwasher_binary_sensors(
    coordinator: DataUpdateCoordinator, config_entry: ConfigEntry
) -> list[BinarySensorEntity]:
    return [
        DishwasherSaltEmptyBinarySensor(coordinator, config_entry),
        DishwasherRinseAidEmptyBinarySensor(coordinator, config_entry),
        DishwasherDoorBinarySensor(coordinator, config_entry),
        DishwasherRemoteControlBinarySensor(coordinator, config_entry),
    ]


class _DishwasherEntity(CoordinatorEntity):
    _unique_id_template: str

    def __init__(
        self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def status(self) -> DishwasherStatus:
        return cast(DishwasherStatus, self.coordinator.data)

    @property
    def unique_id(self) -> str:
        return self._unique_id_template.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return dishwasher_device_info(self.config_entry)


class _DishwasherSettingEntity(_DishwasherEntity):
    """Setting for the next start: editable only while the machine is idle."""

    @property
    def available(self) -> bool:
        return super().available and not self.status.running

    @property
    def start_options(self) -> DishwasherStartOptions:
        return _start_options(self, self.config_id)


class _DishwasherButton(_DishwasherEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
    ) -> None:
        super().__init__(coordinator, config_entry)
        self._client = client

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.hass.data[DOMAIN][self.config_id].get(DATA_KEY_WRITE_PENDING, 0)
            == 0
            and self.status.remote_control
        )

    async def _send_command_and_refresh(self, query_string: str) -> None:
        data = self.hass.data[DOMAIN][self.config_id]
        data[DATA_KEY_WRITE_PENDING] = data.get(DATA_KEY_WRITE_PENDING, 0) + 1
        self.coordinator.async_update_listeners()
        try:
            await self._client.send_command(query_string)
            await asyncio.sleep(5)
        except Exception:
            await asyncio.sleep(5)
            raise
        finally:
            data[DATA_KEY_WRITE_PENDING] -= 1
            if data[DATA_KEY_WRITE_PENDING] == 0:
                await self.coordinator.async_request_refresh()


class DishwasherStartButton(_DishwasherButton):
    _attr_name = "Start dishwasher"
    _attr_translation_key = "dishwasher_start_button"
    _attr_icon = "mdi:play-circle-outline"
    _unique_id_template = UNIQUE_ID_DISHWASHER_START_BUTTON

    @property
    def available(self) -> bool:
        # A pending delayed start also reports StartStop=1
        return (
            super().available and not self.status.running and not self.status.door_open
        )

    async def async_press(self) -> None:
        options = _start_options(self, self.config_id)
        await self._send_command_and_refresh(
            dishwasher_start_command(self.status, options)
        )
        # Never carry a delay over to the next start
        options.delay_minutes = 0
        self.coordinator.async_update_listeners()


class DishwasherStopButton(_DishwasherButton):
    _attr_name = "Stop dishwasher"
    _attr_translation_key = "dishwasher_stop_button"
    _attr_icon = "mdi:stop-circle-outline"
    _unique_id_template = UNIQUE_ID_DISHWASHER_STOP_BUTTON

    @property
    def available(self) -> bool:
        return super().available and self.status.running

    async def async_press(self) -> None:
        await self._send_command_and_refresh("Reset=1")


class DishwasherProgramSelect(_DishwasherSettingEntity, SelectEntity):
    _attr_name = "Dishwasher program to start"
    _attr_translation_key = "dishwasher_program_select"
    _attr_icon = "mdi:format-list-numbered"
    _attr_options = [DISHWASHER_PROGRAM_PANEL, *DISHWASHER_PROGRAMS]
    _unique_id_template = UNIQUE_ID_DISHWASHER_PROGRAM_SELECT

    @property
    def current_option(self) -> str:
        return self.start_options.program

    async def async_select_option(self, option: str) -> None:
        self.start_options.program = option
        self.async_write_ha_state()


class _DishwasherOptionSwitch(_DishwasherSettingEntity, SwitchEntity):
    """Option for the next start, following the panel until changed here."""

    _option: str

    def _panel_value(self) -> bool:
        raise NotImplementedError

    @property
    def is_on(self) -> bool:
        value = getattr(self.start_options, self._option)
        return self._panel_value() if value is None else value

    async def async_turn_on(self, **kwargs) -> None:
        setattr(self.start_options, self._option, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        setattr(self.start_options, self._option, False)
        self.async_write_ha_state()


class DishwasherEcoSwitch(_DishwasherOptionSwitch):
    _attr_name = "Dishwasher eco option"
    _attr_translation_key = "dishwasher_eco_switch"
    _attr_icon = "mdi:leaf"
    _option = "eco"
    _unique_id_template = UNIQUE_ID_DISHWASHER_ECO_SWITCH

    def _panel_value(self) -> bool:
        return self.status.eco_mode


class DishwasherThreeInOneSwitch(_DishwasherOptionSwitch):
    _attr_name = "Dishwasher 3in1 tablets"
    _attr_translation_key = "dishwasher_three_in_one_switch"
    _attr_icon = "mdi:pill"
    _option = "three_in_one"
    _unique_id_template = UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH

    def _panel_value(self) -> bool:
        return self.status.three_in_one


class DishwasherDelayNumber(_DishwasherSettingEntity, NumberEntity):
    _attr_name = "Dishwasher start delay"
    _attr_translation_key = "dishwasher_delay_number"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = _DELAY_MAX_MINUTES
    _attr_native_step = _DELAY_STEP_MINUTES
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _unique_id_template = UNIQUE_ID_DISHWASHER_DELAY_NUMBER

    @property
    def native_value(self) -> float:
        return self.start_options.delay_minutes

    async def async_set_native_value(self, value: float) -> None:
        minutes = int(value) // _DELAY_STEP_MINUTES * _DELAY_STEP_MINUTES
        self.start_options.delay_minutes = minutes
        self.async_write_ha_state()


class DishwasherSaltEmptyBinarySensor(_DishwasherEntity, BinarySensorEntity):
    _attr_name = "Dishwasher salt empty"
    _attr_translation_key = "dishwasher_salt_empty"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:shaker-outline"
    _unique_id_template = UNIQUE_ID_DISHWASHER_SALT_EMPTY

    @property
    def is_on(self) -> bool:
        return self.status.salt_empty


class DishwasherRinseAidEmptyBinarySensor(_DishwasherEntity, BinarySensorEntity):
    _attr_name = "Dishwasher rinse aid empty"
    _attr_translation_key = "dishwasher_rinse_aid_empty"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-outline"
    _unique_id_template = UNIQUE_ID_DISHWASHER_RINSE_AID_EMPTY

    @property
    def is_on(self) -> bool:
        return self.status.rinse_aid_empty


class DishwasherDoorBinarySensor(_DishwasherEntity, BinarySensorEntity):
    _attr_name = "Dishwasher door"
    _attr_translation_key = "dishwasher_door"
    _attr_device_class = BinarySensorDeviceClass.DOOR
    _unique_id_template = UNIQUE_ID_DISHWASHER_DOOR

    @property
    def is_on(self) -> bool:
        return self.status.door_open


class DishwasherRemoteControlBinarySensor(_DishwasherEntity, BinarySensorEntity):
    _attr_name = "Remote control"
    _attr_translation_key = "remote_control"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:remote"
    _unique_id_template = UNIQUE_ID_DISHWASHER_REMOTE_CONTROL

    @property
    def is_on(self) -> bool:
        return self.status.remote_control
