from __future__ import annotations

from typing import cast

from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import (
    CandyClient,
    DownloadableProgram,
    TumbleDryerProgram,
    WasherDryerDryTarget,
    WashingMachineStatus,
    WashingMachineWashProgram,
    load_downloadable_programs,
    parse_dryer_programs,
    parse_wash_programs,
    resolve_downloadable_programs,
)
from .client.model import MachineState, TumbleDryerStatus
from .const import (
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DOMAIN,
    DRY_LEVEL_FROM_VALUE,
    DRY_LEVEL_HANG,
    DRY_LEVEL_OPTIONS,
    DRY_LEVEL_TO_VALUE,
    DRY_TARGET_CUPBOARD_DRY,
    DRY_TARGET_NO_DRY,
    DRY_TARGET_OPTIONS_FULL,
    DRY_TARGET_OPTIONS_ONLY_DRY,
    FLANGIA_PROGRAMS_TO_HIDE,
    MODE_FULL_CONTROL,
    PROGRAM_TYPE_DRYING,
    PROGRAM_TYPE_WASH_AND_DRY,
    PROGRAM_TYPE_WASHING,
    PROGRAM_TYPES,
    RAPID_LEVEL_TO_VALUE,
    SOIL_LABELS,
    UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT,
    UNIQUE_ID_TUMBLE_PROGRAM_SELECT,
    UNIQUE_ID_TUMBLE_RAPID_SELECT,
    UNIQUE_ID_TUMBLE_TIME_SELECT,
    UNIQUE_ID_WASH_DRY_SELECT,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_PROGRAM_DESCRIPTION,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_TEMP_SELECT,
    UNIQUE_ID_WASH_WATER_HARDNESS,
    WATER_HARDNESS_FROM_VALUE,
    WATER_HARDNESS_OPTIONS,
    WATER_HARDNESS_TO_VALUE,
)
from .helpers import (
    dryer_device_info,
    is_dualtech,
    is_washer_dryer,
    remote_control_enabled,
    supports_autodose,
    wash_device_info,
)

_TEMP_STEPS = [0, 20, 30, 40, 60, 90]
_BASE_EVEN_SPIN_STEPS: tuple[int, ...] = (0, 400, 600, 800, 1000, 1200, 1400, 1600)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
) -> None:
    config_id = config_entry.entry_id

    if config_entry.data.get(CONF_KEY_MODE) != MODE_FULL_CONTROL:
        return

    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][config_id][
        DATA_KEY_COORDINATOR
    ]
    if isinstance(coordinator.data, TumbleDryerStatus):
        dryer_client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
        raw_programs = config_entry.data.get(CONF_KEY_PROGRAMS, [])
        dryer_programs = parse_dryer_programs(raw_programs)
        if not dryer_programs:
            return

        level_select = CandyDryerLevelSelect(
            coordinator, config_entry, dryer_client, dryer_programs
        )
        time_select = CandyDryerTimeSelect(
            coordinator, config_entry, dryer_client, dryer_programs
        )
        rapid_select = CandyDryerRapidSelect(
            coordinator, config_entry, dryer_client, dryer_programs
        )
        dryer_program_select = CandyDryerProgramSelect(
            coordinator,
            config_entry,
            dryer_client,
            dryer_programs,
            level_select,
            time_select,
            rapid_select,
        )
        async_add_entities(
            [dryer_program_select, level_select, time_select, rapid_select]
        )
        return

    if not isinstance(coordinator.data, WashingMachineStatus):
        return

    client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
    programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))

    raw_dl = config_entry.data.get(CONF_KEY_DOWNLOADABLE_PROGRAMS, [])
    nfc_entries = resolve_downloadable_programs(
        load_downloadable_programs(raw_dl), programs
    )

    is_wd = is_washer_dryer(config_entry, programs)

    type_select: CandyWashProgramTypeSelect | None = None
    dry_select: CandyWashDrySelect | None = None
    if is_wd:
        type_select = CandyWashProgramTypeSelect(
            coordinator, config_entry, client, programs
        )
        dry_select = CandyWashDrySelect(
            coordinator, config_entry, client, programs, type_select
        )

    temp_select = WashTempSelect(coordinator, config_entry, client, programs)
    spin_select = WashSpinSelect(coordinator, config_entry, client, programs)
    soil_select = WashSoilSelect(coordinator, config_entry, client, programs)
    description_sensor = CandyWashProgramDescriptionSensor(coordinator, config_entry)
    program_select = WashProgramSelect(
        coordinator,
        config_entry,
        client,
        programs,
        temp_select,
        spin_select,
        soil_select,
        description_sensor,
        nfc_entries,
        type_select,
        dry_select,
    )

    entities: list[SelectEntity | SensorEntity] = [
        program_select,
        temp_select,
        spin_select,
        soil_select,
        description_sensor,
    ]
    if type_select is not None:
        type_select.set_program_select(program_select)
        type_select.set_dry_select(dry_select)
        entities.insert(0, type_select)
    if dry_select is not None:
        dry_select.set_program_select(program_select)
        entities.append(dry_select)

    interface_type = config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
    if supports_autodose(interface_type):
        entities.append(CandyWashWaterHardnessSelect(coordinator, config_entry, client))

    async_add_entities(entities)


class CandyWashSelectBase(CoordinatorEntity, SelectEntity):
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

    def _program_name(self, program: WashingMachineWashProgram) -> str:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        return program.localized_name(lang)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and remote_control_enabled(self.coordinator.data)

    def _current_program(self) -> WashingMachineWashProgram | None:
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

    def _machine_is_idle(self) -> bool:
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state in {MachineState.IDLE, MachineState.OFF}


class CandyWashProgramTypeSelect(CandyWashSelectBase):
    _attr_has_entity_name = True
    _attr_name = "Program type"
    _attr_translation_key = "wash_program_type"
    _attr_icon = "mdi:tune-vertical"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._current_option: str | None = None
        self._program_select: WashProgramSelect | None = None
        self._dry_select: CandyWashDrySelect | None = None

    def set_program_select(self, program_select: WashProgramSelect) -> None:
        self._program_select = program_select

    def set_dry_select(self, dry_select: CandyWashDrySelect | None) -> None:
        self._dry_select = dry_select

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(self.config_id)

    @property
    def available(self) -> bool:
        return super().available and self._machine_is_idle()

    @property
    def options(self) -> list[str]:
        return PROGRAM_TYPES

    @property
    def current_option(self) -> str:
        if not self._machine_is_idle():
            prog = self._current_program()
            if prog is not None:
                if prog.is_dry:
                    return PROGRAM_TYPE_DRYING
                if prog.program_type == "WD":
                    return PROGRAM_TYPE_WASH_AND_DRY
                status = cast(WashingMachineStatus, self.coordinator.data)
                if (
                    status.dry_target is not None
                    and status.dry_target != WasherDryerDryTarget.NO_DRY
                ):
                    return PROGRAM_TYPE_WASH_AND_DRY
            return PROGRAM_TYPE_WASHING

        if self._current_option is not None:
            return self._current_option

        prog = self._current_program()
        if prog is not None:
            if prog.is_dry:
                return PROGRAM_TYPE_DRYING
            if prog.program_type == "WD":
                return PROGRAM_TYPE_WASH_AND_DRY
            status = cast(WashingMachineStatus, self.coordinator.data)
            if (
                status.dry_target is not None
                and status.dry_target != WasherDryerDryTarget.NO_DRY
            ):
                return PROGRAM_TYPE_WASH_AND_DRY
        return PROGRAM_TYPE_WASHING

    async def async_select_option(self, option: str) -> None:
        if option not in PROGRAM_TYPES:
            raise ValueError(f"Invalid program type: {option}")
        self._current_option = option
        self.async_write_ha_state()
        if self._program_select is not None:
            await self._program_select.async_update_for_program_type(option)
        elif self._dry_select is not None:
            self._dry_select.update_for_program_type(option)


class CandyWashDrySelect(CandyWashSelectBase):
    _attr_has_entity_name = True
    _attr_name = "Dry setting"
    _attr_translation_key = "wash_dry_select"
    _attr_icon = "mdi:tumble-dryer"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
        type_select: CandyWashProgramTypeSelect | None,
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._type_select = type_select
        self._program_select: WashProgramSelect | None = None
        self._current_option: str | None = None
        self._selected_program: WashingMachineWashProgram | None = None

    def set_program_select(self, program_select: WashProgramSelect) -> None:
        self._program_select = program_select

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DRY_SELECT.format(self.config_id)

    @property
    def available(self) -> bool:
        return super().available and self._machine_is_idle()

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._selected_program is not None:
            return self._selected_program
        if (
            self._program_select is not None
            and self._program_select.current_option is not None
        ):
            for p in self._programs:
                if self._program_name(p) == self._program_select.current_option:
                    return p
        return self._current_program()

    def _active_program_type(self) -> str:
        if self._type_select is not None:
            return self._type_select.current_option
        prog = self._active_program()
        if prog is not None:
            if prog.is_dry:
                return PROGRAM_TYPE_DRYING
            if prog.is_wash_and_dry:
                return PROGRAM_TYPE_WASH_AND_DRY
        return PROGRAM_TYPE_WASHING

    @property
    def options(self) -> list[str]:
        current_type = self._active_program_type()
        if current_type == PROGRAM_TYPE_WASHING:
            return [DRY_TARGET_NO_DRY]
        if current_type == PROGRAM_TYPE_DRYING:
            return list(DRY_TARGET_OPTIONS_ONLY_DRY)
        prog = self._active_program()
        if prog is not None and not prog.dry_supported:
            return [DRY_TARGET_NO_DRY]
        return list(DRY_TARGET_OPTIONS_FULL)

    @property
    def current_option(self) -> str | None:
        opts = self.options
        if not self._machine_is_idle():
            status = cast(WashingMachineStatus, self.coordinator.data)
            if (
                status.dry_target is not None
                and status.dry_target != WasherDryerDryTarget.COOLDOWN
            ):
                if status.dry_target.label in opts:
                    return status.dry_target.label
            return (
                DRY_TARGET_NO_DRY
                if DRY_TARGET_NO_DRY in opts
                else (opts[0] if opts else None)
            )

        if self._current_option is not None and self._current_option in opts:
            return self._current_option

        status = cast(WashingMachineStatus, self.coordinator.data)
        if (
            status.dry_target is not None
            and status.dry_target != WasherDryerDryTarget.COOLDOWN
        ):
            if status.dry_target.label in opts:
                return status.dry_target.label

        current_type = self._active_program_type()
        if current_type == PROGRAM_TYPE_WASHING:
            return DRY_TARGET_NO_DRY
        if current_type in (PROGRAM_TYPE_WASH_AND_DRY, PROGRAM_TYPE_DRYING):
            if DRY_TARGET_CUPBOARD_DRY in opts:
                return DRY_TARGET_CUPBOARD_DRY
        return opts[0] if opts else None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Invalid dry target: {option}")
        self._current_option = option
        self.async_write_ha_state()

    def update_for_program(self, program: WashingMachineWashProgram | None) -> None:
        self._selected_program = program
        opts = self.options
        if self._current_option not in opts:
            if DRY_TARGET_CUPBOARD_DRY in opts:
                self._current_option = DRY_TARGET_CUPBOARD_DRY
            elif DRY_TARGET_NO_DRY in opts:
                self._current_option = DRY_TARGET_NO_DRY
            elif opts:
                self._current_option = opts[0]
            else:
                self._current_option = None
        self.async_write_ha_state()

    def update_for_program_type(self, program_type: str) -> None:
        opts = self.options
        if program_type == PROGRAM_TYPE_WASHING:
            self._current_option = DRY_TARGET_NO_DRY
        elif program_type in (PROGRAM_TYPE_WASH_AND_DRY, PROGRAM_TYPE_DRYING):
            if (
                self._current_option is None
                or self._current_option == DRY_TARGET_NO_DRY
                or self._current_option not in opts
            ):
                self._current_option = (
                    DRY_TARGET_CUPBOARD_DRY
                    if DRY_TARGET_CUPBOARD_DRY in opts
                    else opts[0]
                )
        elif self._current_option not in opts:
            self._current_option = opts[0] if opts else None
        self.async_write_ha_state()


class WashProgramSelect(CandyWashSelectBase):
    _attr_name = "Wash program"
    _attr_translation_key = "wash_program_select"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
        temp_select: WashTempSelect,
        spin_select: WashSpinSelect,
        soil_select: WashSoilSelect,
        description_sensor: CandyWashProgramDescriptionSensor,
        nfc_entries: list[tuple[DownloadableProgram, WashingMachineWashProgram]],
        type_select: CandyWashProgramTypeSelect | None,
        dry_select: CandyWashDrySelect | None,
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._temp_select = temp_select
        self._spin_select = spin_select
        self._soil_select = soil_select
        self._description_sensor = description_sensor
        self._nfc_entries = nfc_entries
        self._type_select = type_select
        self._dry_select = dry_select
        self._current_option: str | None = None

    def _nfc_enabled(self) -> bool:
        registry = er.async_get(self.hass)
        nfc_switch_id = registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(self.config_id)
        )
        if nfc_switch_id is None:
            return False
        state = self.hass.states.get(nfc_switch_id)
        return state is not None and state.state == "on"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"

    @property
    def available(self) -> bool:
        return super().available and self._machine_is_idle()

    def _is_flangia_hidden(self, program: WashingMachineWashProgram) -> bool:
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        return (
            is_dualtech(interface_type)
            and program.name.upper() in FLANGIA_PROGRAMS_TO_HIDE
        )

    @property
    def options(self) -> list[str]:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        current_type = (
            self._type_select.current_option
            if self._type_select is not None
            else PROGRAM_TYPE_WASHING
        )

        if current_type == PROGRAM_TYPE_DRYING:
            return [
                self._program_name(p)
                for p in self._programs
                if p.is_dry and not self._is_flangia_hidden(p)
            ]

        if current_type == PROGRAM_TYPE_WASH_AND_DRY:
            return [
                self._program_name(p)
                for p in self._programs
                if p.is_wash_and_dry
                and "autoclean" not in p.name.lower()
                and not self._is_flangia_hidden(p)
            ]

        standard = [
            self._program_name(p)
            for p in self._programs
            if p.is_wash
            and "autoclean" not in p.name.lower()
            and not self._is_flangia_hidden(p)
        ]
        if not self._nfc_enabled():
            return standard
        nfc = sorted(nfc.category_prefixed(lang) for nfc, _ in self._nfc_entries)
        return standard + nfc

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            if self._current_option in self.options:
                return self._current_option
            self._current_option = None
        prog = self._current_program()
        if prog is not None:
            name = self._program_name(prog)
            if name in self.options:
                return name
        opts = self.options
        return opts[0] if opts else None

    async def async_update_for_program_type(self, program_type: str) -> None:
        opts = self.options
        if opts and (self._current_option not in opts):
            await self.async_select_option(opts[0])
        else:
            self.async_write_ha_state()
            if self._dry_select is not None:
                self._dry_select.update_for_program_type(program_type)

    @property
    def extra_state_attributes(self) -> dict | None:
        option = self.current_option
        if option is None:
            return None
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        nfc_match = next(
            (
                (nfc, base)
                for nfc, base in self._nfc_entries
                if nfc.category_prefixed(lang) == option
            ),
            None,
        )
        if nfc_match is not None:
            nfc, base = nfc_match
            duration = base.duration_for_soil(nfc.resolve_soil_target(base))
            if duration:
                return {"duration_minutes": duration}
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        nfc_match = next(
            (
                nfc
                for nfc, _ in self._nfc_entries
                if nfc.category_prefixed(lang) == option
            ),
            None,
        )
        if nfc_match is not None:
            self._temp_select.update_for_program(nfc_match)
            self._spin_select.update_for_program(None)
            self._soil_select.update_for_program(None)
            self._description_sensor.update_for_program(nfc_match)
            if self._dry_select is not None:
                self._dry_select.update_for_program(None)
        else:
            selected = next(
                (p for p in self._programs if self._program_name(p) == option), None
            )
            if selected is not None:
                self._temp_select.reset_for_standard_program(selected)
                self._spin_select.update_for_program(selected)
                self._soil_select.update_for_program(selected)
                self._description_sensor.reset_for_standard_program(selected)
                if self._dry_select is not None:
                    self._dry_select.update_for_program(selected)
            else:
                self._description_sensor.reset_for_standard_program(None)
                if self._dry_select is not None:
                    self._dry_select.update_for_program(None)
        self.async_write_ha_state()
        self._temp_select.async_write_ha_state()
        self._spin_select.async_write_ha_state()
        self._soil_select.async_write_ha_state()
        self._description_sensor.async_write_ha_state()


class CandyWashProgramDescriptionSensor(CoordinatorEntity, SensorEntity):
    """Read-only sensor showing the description of the selected downloadable program."""

    _attr_name = "Program description"
    _attr_translation_key = "wash_program_description"
    _attr_should_poll = False
    _description: str | None = None

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PROGRAM_DESCRIPTION.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and self._description is not None

    @property
    def native_value(self) -> str | None:
        return self._description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._seed_from_coordinator()

    def _handle_coordinator_update(self) -> None:
        if self._description is None:
            self._seed_from_coordinator()
        super()._handle_coordinator_update()

    def _seed_from_coordinator(self) -> None:
        if not isinstance(self.coordinator.data, WashingMachineStatus):
            return
        status = cast(WashingMachineStatus, self.coordinator.data)
        lang = self.config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, "en")
        if status.recipe_id and status.recipe_id not in ("0", ""):
            dl_programs = load_downloadable_programs(
                self.config_entry.data.get(CONF_KEY_DOWNLOADABLE_PROGRAMS, [])
            )
            for dl in dl_programs:
                if (
                    dl.recipe_id == status.recipe_id
                    or str(dl.position) == status.recipe_id
                ):
                    self._description = self._truncate(dl.description(lang))
                    return
        programs = parse_wash_programs(
            self.config_entry.data.get(CONF_KEY_PROGRAMS, [])
        )
        if status.program_code is not None:
            for p in programs:
                if (
                    p.selector_position == status.program
                    and p.pr_code == status.program_code
                ):
                    self._description = self._truncate(p.localized_description(lang))
                    return
        for p in programs:
            if p.selector_position == status.program:
                self._description = self._truncate(p.localized_description(lang))
                return

    @staticmethod
    def _truncate(value: str | None) -> str | None:
        return value[:255] if value is not None else None

    def update_for_program(self, program: DownloadableProgram | None) -> None:
        lang = self.config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, "en")
        raw = program.description(lang) if program is not None else None
        self._description = self._truncate(raw)

    def reset_for_standard_program(
        self, program: WashingMachineWashProgram | None
    ) -> None:
        if program is None:
            self._description = None
            return
        lang = self.config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, "en")
        self._description = self._truncate(program.localized_description(lang))


class WashTempSelect(CandyWashSelectBase):
    _attr_name = "Wash temperature"
    _attr_translation_key = "wash_temp_select"
    _current_option: str | None = None
    _selected_program: WashingMachineWashProgram | None = None
    _nfc_active: bool = False
    _nfc_temp: int | None = (
        None  # fixed temperature for the active downloadable program
    )

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_TEMP_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:thermometer"

    @property
    def available(self) -> bool:
        if self._nfc_active:
            return (
                super().available
                and self._machine_is_idle()
                and self._nfc_temp is not None
            )
        prog = self._active_program()
        return (
            super().available
            and self._machine_is_idle()
            and prog is not None
            and prog.max_temperature != 255
        )

    @property
    def options(self) -> list[str]:
        if self._nfc_active:
            return [str(self._nfc_temp)] if self._nfc_temp is not None else []
        prog = self._active_program()
        if prog is None or prog.max_temperature == 255:
            return []
        return [str(t) for t in _TEMP_STEPS if t <= prog.max_temperature]

    @property
    def current_option(self) -> str | None:
        if self._nfc_active:
            return str(self._nfc_temp) if self._nfc_temp is not None else None
        if self._current_option is not None:
            return self._current_option
        prog = self._active_program()
        if prog is None or prog.max_temperature == 255:
            return None
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.temp)

    def update_for_program(self, program: DownloadableProgram | None) -> None:
        self._nfc_active = True
        self._selected_program = None
        self._current_option = None
        self._nfc_temp = program.temperature if program is not None else None

    def reset_for_standard_program(self, program: WashingMachineWashProgram) -> None:
        self._nfc_active = False
        self._nfc_temp = None
        self._selected_program = program
        self._current_option = str(program.default_temperature)

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._selected_program is not None:
            return self._selected_program
        return self._current_program()

    async def async_select_option(self, option: str) -> None:
        if self._nfc_active:
            return
        self._current_option = option
        self.async_write_ha_state()


class WashSpinSelect(CandyWashSelectBase):
    _attr_name = "Wash spin speed"
    _attr_translation_key = "wash_spin_select"
    _current_option: str | None = None
    _selected_program: WashingMachineWashProgram | None = None
    _nfc_active: bool = False

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        valid_max_spins = [
            p.max_spin_speed for p in programs if p.max_spin_speed not in (0, 255)
        ]
        appliance_max = max(valid_max_spins, default=1400)
        catalog_spins = {
            s
            for p in programs
            for s in (p.default_spin_speed, p.max_spin_speed)
            if s not in (0, 255) and s <= appliance_max
        }
        special_catalog_spins = {s for s in catalog_spins if s % 200 != 0}
        base_steps = {s for s in _BASE_EVEN_SPIN_STEPS if s <= appliance_max}
        self._appliance_spin_steps: list[int] = sorted(
            base_steps | special_catalog_spins
        )

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SPIN_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:rotate-right"

    @property
    def available(self) -> bool:
        if self._nfc_active:
            return False
        prog = self._active_program()
        return (
            super().available
            and self._machine_is_idle()
            and prog is not None
            and prog.max_spin_speed != 255
        )

    @property
    def options(self) -> list[str]:
        prog = self._active_program()
        if prog is None or prog.max_spin_speed == 255:
            return []
        return [str(s) for s in self._appliance_spin_steps if s <= prog.max_spin_speed]

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._active_program()
        if prog is None or prog.max_spin_speed == 255:
            return None
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.spin_speed)

    def update_for_program(self, program: WashingMachineWashProgram | None) -> None:
        self._nfc_active = program is None
        self._selected_program = program
        self._current_option = (
            str(program.default_spin_speed) if program is not None else None
        )

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._selected_program is not None:
            return self._selected_program
        return self._current_program()

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class WashSoilSelect(CandyWashSelectBase):
    _attr_name = "Wash stain level"
    _attr_translation_key = "wash_soil_select"
    _current_option: str | None = None
    _selected_program: WashingMachineWashProgram | None = None
    _nfc_active: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SOIL_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:water-opacity"

    @property
    def available(self) -> bool:
        if self._nfc_active:
            return False
        prog = self._active_program()
        if prog is None:
            return False
        return (
            super().available
            and self._machine_is_idle()
            and prog.min_soil_level < prog.max_soil_level
        )

    @property
    def options(self) -> list[str]:
        prog = self._active_program()
        if prog is None or prog.min_soil_level >= prog.max_soil_level:
            return []
        return [
            SOIL_LABELS[i]
            for i in range(prog.min_soil_level, prog.max_soil_level + 1)
            if i in SOIL_LABELS
        ]

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._active_program()
        if prog is None or prog.min_soil_level >= prog.max_soil_level:
            return None
        status = cast(WashingMachineStatus, self.coordinator.data)
        if (
            status.soil_level is not None
            and prog.min_soil_level <= status.soil_level <= prog.max_soil_level
        ):
            return SOIL_LABELS.get(status.soil_level)
        return SOIL_LABELS.get(prog.default_soil_level)

    def update_for_program(self, program: WashingMachineWashProgram | None) -> None:
        self._nfc_active = program is None
        self._selected_program = program
        if program is not None and program.min_soil_level < program.max_soil_level:
            self._current_option = SOIL_LABELS.get(program.default_soil_level)
        else:
            self._current_option = None

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._selected_program is not None:
            return self._selected_program
        return self._current_program()

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class CandyDryerLevelSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "dryer_level_select"
    _attr_icon = "mdi:weather-sunny"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[TumbleDryerProgram],
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._programs = programs
        self._selected_program: TumbleDryerProgram = programs[0]
        self._current_option: str | None = (
            DRY_LEVEL_FROM_VALUE.get(
                self._selected_program.default_drying_level, DRY_LEVEL_HANG
            )
            if self._selected_program.set_dry_level
            else None
        )

    def _machine_is_idle(self) -> bool:
        status = self.coordinator.data
        if not isinstance(status, TumbleDryerStatus):
            return False
        return (
            status.machine_state
            in (
                MachineState.IDLE,
                MachineState.FINISHED1,
                MachineState.FINISHED2,
            )
            and status.remote_control
        )

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return dryer_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and self._machine_is_idle() and bool(self.options)

    @property
    def options(self) -> list[str]:
        if self._selected_program.set_dry_level:
            return DRY_LEVEL_OPTIONS
        return []

    @property
    def current_option(self) -> str | None:
        if self._current_option in self.options:
            return self._current_option
        opts = self.options
        return opts[0] if opts else None

    @property
    def selected_level(self) -> int:
        opt = self.current_option
        return DRY_LEVEL_TO_VALUE.get(
            opt or "", self._selected_program.default_drying_level
        )

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Invalid dry level: {option}")
        self._current_option = option
        self.async_write_ha_state()

    def update_for_program(self, program: TumbleDryerProgram) -> None:
        self._selected_program = program
        opts = self.options
        if not opts:
            self._current_option = None
        else:
            default_lvl = DRY_LEVEL_FROM_VALUE.get(program.default_drying_level)
            if default_lvl and default_lvl in opts:
                self._current_option = default_lvl
            else:
                self._current_option = opts[0]
        self.async_write_ha_state()


class CandyDryerTimeSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "dryer_time_select"
    _attr_icon = "mdi:timer-outline"

    _TIME_OPTIONS = ["off", "30", "45", "60", "90", "120"]

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[TumbleDryerProgram],
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._programs = programs
        self._selected_program: TumbleDryerProgram = programs[0]
        if not self._selected_program.set_time_level:
            self._current_option: str | None = None
        elif not self._selected_program.set_dry_level:
            default_t = str(self._selected_program.default_time_level)
            self._current_option = (
                default_t
                if default_t in self._TIME_OPTIONS and default_t != "off"
                else "30"
            )
        else:
            self._current_option = "off"

    def _machine_is_idle(self) -> bool:
        status = self.coordinator.data
        if not isinstance(status, TumbleDryerStatus):
            return False
        return (
            status.machine_state
            in (
                MachineState.IDLE,
                MachineState.FINISHED1,
                MachineState.FINISHED2,
            )
            and status.remote_control
        )

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_TIME_SELECT.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return dryer_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._machine_is_idle()
            and self._selected_program.set_time_level
        )

    @property
    def options(self) -> list[str]:
        if not self._selected_program.set_time_level:
            return []
        if not self._selected_program.set_dry_level:
            return [opt for opt in self._TIME_OPTIONS if opt != "off"]
        return self._TIME_OPTIONS

    @property
    def current_option(self) -> str | None:
        if self._current_option in self.options:
            return self._current_option
        opts = self.options
        return opts[0] if opts else None

    @property
    def selected_time_minutes(self) -> int:
        opt = self.current_option
        if opt is None or opt == "off" or not opt.isdigit():
            return 0
        return int(opt)

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Invalid drying time: {option}")
        self._current_option = option
        self.async_write_ha_state()

    def update_for_program(self, program: TumbleDryerProgram) -> None:
        self._selected_program = program
        opts = self.options
        if not program.set_time_level:
            self._current_option = None
        elif not program.set_dry_level:
            default_t = str(program.default_time_level)
            if default_t in opts:
                self._current_option = default_t
            elif opts:
                self._current_option = opts[0]
            else:
                self._current_option = None
        else:
            self._current_option = "off"
        self.async_write_ha_state()


class CandyDryerRapidSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "dryer_rapid_select"
    _attr_icon = "mdi:lightning-bolt-outline"

    _RAPID_OPTIONS = ["off", "30", "45", "59"]

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[TumbleDryerProgram],
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._programs = programs
        self._selected_program: TumbleDryerProgram = programs[0]
        self._current_option: str | None = (
            "off" if self._selected_program.set_rapido else None
        )

    def _machine_is_idle(self) -> bool:
        status = self.coordinator.data
        if not isinstance(status, TumbleDryerStatus):
            return False
        return (
            status.machine_state
            in (
                MachineState.IDLE,
                MachineState.FINISHED1,
                MachineState.FINISHED2,
            )
            and status.remote_control
        )

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_RAPID_SELECT.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return dryer_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._machine_is_idle()
            and self._selected_program.set_rapido
        )

    @property
    def options(self) -> list[str]:
        if not self._selected_program.set_rapido:
            return []
        return self._RAPID_OPTIONS

    @property
    def current_option(self) -> str | None:
        if self._current_option in self.options:
            return self._current_option
        opts = self.options
        return opts[0] if opts else None

    @property
    def selected_rapid_level(self) -> int:
        opt = self.current_option
        if opt is None or opt == "off":
            return 0
        return RAPID_LEVEL_TO_VALUE.get(opt, 0)

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Invalid rapid dry option: {option}")
        self._current_option = option
        self.async_write_ha_state()

    def update_for_program(self, program: TumbleDryerProgram) -> None:
        self._selected_program = program
        if not program.set_rapido:
            self._current_option = None
        else:
            self._current_option = "off"
        self.async_write_ha_state()


class CandyDryerProgramSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "dryer_program_select"
    _attr_icon = "mdi:tumble-dryer"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[TumbleDryerProgram],
        level_select: CandyDryerLevelSelect,
        time_select: CandyDryerTimeSelect,
        rapid_select: CandyDryerRapidSelect,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._programs = programs
        self._level_select = level_select
        self._time_select = time_select
        self._rapid_select = rapid_select
        lang = config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, "en")
        self._current_option: str = programs[0].localized_name(lang)

    def _machine_is_idle(self) -> bool:
        status = self.coordinator.data
        if not isinstance(status, TumbleDryerStatus):
            return False
        return (
            status.machine_state
            in (
                MachineState.IDLE,
                MachineState.FINISHED1,
                MachineState.FINISHED2,
            )
            and status.remote_control
        )

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_PROGRAM_SELECT.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return dryer_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and self._machine_is_idle()

    @property
    def options(self) -> list[str]:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        return [p.localized_name(lang) for p in self._programs]

    @property
    def current_option(self) -> str:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        if not self._machine_is_idle():
            status = cast(TumbleDryerStatus, self.coordinator.data)
            match = next(
                (p for p in self._programs if p.selector_position == status.program),
                None,
            )
            if match is not None:
                return match.localized_name(lang)

        if self._current_option in self.options:
            return self._current_option
        return self.options[0] if self.options else ""

    @property
    def selected_program(self) -> TumbleDryerProgram:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        cur = self.current_option
        match = next(
            (p for p in self._programs if p.localized_name(lang) == cur),
            None,
        )
        return match if match is not None else self._programs[0]

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Invalid dryer program: {option}")
        self._current_option = option
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        match = next(
            (p for p in self._programs if p.localized_name(lang) == option),
            None,
        )
        if match is not None:
            self._level_select.update_for_program(match)
            self._time_select.update_for_program(match)
            self._rapid_select.update_for_program(match)
        self.async_write_ha_state()


class CandyWashWaterHardnessSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "wash_water_hardness"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:water-opacity"
    _attr_options = WATER_HARDNESS_OPTIONS

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._client = client
        self._attr_unique_id = UNIQUE_ID_WASH_WATER_HARDNESS.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def available(self) -> bool:
        return super().available and remote_control_enabled(self.coordinator.data)

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.water_hardness is None:
            return None
        return WATER_HARDNESS_FROM_VALUE.get(status.water_hardness)

    async def async_select_option(self, option: str) -> None:
        if option not in WATER_HARDNESS_TO_VALUE:
            raise ValueError(f"Invalid water hardness option: {option}")
        level = WATER_HARDNESS_TO_VALUE[option]
        await self._client.set_water_hardness(level)
        await self.coordinator.async_request_refresh()
