from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import cast
from urllib.parse import quote, urlencode

from homeassistant.components.button import ButtonEntity
from homeassistant.components.persistent_notification import (
    async_create as pn_async_create,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .client import (
    CandyClient,
    DownloadableProgram,
    TumbleDryerProgram,
    TumbleDryerStatus,
    WashingMachineStatistics,
    WashingMachineStatus,
    WashingMachineWashProgram,
    get_dryer_command_builder,
    load_downloadable_programs,
    parse_dryer_programs,
    parse_wash_programs,
    resolve_downloadable_programs,
)
from .client.model import MachineState, WashProgramState
from .const import (
    CHECKUP_SCHEDULE_EVERY_CYCLE,
    CHECKUP_SCHEDULE_WEEKLY,
    CONF_KEY_BRAND,
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_LAST_DATE,
    CONF_KEY_CHECKUP_PENDING,
    CONF_KEY_CHECKUP_SCHEDULE,
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FILTER,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DATA_KEY_WRITE_PENDING,
    DOMAIN,
    DRY_LEVEL_TO_VALUE,
    DRY_TARGET_TO_VALUE,
    MODE_FULL_CONTROL,
    NOTIF_ID_FULL_CHECKUP,
    NOTIF_ID_LIMESCALE,
    PROGRAM_TYPE_WASH_AND_DRY,
    RAPID_LEVEL_TO_VALUE,
    SOIL_LABELS_REVERSE,
    UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON,
    UNIQUE_ID_TUMBLE_CHECKUP_BUTTON,
    UNIQUE_ID_TUMBLE_DELAY_NUMBER,
    UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT,
    UNIQUE_ID_TUMBLE_PAUSE_BUTTON,
    UNIQUE_ID_TUMBLE_PROGRAM_SELECT,
    UNIQUE_ID_TUMBLE_RAPID_SELECT,
    UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON,
    UNIQUE_ID_TUMBLE_RESUME_BUTTON,
    UNIQUE_ID_TUMBLE_START_BUTTON,
    UNIQUE_ID_TUMBLE_STOP_BUTTON,
    UNIQUE_ID_TUMBLE_TIME_SELECT,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_DRY_SELECT,
    UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH,
    UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON,
    UNIQUE_ID_WASH_LIMESCALE_BUTTON,
    UNIQUE_ID_WASH_MAINT_FILTER_BUTTON,
    UNIQUE_ID_WASH_MAINT_FULL_CHECKUP_BUTTON,
    UNIQUE_ID_WASH_MAINT_LIMESCALE_BUTTON,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT,
    UNIQUE_ID_WASH_RESUME_BUTTON,
    UNIQUE_ID_WASH_RESUME_GOOD_NIGHT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    UNIQUE_ID_WASH_STOP_BUTTON,
    UNIQUE_ID_WASH_TEMP_SELECT,
    WASH_OPTIONS,
)
from .helpers import (
    command_settling_delay,
    dryer_device_info,
    is_dualtech,
    is_washer_dryer,
    localized_notification_text,
    remote_control_enabled,
    supports_remote_pause,
    wash_device_info,
)


def _should_send_checkup(config_entry: ConfigEntry, now: datetime) -> int:
    """Return 1 if the automatic diagnostic should run with the next wash start, else 0."""
    if not config_entry.data.get(CONF_KEY_CHECKUP_ENABLED, False):
        return 0
    schedule = config_entry.data.get(
        CONF_KEY_CHECKUP_SCHEDULE, CHECKUP_SCHEDULE_EVERY_CYCLE
    )
    if schedule == CHECKUP_SCHEDULE_EVERY_CYCLE:
        return 1
    last_ts = config_entry.data.get(CONF_KEY_CHECKUP_LAST_DATE)
    if last_ts is None:
        return 1
    last = dt_util.utc_from_timestamp(last_ts)
    delta = timedelta(days=7 if schedule == CHECKUP_SCHEDULE_WEEKLY else 30)
    return 1 if (now - last) >= delta else 0


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

        dryer_buttons: list[ButtonEntity] = [
            CandyDryerStartButton(
                coordinator, config_entry, dryer_client, dryer_programs
            ),
            CandyDryerStopButton(coordinator, config_entry, dryer_client),
            CandyDryerPauseButton(coordinator, config_entry, dryer_client),
            CandyDryerResumeButton(coordinator, config_entry, dryer_client),
            CandyDryerAntiCreaseCancelButton(coordinator, config_entry, dryer_client),
            CandyDryerCheckUpButton(coordinator, config_entry, dryer_client),
            CandyDryerResetWarningsButton(coordinator, config_entry, dryer_client),
        ]
        async_add_entities(dryer_buttons)
        return

    if not isinstance(coordinator.data, WashingMachineStatus):
        return

    client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
    programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))
    raw_dl = config_entry.data.get(CONF_KEY_DOWNLOADABLE_PROGRAMS, [])
    nfc_entries = resolve_downloadable_programs(
        load_downloadable_programs(raw_dl), programs
    )

    interface_type = config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
    supports_pause = supports_remote_pause(interface_type)

    buttons: list = [
        WashStartButton(coordinator, config_entry, client, programs, nfc_entries),
        WashStopButton(coordinator, config_entry, client),
        WashGoodNightResumeButton(coordinator, config_entry, client),
    ]
    if supports_pause:
        buttons.append(WashPauseButton(coordinator, config_entry, client))
        buttons.append(WashResumeButton(coordinator, config_entry, client))
    async_add_entities(buttons)

    has_maint = bool(config_entry.data.get(CONF_KEY_MAINTENANCE_ENABLED, False))
    has_checkup = bool(config_entry.data.get(CONF_KEY_CHECKUP_ENABLED, False))
    if has_maint or has_checkup:
        maint_buttons: list = [WashFullCheckUpButton(coordinator, config_entry, client)]
        if has_maint:
            autoclean = next(
                (p for p in programs if "autoclean" in p.name.lower()),
                None,
            )
            if autoclean is not None:
                maint_buttons.append(
                    WashLimescaleCleanButton(
                        coordinator, config_entry, client, autoclean
                    )
                )
        stats_coordinator = hass.data[DOMAIN][config_id].get(DATA_KEY_STATS_COORDINATOR)
        if stats_coordinator is not None:
            maint_buttons.append(
                WashMaintResetButton(
                    coordinator,
                    config_entry,
                    stats_coordinator,
                    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
                    UNIQUE_ID_WASH_MAINT_FULL_CHECKUP_BUTTON,
                    "Check-up maintenance reset",
                    "wash_maint_full_checkup_reset",
                    "mdi:washing-machine-alert",
                ),
            )
            if config_entry.data.get(CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True):
                maint_buttons.append(
                    WashMaintResetButton(
                        coordinator,
                        config_entry,
                        stats_coordinator,
                        CONF_KEY_MAINTENANCE_LAST_LIMESCALE,
                        UNIQUE_ID_WASH_MAINT_LIMESCALE_BUTTON,
                        "Limescale maintenance reset",
                        "wash_maint_limescale_reset",
                        "mdi:water-remove",
                    )
                )
            if config_entry.data.get(CONF_KEY_MAINTENANCE_FILTER_ENABLED, True):
                maint_buttons.append(
                    WashMaintResetButton(
                        coordinator,
                        config_entry,
                        stats_coordinator,
                        CONF_KEY_MAINTENANCE_LAST_FILTER,
                        UNIQUE_ID_WASH_MAINT_FILTER_BUTTON,
                        "Filter maintenance reset",
                        "wash_maint_filter_reset",
                        "mdi:filter-remove",
                    )
                )
        async_add_entities(maint_buttons)


def _build_bianca_start_params(
    selector_position: int,
    pr_code: int,
    pr_str: str,
    temp: int,
    soil: int,
    spin: int,
    opt_mask: int,
    steam: bool,
    dry: int,
    recipe_id: str | int,
    checkup: int,
    delay_minutes: int,
    extra_dose: int,
) -> dict[str, str | int]:
    """Build URL parameters for starting a wash cycle on Bianca/Rapido platforms."""
    return {
        "Write": 1,
        "StSt": 1,
        "DelVl": delay_minutes // 30,
        "PrNm": selector_position,
        "PrCode": pr_code,
        "PrStr": pr_str,
        "TmpTgt": temp,
        "SLevTgt": soil,
        "SpdTgt": spin // 100,
        "OptMsk1": opt_mask,
        "OptMsk2": 0,
        "Lang": 0,
        "Stm": 1 if steam else 0,
        "Dry": dry,
        "ED": extra_dose,
        "RecipeId": recipe_id,
        "StartCheckUp": checkup,
        "DispTestOn": 1,
    }


def _build_dualtech_start_params(
    program: WashingMachineWashProgram,
    temp: int,
    soil: int,
    spin: int,
    opt_mask: int,
    steam: bool,
    dry: int,
    recipe_id: str | int,
    checkup: int,
    delay_minutes: int,
    is_washer_dryer: bool,
    is_hoover: bool,
    interface_type: str,
) -> dict[str, str | int]:
    """Build URL parameters for starting a wash cycle on DualTech platforms."""
    params: dict[str, str | int] = {
        "Write": 1,
        "Pa": 0,
        "Sel": 0,
        "PrNm": program.selector_position,
    }
    delay_hours = delay_minutes // 60
    if delay_hours > 0:
        params["DelMd"] = 1
        params["DelVl"] = delay_hours
    else:
        params["StSt"] = 1

    effective_opt_mask = opt_mask
    if (
        interface_type.upper().startswith("3D_DUAL")
        and is_hoover
        and bool(effective_opt_mask & 16)
    ):
        effective_opt_mask = (effective_opt_mask & ~16) | 128

    if not program.is_dry:
        if temp not in (program.default_temperature, 255):
            params["TmpTgt"] = temp
            params["TmpDf"] = program.default_temperature

        effective_soil = soil
        if effective_soil == 9:
            effective_soil = program.min_soil_level
        if effective_soil not in (program.default_soil_level, 255):
            if temp == 90 and effective_soil == 1:
                effective_soil = 2
            params["SLevTgt"] = effective_soil

        if spin not in (program.default_spin_speed, 255):
            params["SpdTgt"] = spin // 100
            params["SpdDef"] = program.default_spin_speed // 100

    if effective_opt_mask > 0:
        params["OptMsk"] = effective_opt_mask

    params["Stm"] = 1 if steam else 0

    if is_washer_dryer:
        # Confirmed via Simply-Fi APK CandyWasherDryerDualTech.start (classes4.dex):
        # In wash or wash-and-dry mode, uses selected dry target (0 for no dry, 1..8 if active).
        # In standalone drying mode, uses selected dry target, falling back to catalog dry or cupboard dry.
        if not program.is_dry:
            dry_val = dry
        else:
            dry_val = (
                dry
                if dry > 0
                else (
                    program.dry
                    if 0 < program.dry < 255
                    else (2 if program.dry == 255 else 0)
                )
            )
        params["Option"] = dry_val

    params["RecipeId"] = recipe_id
    params["CheckUpState"] = checkup
    return params


def _build_bianca_stop_params(program: int) -> dict[str, int]:
    """Build URL parameters for stopping a wash cycle on Bianca/Rapido platforms."""
    return {
        "Write": 1,
        "StSt": 0,
        "PrNm": program,
        "DelVl": 0,
    }


def _build_dualtech_stop_params(program: int) -> dict[str, int]:
    """Build URL parameters for stopping a wash cycle on DualTech platforms."""
    return {
        "Write": 1,
        "StSt": 0,
        "DelMd": 0,
        "PrNm": program,
    }


class CandyWashButtonBase(CoordinatorEntity, ButtonEntity):
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

    @property
    def available(self) -> bool:
        return self.hass.data[DOMAIN][self.config_id].get(
            DATA_KEY_WRITE_PENDING, 0
        ) == 0 and remote_control_enabled(self.coordinator.data)

    async def _send_command_and_refresh(self, query_string: str) -> None:
        data = self.hass.data[DOMAIN][self.config_id]
        data[DATA_KEY_WRITE_PENDING] = data.get(DATA_KEY_WRITE_PENDING, 0) + 1
        self.coordinator.async_update_listeners()
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        settling_delay = command_settling_delay(interface_type)
        try:
            await self._client.send_command(query_string)
            await asyncio.sleep(settling_delay)
        except Exception:
            await asyncio.sleep(settling_delay)
            raise
        finally:
            data[DATA_KEY_WRITE_PENDING] -= 1
            if data[DATA_KEY_WRITE_PENDING] == 0:
                await self.coordinator.async_request_refresh()

    def _record_checkup_pending(self) -> None:
        new_data = dict(self.config_entry.data)
        new_data[CONF_KEY_CHECKUP_PENDING] = True
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)


class WashStartButton(CandyWashButtonBase):
    _attr_name = "Start wash"
    _attr_translation_key = "wash_start_button"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[WashingMachineWashProgram],
        nfc_entries: list[tuple[DownloadableProgram, WashingMachineWashProgram]],
    ) -> None:
        super().__init__(coordinator, config_entry, client)
        self._programs = programs
        self._nfc_entries = nfc_entries

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_START_BUTTON.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:play-circle-outline"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        # Simply-Fi app allows cycle start in IDLE or FINISHED states (CandyWasher.updateWithStatus, credit: Cessibear)
        return status.machine_state in {
            MachineState.IDLE,
            MachineState.FINISHED1,
            MachineState.FINISHED2,
        }

    def _get_dry_target(self, registry: er.EntityRegistry) -> int:
        entity_id = registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_DRY_SELECT.format(self.config_id)
        )
        if entity_id is None:
            return 0
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            return 0
        if state.state in DRY_TARGET_TO_VALUE:
            return DRY_TARGET_TO_VALUE[state.state]
        raise ValueError(f"Unknown dry target: {state.state}")

    async def async_press(self) -> None:
        registry = er.async_get(self.hass)
        dry = self._get_dry_target(registry)

        def _get_state(unique_id_template: str) -> str | None:
            entity_id = registry.async_get_entity_id(
                "select", DOMAIN, unique_id_template.format(self.config_id)
            )
            if entity_id is None:
                return None
            state = self.hass.states.get(entity_id)
            return state.state if state else None

        def _get_number(unique_id_template: str) -> float:
            entity_id = registry.async_get_entity_id(
                "number", DOMAIN, unique_id_template.format(self.config_id)
            )
            if entity_id is None:
                return 0
            state = self.hass.states.get(entity_id)
            try:
                return float(state.state) if state else 0
            except (ValueError, TypeError):
                return 0

        program_name = _get_state(UNIQUE_ID_WASH_PROGRAM_SELECT)
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        program = next(
            (p for p in self._programs if p.localized_name(lang) == program_name),
            None,
        )

        if program is None:
            nfc_switch_id = registry.async_get_entity_id(
                "switch", DOMAIN, UNIQUE_ID_WASH_NFC_SWITCH.format(self.config_id)
            )
            nfc_switch_state = (
                self.hass.states.get(nfc_switch_id) if nfc_switch_id else None
            )
            nfc_active = nfc_switch_state is not None and nfc_switch_state.state == "on"
            nfc_match = next(
                (
                    (nfc, base)
                    for nfc, base in self._nfc_entries
                    if nfc_active and nfc.category_prefixed(lang) == program_name
                ),
                None,
            )
            if nfc_match is None:
                raise ValueError(
                    f"Cannot start: program '{program_name}' not found in catalog"
                )
            nfc, base = nfc_match
            delay = int(_get_number(UNIQUE_ID_WASH_DELAY_NUMBER))
            opt_mask = 0
            for bitmask, _translation_key, uid_suffix, _name in WASH_OPTIONS:
                switch_entity_id = registry.async_get_entity_id(
                    "switch", DOMAIN, f"{self.config_id}-{uid_suffix}"
                )
                switch_state = (
                    self.hass.states.get(switch_entity_id) if switch_entity_id else None
                )
                if switch_state and switch_state.state == "on":
                    opt_mask |= bitmask
            steam_entity_id = registry.async_get_entity_id(
                "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)
            )
            steam_state = (
                self.hass.states.get(steam_entity_id) if steam_entity_id else None
            )
            steam = steam_state.state == "on" if steam_state else False
            checkup = _should_send_checkup(self.config_entry, dt_util.utcnow())
            soil_target = nfc.resolve_soil_target(base)
            spin_target = (
                nfc.spin_speed if nfc.spin_speed is not None else base.max_spin_speed
            )
            interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
            extra_dose_entity_id = registry.async_get_entity_id(
                "switch",
                DOMAIN,
                UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH.format(self.config_id),
            )
            extra_dose_state = (
                self.hass.states.get(extra_dose_entity_id)
                if extra_dose_entity_id
                else None
            )
            extra_dose = 1 if extra_dose_state and extra_dose_state.state == "on" else 0
            if is_dualtech(interface_type):
                brand = self.config_entry.data.get(CONF_KEY_BRAND, "candy")
                is_hoover = str(brand).lower() == "hoover"
                is_wd = is_washer_dryer(self.config_entry, self._programs)
                params = _build_dualtech_start_params(
                    base,
                    nfc.temperature,
                    soil_target,
                    spin_target,
                    nfc.options | opt_mask,
                    steam,
                    dry,
                    nfc.recipe_id,
                    checkup,
                    delay,
                    is_wd,
                    is_hoover,
                    interface_type,
                )
            else:
                params = _build_bianca_start_params(
                    base.selector_position,
                    base.pr_code,
                    nfc.display_name(lang),
                    nfc.temperature,
                    soil_target,
                    spin_target,
                    nfc.options | opt_mask,
                    steam,
                    dry,
                    nfc.recipe_id,
                    checkup,
                    delay,
                    extra_dose,
                )
            await self._send_command_and_refresh(urlencode(params, quote_via=quote))
            if checkup == 1:
                self._record_checkup_pending()
            return

        temp_str = _get_state(UNIQUE_ID_WASH_TEMP_SELECT)
        spin_str = _get_state(UNIQUE_ID_WASH_SPIN_SELECT)
        soil_str = _get_state(UNIQUE_ID_WASH_SOIL_SELECT)
        delay = int(_get_number(UNIQUE_ID_WASH_DELAY_NUMBER))

        try:
            temp = (
                int(temp_str)
                if temp_str not in (None, "unavailable", "unknown")
                else program.default_temperature
            )
        except (ValueError, TypeError):
            temp = program.default_temperature

        try:
            spin = (
                int(spin_str)
                if spin_str not in (None, "unavailable", "unknown")
                else program.default_spin_speed
            )
        except (ValueError, TypeError):
            spin = program.default_spin_speed

        if program.min_soil_level < program.max_soil_level:
            try:
                soil = (
                    SOIL_LABELS_REVERSE[soil_str]
                    if soil_str not in (None, "unavailable", "unknown")
                    else program.default_soil_level
                )
            except KeyError:
                soil = program.default_soil_level
        else:
            soil = program.default_soil_level

        if soil == 9 or (program.max_soil_level > 0 and soil > program.max_soil_level):
            soil = program.min_soil_level

        program_type = _get_state(UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
        if (
            program_type == PROGRAM_TYPE_WASH_AND_DRY
            and program.dry_supported
            and dry == 0
        ):
            raise ValueError(
                "Cannot start wash and dry cycle without a valid dry target setting"
            )

        if program.is_dry:
            if dry == 0:
                raise ValueError(
                    "Cannot start drying cycle without a valid dry target setting"
                )
            temp = 0
            spin = 0
            soil = 0
            steam = False
            opt_mask = 0
        else:
            steam_entity_id = registry.async_get_entity_id(
                "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)
            )
            steam_state = (
                self.hass.states.get(steam_entity_id) if steam_entity_id else None
            )
            steam = steam_state.state == "on" if steam_state else False

            opt_mask = 0
            for bitmask, _translation_key, uid_suffix, _name in WASH_OPTIONS:
                switch_entity_id = registry.async_get_entity_id(
                    "switch", DOMAIN, f"{self.config_id}-{uid_suffix}"
                )
                switch_state = (
                    self.hass.states.get(switch_entity_id) if switch_entity_id else None
                )
                if switch_state and switch_state.state == "on":
                    opt_mask |= bitmask

        checkup = _should_send_checkup(self.config_entry, dt_util.utcnow())
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        extra_dose_entity_id = registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH.format(self.config_id)
        )
        extra_dose_state = (
            self.hass.states.get(extra_dose_entity_id) if extra_dose_entity_id else None
        )
        extra_dose = 1 if extra_dose_state and extra_dose_state.state == "on" else 0
        if is_dualtech(interface_type):
            brand = self.config_entry.data.get(CONF_KEY_BRAND, "candy")
            is_hoover = str(brand).lower() == "hoover"
            is_wd = is_washer_dryer(self.config_entry, self._programs)
            params = _build_dualtech_start_params(
                program,
                temp,
                soil,
                spin,
                opt_mask,
                steam,
                dry,
                0,
                checkup,
                delay,
                is_wd,
                is_hoover,
                interface_type,
            )
        else:
            params = _build_bianca_start_params(
                program.selector_position,
                program.pr_code,
                program.localized_name(lang),
                temp,
                soil,
                spin,
                opt_mask,
                steam,
                dry,
                0,
                checkup,
                delay,
                extra_dose,
            )
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))
        if checkup == 1:
            self._record_checkup_pending()


class WashMaintResetButton(CoordinatorEntity, ButtonEntity):
    """Reset a maintenance counter to its full threshold."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        stats_coordinator: DataUpdateCoordinator,
        conf_key: str,
        unique_id_template: str,
        name: str,
        translation_key: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id
        self._stats_coordinator = stats_coordinator
        self._conf_key = conf_key
        self._unique_id_template = unique_id_template
        self._attr_name = name
        self._attr_translation_key = translation_key
        self._attr_icon = icon

    @property
    def unique_id(self) -> str:
        return self._unique_id_template.format(self.config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    async def async_press(self) -> None:
        total = 0
        if self._stats_coordinator.data is not None:
            total = cast(
                WashingMachineStatistics, self._stats_coordinator.data
            ).total_cycles
        new_data = dict(self.config_entry.data)
        new_data[self._conf_key] = total
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        self._stats_coordinator.async_update_listeners()


class WashPauseButton(CandyWashButtonBase):
    _attr_name = "Pause wash"
    _attr_translation_key = "wash_pause_button"
    _attr_icon = "mdi:pause-circle-outline"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PAUSE_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state == MachineState.RUNNING

    async def async_press(self) -> None:
        await self._send_command_and_refresh("Pa=1")


class WashResumeButton(CandyWashButtonBase):
    _attr_name = "Resume wash"
    _attr_translation_key = "wash_resume_button"
    _attr_icon = "mdi:play-circle-outline"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_RESUME_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state == MachineState.PAUSED

    async def async_press(self) -> None:
        await self._send_command_and_refresh("Pa=0")


class WashGoodNightResumeButton(CandyWashButtonBase):
    _attr_has_entity_name = True
    _attr_translation_key = "wash_resume_good_night"
    _attr_icon = "mdi:weather-night"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_RESUME_GOOD_NIGHT.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.program_state == WashProgramState.GOOD_NIGHT

    async def async_press(self) -> None:
        await self._send_command_and_refresh("Write=1&RestartGN=1")


class WashStopButton(CandyWashButtonBase):
    _attr_name = "Stop wash"
    _attr_translation_key = "wash_stop_button"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_STOP_BUTTON.format(self.config_id)

    @property
    def icon(self) -> str:
        return "mdi:stop-circle-outline"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state not in {MachineState.IDLE, MachineState.OFF}

    async def async_press(self) -> None:
        status = cast(WashingMachineStatus, self.coordinator.data)
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        if is_dualtech(interface_type):
            params = _build_dualtech_stop_params(status.program)
        else:
            params = _build_bianca_stop_params(status.program)
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class WashFullCheckUpButton(CandyWashButtonBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Full Check-up"
    _attr_translation_key = "wash_full_checkup"
    _attr_icon = "mdi:stethoscope"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state == MachineState.IDLE

    async def async_press(self) -> None:
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        cmd = (
            {"Write": 1, "CheckUpState": 1}
            if is_dualtech(interface_type)
            else {"CheckUpState": 1}
        )
        await self._send_command_and_refresh(urlencode(cmd, quote_via=quote))
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        pn_async_create(
            self.hass,
            localized_notification_text("checkup_button_message", lang),
            title=localized_notification_text("full_checkup_title", lang),
            notification_id=NOTIF_ID_FULL_CHECKUP.format(self.config_id),
        )


class WashLimescaleCleanButton(CandyWashButtonBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Limescale Cleaning"
    _attr_translation_key = "wash_limescale_clean"
    _attr_icon = "mdi:water-remove"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        program: WashingMachineWashProgram,
    ) -> None:
        super().__init__(coordinator, config_entry, client)
        self._program = program

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_LIMESCALE_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state == MachineState.IDLE

    async def async_press(self) -> None:
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        if is_dualtech(interface_type):
            brand = self.config_entry.data.get(CONF_KEY_BRAND, "candy")
            is_hoover = str(brand).lower() == "hoover"
            is_wd = is_washer_dryer(self.config_entry, [self._program])
            params: dict[str, str | int] = _build_dualtech_start_params(
                self._program,
                255,
                255,
                0,
                0,
                False,
                0,
                0,
                0,
                0,
                is_wd,
                is_hoover,
                interface_type,
            )
        else:
            params = {
                "Write": 1,
                "StSt": 1,
                "PrNm": self._program.selector_position,
                "PrCode": self._program.pr_code,
                "PrStr": self._program.localized_name(lang),
                "TmpTgt": 255,
                "SpdTgt": 0,
                "OptMsk1": 0,
                "OptMsk2": 0,
                "Lang": 0,
                "Stm": 0,
                "Dry": 0,
                "ED": 0,
                "RecipeId": 0,
                "StartCheckUp": 0,
                "DispTestOn": 1,
            }
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))
        pn_async_create(
            self.hass,
            localized_notification_text("limescale_message", lang),
            title=localized_notification_text("limescale_title", lang),
            notification_id=NOTIF_ID_LIMESCALE.format(self.config_id),
        )


class CandyDryerButtonBase(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

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

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self.hass.data[DOMAIN][self.config_id].get(DATA_KEY_WRITE_PENDING, 0)
            == 0
            and remote_control_enabled(self.coordinator.data)
        )

    async def _send_command_and_refresh(self, query_string: str) -> None:
        data = self.hass.data[DOMAIN][self.config_id]
        data[DATA_KEY_WRITE_PENDING] = data.get(DATA_KEY_WRITE_PENDING, 0) + 1
        self.coordinator.async_update_listeners()
        interface_type = self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        settling_delay = command_settling_delay(interface_type)
        try:
            await self._client.send_command(query_string)
            await asyncio.sleep(settling_delay)
        except Exception:
            await asyncio.sleep(settling_delay)
            raise
        finally:
            data[DATA_KEY_WRITE_PENDING] -= 1
            if data[DATA_KEY_WRITE_PENDING] == 0:
                await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        return dryer_device_info(self.config_entry)


class CandyDryerStartButton(CandyDryerButtonBase):
    _attr_translation_key = "dryer_start_button"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        client: CandyClient,
        programs: list[TumbleDryerProgram],
    ) -> None:
        super().__init__(coordinator, config_entry, client)
        self._programs = programs

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_START_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return (
            status.machine_state
            in (
                MachineState.IDLE,
                MachineState.FINISHED1,
                MachineState.FINISHED2,
            )
            and status.door_closed
        )

    async def async_press(self) -> None:
        registry = er.async_get(self.hass)

        def _get_select_state(unique_id_template: str) -> str | None:
            entity_id = registry.async_get_entity_id(
                "select", DOMAIN, unique_id_template.format(self.config_id)
            )
            if entity_id is None:
                return None
            state = self.hass.states.get(entity_id)
            return (
                state.state
                if state and state.state not in ("unavailable", "unknown")
                else None
            )

        def _get_number_state(unique_id_template: str) -> float:
            entity_id = registry.async_get_entity_id(
                "number", DOMAIN, unique_id_template.format(self.config_id)
            )
            if entity_id is None:
                return 0.0
            state = self.hass.states.get(entity_id)
            try:
                return (
                    float(state.state)
                    if state and state.state not in ("unavailable", "unknown")
                    else 0.0
                )
            except (ValueError, TypeError):
                return 0.0

        program_name = _get_select_state(UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
        dry_level_option = _get_select_state(UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT)
        time_option = _get_select_state(UNIQUE_ID_TUMBLE_TIME_SELECT)
        rapid_option = _get_select_state(UNIQUE_ID_TUMBLE_RAPID_SELECT)
        delay_minutes = int(_get_number_state(UNIQUE_ID_TUMBLE_DELAY_NUMBER))

        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        program = next(
            (p for p in self._programs if p.localized_name(lang) == program_name),
            None,
        )
        if program is None:
            if self._programs:
                program = self._programs[0]
            else:
                raise ValueError("No dryer program available to start")

        dry_level = DRY_LEVEL_TO_VALUE.get(
            dry_level_option or "", program.default_drying_level
        )
        builder = get_dryer_command_builder(
            self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        )

        selected_time: int | None = None
        if (
            program.set_time_level
            and time_option is not None
            and time_option.isdigit()
            and int(time_option) > 0
        ):
            selected_time = int(time_option)
        elif not program.set_dry_level and program.set_time_level:
            selected_time = (
                program.default_time_level if program.default_time_level > 0 else 30
            )

        rapid_level = (
            RAPID_LEVEL_TO_VALUE.get(rapid_option or "", 0) if program.set_rapido else 0
        )

        if rapid_level > 0:
            if delay_minutes > 0:
                params = builder.build_rapid_delay_start(
                    program.selector_position, rapid_level, delay_minutes
                )
            else:
                params = builder.build_rapid_start(
                    program.selector_position, rapid_level
                )
        elif selected_time is not None:
            if delay_minutes > 0:
                params = builder.build_timed_delay_start(
                    program.selector_position, selected_time, delay_minutes
                )
            else:
                params = builder.build_timed_start(
                    program.selector_position, selected_time
                )
        else:
            effective_dry_level = (
                dry_level
                if dry_level > 0
                else (
                    program.default_drying_level
                    if program.default_drying_level > 0
                    else 1
                )
            )
            if delay_minutes > 0:
                params = builder.build_delay_start(
                    program.selector_position, effective_dry_level, delay_minutes
                )
            else:
                params = builder.build_standard_start(
                    program.selector_position, effective_dry_level
                )

        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class CandyDryerStopButton(CandyDryerButtonBase):
    _attr_translation_key = "dryer_stop_button"
    _attr_icon = "mdi:stop-circle-outline"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_STOP_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.machine_state not in {MachineState.IDLE, MachineState.OFF}

    async def async_press(self) -> None:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        builder = get_dryer_command_builder(
            self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        )
        params = builder.build_stop(status.program)
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class CandyDryerPauseButton(CandyDryerButtonBase):
    _attr_translation_key = "dryer_pause_button"
    _attr_icon = "mdi:pause-circle-outline"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_PAUSE_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.machine_state == MachineState.RUNNING

    async def async_press(self) -> None:
        builder = get_dryer_command_builder(
            self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        )
        params = builder.build_pause()
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class CandyDryerResumeButton(CandyDryerButtonBase):
    _attr_translation_key = "dryer_resume_button"
    _attr_icon = "mdi:play-circle-outline"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_RESUME_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.machine_state == MachineState.PAUSED

    async def async_press(self) -> None:
        builder = get_dryer_command_builder(
            self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        )
        params = builder.build_resume()
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class CandyDryerAntiCreaseCancelButton(CandyDryerButtonBase):
    _attr_translation_key = "dryer_anti_crease_cancel_button"
    _attr_icon = "mdi:cancel"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.machine_state in {MachineState.FINISHED1, MachineState.FINISHED2}

    async def async_press(self) -> None:
        builder = get_dryer_command_builder(
            self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        )
        params = builder.build_cancel_anticrease()
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class CandyDryerCheckUpButton(CandyDryerButtonBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "dryer_checkup_button"
    _attr_icon = "mdi:stethoscope"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_CHECKUP_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.machine_state == MachineState.IDLE and status.door_closed

    async def async_press(self) -> None:
        builder = get_dryer_command_builder(
            self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        )
        params = builder.build_checkup_start()
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))


class CandyDryerResetWarningsButton(CandyDryerButtonBase):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "dryer_reset_warnings_button"
    _attr_icon = "mdi:alert-remove-outline"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.need_clean_filter or status.water_tank_full

    async def async_press(self) -> None:
        builder = get_dryer_command_builder(
            self.config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")
        )
        params = builder.build_reset_warnings()
        await self._send_command_and_refresh(urlencode(params, quote_via=quote))
