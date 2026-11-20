from __future__ import annotations

import functools
import operator
from typing import Any, cast

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import (
    CandyClient,
    DishwasherProgram,
    WashingMachineStatus,
    WashingMachineWashProgram,
    is_open_door_supported,
    parse_dish_programs,
    parse_wash_programs,
)
from .client.model import DishwasherStatus, MachineState
from .const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DEFAULT_DISHWASHER_PROGRAMS,
    DISHWASHER_PROGRAM_PANEL,
    DISHWASHER_PROGRAMS,
    DOMAIN,
    MODE_FULL_CONTROL,
    UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH,
    UNIQUE_ID_DISHWASHER_ECO_SWITCH,
    UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH,
    UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
    UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH,
    UNIQUE_ID_WASH_DETERGENT_AUTODOSE,
    UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SOFTENER_AUTODOSE,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    WASH_OPTIONS,
)
from .coordinator import CandyDataUpdateCoordinator
from .helpers import (
    dishwasher_device_info,
    remote_control_enabled,
    supports_autodose,
    wash_device_info,
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
) -> None:
    config_id = config_entry.entry_id
    coordinator: CandyDataUpdateCoordinator = hass.data[DOMAIN][config_id][
        DATA_KEY_COORDINATOR
    ]

    if isinstance(coordinator.data, DishwasherStatus):
        raw_programs = config_entry.data.get(CONF_KEY_PROGRAMS, [])
        dish_programs = (
            parse_dish_programs(raw_programs)
            if raw_programs
            else parse_dish_programs(DEFAULT_DISHWASHER_PROGRAMS)
        )
        interface_type = config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")

        switches: list[SwitchEntity] = [
            DishwasherEcoSwitch(coordinator, config_entry, dish_programs, 4),
            DishwasherThreeInOneSwitch(coordinator, config_entry, dish_programs, 8),
            DishwasherHalfLoadSwitch(coordinator, config_entry, dish_programs, 2),
            DishwasherExtraDrySwitch(coordinator, config_entry, dish_programs, 1),
        ]
        if is_open_door_supported(interface_type):
            switches.append(
                DishwasherAutoDoorSwitch(coordinator, config_entry, dish_programs, 16)
            )

        async_add_entities(switches)
        return

    if config_entry.data.get(CONF_KEY_MODE) != MODE_FULL_CONTROL:
        return

    if not isinstance(coordinator.data, WashingMachineStatus):
        return

    client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
    programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))

    entities: list[SwitchEntity] = []

    interface_type = config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
    if supports_autodose(interface_type):
        entities.extend(
            [
                WashDetergentAutoDoseSwitch(coordinator, config_entry, client),
                WashSoftenerAutoDoseSwitch(coordinator, config_entry, client),
                WashExtraDoseSwitch(coordinator, config_entry, client, programs),
            ]
        )

    if any(p.steam for p in programs):
        entities.append(WashSteamSwitch(coordinator, config_entry, client, programs))

    entities.append(
        NfcSpecialProgramsSwitch(coordinator, config_entry, client, programs)
    )

    appliance_options = functools.reduce(
        operator.or_, (p.available_options for p in programs), 0
    )
    for bitmask, translation_key, uid_suffix, name in WASH_OPTIONS:
        if appliance_options & bitmask:
            entities.append(
                WashOptionSwitch(
                    coordinator,
                    config_entry,
                    client,
                    programs,
                    bitmask,
                    translation_key,
                    uid_suffix,
                    name,
                )
            )

    async_add_entities(entities)


class _WashSwitchBase(CoordinatorEntity, SwitchEntity):
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._programs = programs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        registry = er.async_get(self.hass)
        target_unique_id = UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)

        @callback
        def _on_state_changed(event: Any) -> None:
            entity_id: str = event.data.get("entity_id", "")
            if not entity_id.startswith("select."):
                return
            entry = registry.async_get(entity_id)
            if entry is not None and entry.config_entry_id == self.config_id:
                if entry.unique_id == target_unique_id:
                    self._on_program_changed(event)

        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, _on_state_changed)
        )

    @callback
    def _on_program_changed(self, event) -> None:
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and remote_control_enabled(self.coordinator.data)

    def _active_program(self) -> WashingMachineWashProgram | None:
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)
        )
        if entity_id is not None:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in ("unavailable", "unknown"):
                return next(
                    (
                        p
                        for p in self._programs
                        if p.localized_name(
                            self.config_entry.data.get(
                                CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
                            )
                        )
                        == state.state
                    ),
                    None,
                )
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.program_code is not None:
            for p in self._programs:
                if (
                    p.selector_position == status.program
                    and p.pr_code == status.program_code
                ):
                    return p
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None


class WashSteamSwitch(_WashSwitchBase):
    _attr_name = "Wash steam"
    _attr_translation_key = "wash_steam_switch"
    _attr_icon = "mdi:weather-fog"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._steam_on: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)

    @callback
    def _on_program_changed(self, event) -> None:
        self._steam_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state not in {
            MachineState.IDLE,
            MachineState.OFF,
            MachineState.FINISHED1,
            MachineState.FINISHED2,
        }:
            return False
        prog = self._active_program()
        return prog is not None and prog.steam

    @property
    def is_on(self) -> bool:
        return self._steam_on

    async def async_turn_on(self, **kwargs) -> None:
        self._steam_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._steam_on = False
        self.async_write_ha_state()


class NfcSpecialProgramsSwitch(_WashSwitchBase):
    _attr_name = "Special programs"
    _attr_translation_key = "wash_nfc_switch"
    _attr_icon = "mdi:folder-star"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._is_on: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_NFC_SWITCH.format(self.config_id)

    @property
    def available(self) -> bool:
        return super().available

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()


class WashOptionSwitch(_WashSwitchBase):
    _attr_icon = "mdi:washing-machine"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
        bitmask: int,
        translation_key: str,
        uid_suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._bitmask = bitmask
        self._attr_translation_key = translation_key
        self._attr_name = name
        self._uid_suffix = uid_suffix
        self._is_on: bool = False

    @property
    def unique_id(self) -> str:
        return f"{self.config_id}-{self._uid_suffix}"

    @callback
    def _on_program_changed(self, event) -> None:
        self._is_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state not in {
            MachineState.IDLE,
            MachineState.OFF,
            MachineState.FINISHED1,
            MachineState.FINISHED2,
        }:
            return False
        prog = self._active_program()
        return prog is not None and bool(prog.available_options & self._bitmask)

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.async_write_ha_state()


class WashDetergentAutoDoseSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "wash_detergent_autodose"
    _attr_icon = "mdi:bottle-tonic-outline"

    def __init__(
        self,
        coordinator: CandyDataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
    ) -> None:
        super().__init__(coordinator)
        self.coordinator: CandyDataUpdateCoordinator = coordinator
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._attr_unique_id = UNIQUE_ID_WASH_DETERGENT_AUTODOSE.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and remote_control_enabled(self.coordinator.data)

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return bool(status.detergent_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_detergent_autodose(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_detergent_autodose(False)


class WashSoftenerAutoDoseSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "wash_softener_autodose"
    _attr_icon = "mdi:bottle-tonic-outline"

    def __init__(
        self,
        coordinator: CandyDataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
    ) -> None:
        super().__init__(coordinator)
        self.coordinator: CandyDataUpdateCoordinator = coordinator
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._attr_unique_id = UNIQUE_ID_WASH_SOFTENER_AUTODOSE.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and remote_control_enabled(self.coordinator.data)

    @property
    def is_on(self) -> bool:
        if self.coordinator.data is None:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return bool(status.softener_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_softener_autodose(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_softener_autodose(False)


class WashExtraDoseSwitch(_WashSwitchBase):
    _attr_has_entity_name = True
    _attr_translation_key = "wash_extra_dose"
    _attr_icon = "mdi:plus-circle-outline"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._is_on: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH.format(self.config_id)

    @callback
    def _on_program_changed(self, event) -> None:
        self._is_on = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state not in {
            MachineState.IDLE,
            MachineState.OFF,
            MachineState.FINISHED1,
            MachineState.FINISHED2,
        }:
            return False
        prog = self._active_program()
        # In Simply-Fi APK (AbProgramOptionsFragment.addExtraDose, classes*.dex), Extra Dose
        # is only offered if the selected program supports Prewash (available_options & 1).
        # On AutoDose models, extra dosing dispenses via the prewash hydraulic stage.
        return prog is not None and bool(prog.available_options & 1)

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        self.async_write_ha_state()


class _CandyDishwasherSwitchBase(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        programs: list[DishwasherProgram],
        bitmask: int,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._programs = programs
        self._bitmask = bitmask
        self._user_value: bool | None = None

    @property
    def status(self) -> DishwasherStatus:
        return cast(DishwasherStatus, self.coordinator.data)

    @property
    def device_info(self) -> DeviceInfo:
        return dishwasher_device_info(self.config_entry)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        target_unique_id = UNIQUE_ID_DISHWASHER_PROGRAM_SELECT.format(self.config_id)

        @callback
        def _on_state_changed(event: Any) -> None:
            entity_id: str = event.data.get("entity_id", "")
            if not entity_id.startswith("select."):
                return
            entry = registry.async_get(entity_id)
            if entry is not None and entry.config_entry_id == self.config_id:
                if entry.unique_id == target_unique_id:
                    self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_STATE_CHANGED, _on_state_changed)
        )

    def _active_program(self) -> DishwasherProgram | None:
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "select",
            DOMAIN,
            UNIQUE_ID_DISHWASHER_PROGRAM_SELECT.format(self.config_id),
        )
        if entity_id is not None:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in (
                "unavailable",
                "unknown",
                DISHWASHER_PROGRAM_PANEL,
            ):
                lang = self.config_entry.data.get(
                    CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
                )
                return next(
                    (
                        p
                        for p in self._programs
                        if p.localized_name(lang) == state.state
                        or p.name == state.state
                        or (
                            state.state in DISHWASHER_PROGRAMS
                            and f"P{p.cycle_id}" == DISHWASHER_PROGRAMS[state.state]
                        )
                    ),
                    None,
                )
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if not isinstance(self.coordinator.data, DishwasherStatus):
            return False
        if self.status.running:
            return False
        prog = self._active_program()
        if prog is not None and self._bitmask > 0:
            return (prog.available_options & self._bitmask) != 0
        return True

    def _panel_value(self) -> bool:
        raise NotImplementedError

    @property
    def is_on(self) -> bool:
        if self._user_value is not None:
            return self._user_value
        if not isinstance(self.coordinator.data, DishwasherStatus):
            return False
        return self._panel_value()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._user_value = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._user_value = False
        self.async_write_ha_state()


class DishwasherEcoSwitch(_CandyDishwasherSwitchBase):
    _attr_translation_key = "dishwasher_eco_switch"
    _attr_icon = "mdi:leaf"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_ECO_SWITCH.format(self.config_id)

    def _panel_value(self) -> bool:
        return self.status.eco_mode


class DishwasherThreeInOneSwitch(_CandyDishwasherSwitchBase):
    _attr_translation_key = "dishwasher_three_in_one_switch"
    _attr_icon = "mdi:pill"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH.format(self.config_id)

    def _panel_value(self) -> bool:
        return self.status.three_in_one


class DishwasherHalfLoadSwitch(_CandyDishwasherSwitchBase):
    _attr_translation_key = "dishwasher_half_load_switch"
    _attr_icon = "mdi:fraction-one-half"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH.format(self.config_id)

    def _panel_value(self) -> bool:
        return self.status.half_load


class DishwasherExtraDrySwitch(_CandyDishwasherSwitchBase):
    _attr_translation_key = "dishwasher_extra_dry_switch"
    _attr_icon = "mdi:weather-sunny"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH.format(self.config_id)

    def _panel_value(self) -> bool:
        return self.status.extra_dry


class DishwasherAutoDoorSwitch(_CandyDishwasherSwitchBase):
    _attr_translation_key = "dishwasher_auto_door_switch"
    _attr_icon = "mdi:door-open"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH.format(self.config_id)

    def _panel_value(self) -> bool:
        return bool(self.status.door_open_allowed)
