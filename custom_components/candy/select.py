from __future__ import annotations

from typing import cast

from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
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
    WashingMachineStatus,
    WashingMachineWashProgram,
    load_downloadable_programs,
    parse_wash_programs,
    resolve_downloadable_programs,
)
from .client.model import MachineState
from .const import (
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DOMAIN,
    DRY_LABELS,
    MODE_FULL_CONTROL,
    SOIL_LABELS,
    UNIQUE_ID_WASH_DRY_SELECT,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_PROGRAM_DESCRIPTION,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_TEMP_SELECT,
)
from .helpers import remote_control_enabled, wash_device_info

_TEMP_STEPS = [0, 20, 30, 40, 60, 90]
_SPIN_STEPS = [0, 400, 600, 800, 1000, 1200, 1400]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
) -> None:
    config_id = config_entry.entry_id

    if config_entry.data.get(CONF_KEY_MODE) != MODE_FULL_CONTROL:
        return

    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][config_id][
        DATA_KEY_COORDINATOR
    ]
    if not isinstance(coordinator.data, WashingMachineStatus):
        return

    client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
    programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))

    raw_dl = config_entry.data.get(CONF_KEY_DOWNLOADABLE_PROGRAMS, [])
    nfc_entries = resolve_downloadable_programs(
        load_downloadable_programs(raw_dl), programs
    )

    temp_select = WashTempSelect(coordinator, config_entry, client, programs)
    spin_select = WashSpinSelect(coordinator, config_entry, client, programs)
    soil_select = WashSoilSelect(coordinator, config_entry, client, programs)
    dry_select = WashDrySelect(coordinator, config_entry, client, programs)
    description_sensor = CandyWashProgramDescriptionSensor(coordinator, config_entry)
    program_select = WashProgramSelect(
        coordinator,
        config_entry,
        client,
        programs,
        temp_select,
        spin_select,
        soil_select,
        dry_select,
        description_sensor,
        nfc_entries,
    )

    async_add_entities(
        [
            program_select,
            temp_select,
            spin_select,
            soil_select,
            dry_select,
            description_sensor,
        ]
    )


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
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    def _machine_is_idle(self) -> bool:
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state in {MachineState.IDLE, MachineState.OFF}


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
        dry_select: WashDrySelect,
        description_sensor: CandyWashProgramDescriptionSensor,
        nfc_entries: list[tuple[DownloadableProgram, WashingMachineWashProgram]],
    ) -> None:
        super().__init__(coordinator, config_entry, client, programs)
        self._temp_select = temp_select
        self._spin_select = spin_select
        self._soil_select = soil_select
        self._dry_select = dry_select
        self._description_sensor = description_sensor
        self._nfc_entries = nfc_entries
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

    @property
    def options(self) -> list[str]:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        standard = [
            self._program_name(p)
            for p in self._programs
            if "autoclean" not in p.name.lower()
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
            return self._program_name(prog)
        opts = self.options
        return opts[0] if opts else None

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
        if nfc_match is not None and nfc_match[1].default_duration:
            return {"duration_minutes": nfc_match[1].default_duration}
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
            self._dry_select.update_for_program(None)
            self._description_sensor.update_for_program(nfc_match)
        else:
            selected = next(
                (p for p in self._programs if self._program_name(p) == option), None
            )
            if selected is not None:
                self._temp_select.reset_for_standard_program(selected)
                self._spin_select.update_for_program(selected)
                self._soil_select.update_for_program(selected)
                self._dry_select.update_for_program(selected)
                self._description_sensor.reset_for_standard_program(selected)
            else:
                self._dry_select.update_for_program(None)
                self._description_sensor.reset_for_standard_program(None)
        self.async_write_ha_state()
        self._temp_select.async_write_ha_state()
        self._spin_select.async_write_ha_state()
        self._soil_select.async_write_ha_state()
        self._dry_select.async_write_ha_state()
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
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]
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
        self._current_program = None
        self._current_option = None
        self._nfc_temp = program.temperature if program is not None else None

    def reset_for_standard_program(self, program: WashingMachineWashProgram) -> None:
        self._nfc_active = False
        self._nfc_temp = None
        self._current_program = program
        self._current_option = str(program.default_temperature)

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        if self._nfc_active:
            return
        self._current_option = option
        self.async_write_ha_state()


class WashSpinSelect(CandyWashSelectBase):
    _attr_name = "Wash spin speed"
    _attr_translation_key = "wash_spin_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]
    _nfc_active: bool = False

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
        return [str(s) for s in _SPIN_STEPS if s <= prog.max_spin_speed]

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
        self._current_program = program
        self._current_option = (
            str(program.default_spin_speed) if program is not None else None
        )

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class WashDrySelect(CandyWashSelectBase):
    _attr_name = "Wash drying"
    _attr_translation_key = "wash_dry_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]
    _nfc_active: bool = False

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DRY_SELECT.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"

    @property
    def available(self) -> bool:
        if self._nfc_active:
            return False
        prog = self._active_program()
        return (
            super().available
            and self._machine_is_idle()
            and prog is not None
            and prog.selector_position_dry is not None
        )

    @property
    def options(self) -> list[str]:
        prog = self._active_program()
        if prog is None or prog.selector_position_dry is None:
            return []
        return ["off", *DRY_LABELS.values()]

    @property
    def current_option(self) -> str | None:
        if self._current_option is not None:
            return self._current_option
        prog = self._active_program()
        if prog is None or prog.selector_position_dry is None:
            return None
        return "off"

    def update_for_program(self, program: WashingMachineWashProgram | None) -> None:
        self._nfc_active = program is None
        self._current_program = program
        self._current_option = "off" if program is not None else None

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()


class WashSoilSelect(CandyWashSelectBase):
    _attr_name = "Wash stain level"
    _attr_translation_key = "wash_soil_select"
    _current_option: str | None = None
    _current_program: WashingMachineWashProgram | None = None  # type: ignore[assignment]
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
        self._current_program = program
        if program is not None and program.min_soil_level < program.max_soil_level:
            self._current_option = SOIL_LABELS.get(program.default_soil_level)
        else:
            self._current_option = None

    def _active_program(self) -> WashingMachineWashProgram | None:
        if self._current_program is not None:
            return self._current_program
        status = cast(WashingMachineStatus, self.coordinator.data)
        for p in self._programs:
            if p.selector_position == status.program:
                return p
        return None

    async def async_select_option(self, option: str) -> None:
        self._current_option = option
        self.async_write_ha_state()
