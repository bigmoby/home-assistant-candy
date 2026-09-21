from abc import abstractmethod
from collections.abc import Mapping
import contextlib
import datetime
from typing import Any, cast

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfFrequency,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util import dt as dt_util

from .client import (
    DownloadableProgram,
    WashingMachineStatus,
    WashingMachineWashProgram,
    load_downloadable_programs,
    parse_wash_programs,
)
from .client.model import (
    DishwasherState,
    DishwasherStatus,
    DryerProgramState,
    MachineState,
    OvenStatus,
    TumbleDryerStatus,
    WashingMachineStatistics,
    WineCoolerStatus,
)
from .const import (
    CONF_KEY_CHECKUP_ENABLED,
    CONF_KEY_CHECKUP_LAST_DATE,
    CONF_KEY_CHECKUP_LAST_RESULT,
    CONF_KEY_DEVICE_MODEL,
    CONF_KEY_DOWNLOADABLE_PROGRAMS,
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
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DATA_KEY_WRITE_PENDING,
    DEVICE_NAME_DISHWASHER,
    DEVICE_NAME_OVEN,
    DEVICE_NAME_TUMBLE_DRYER,
    DEVICE_NAME_WASHING_MACHINE,
    DEVICE_NAME_WINE_COOLER,
    DOMAIN,
    DRY_LABELS,
    MAINTENANCE_FILTER_THRESHOLD,
    MAINTENANCE_FULL_CHECKUP_THRESHOLD,
    MAINTENANCE_HARDNESS_THRESHOLDS,
    MODE_FULL_CONTROL,
    SOIL_LABELS,
    SOIL_LABELS_REVERSE,
    STEAM_DURATION_OFFSETS,
    SUGGESTED_AREA_BATHROOM,
    SUGGESTED_AREA_KITCHEN,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_DISHWASHER_PROGRAM,
    UNIQUE_ID_DISHWASHER_REMAINING_TIME,
    UNIQUE_ID_OVEN,
    UNIQUE_ID_OVEN_PROGRAM,
    UNIQUE_ID_OVEN_TEMP,
    UNIQUE_ID_TUMBLE_CYCLE_STATUS,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_TUMBLE_PROGRAM,
    UNIQUE_ID_TUMBLE_REMAINING_TIME,
    UNIQUE_ID_WASH_CHECKUP_RESULT,
    UNIQUE_ID_WASH_CYCLE_CAPACITY,
    UNIQUE_ID_WASH_CYCLE_STATUS,
    UNIQUE_ID_WASH_DELAY,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_DRY_PHASE,
    UNIQUE_ID_WASH_ERROR,
    UNIQUE_ID_WASH_ESTIMATED_DURATION,
    UNIQUE_ID_WASH_FILL_PERCENT,
    UNIQUE_ID_WASH_LAST_CHECKUP,
    UNIQUE_ID_WASH_LIQUID_DETERGENT,
    UNIQUE_ID_WASH_MAINT_FILTER,
    UNIQUE_ID_WASH_MAINT_FULL_CHECKUP,
    UNIQUE_ID_WASH_MAINT_LIMESCALE,
    UNIQUE_ID_WASH_MOTOR_FREQ,
    UNIQUE_ID_WASH_NTC_DRUM,
    UNIQUE_ID_WASH_NTC_WATER,
    UNIQUE_ID_WASH_POWDER_DETERGENT,
    UNIQUE_ID_WASH_PROGRAM,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_PURCHASE_DATE,
    UNIQUE_ID_WASH_REMAINING_TIME,
    UNIQUE_ID_WASH_SCHEDULED_FINISH,
    UNIQUE_ID_WASH_SCHEDULED_START,
    UNIQUE_ID_WASH_SOIL_LEVEL,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SPEED,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    UNIQUE_ID_WASH_TEMPERATURE,
    UNIQUE_ID_WASH_TOTAL_CYCLES,
    UNIQUE_ID_WASHING_MACHINE,
    UNIQUE_ID_WINE_COOLER,
    UNIQUE_ID_WINE_COOLER_ERROR,
    UNIQUE_ID_WINE_COOLER_LIGHT,
    UNIQUE_ID_WINE_COOLER_PROGRAM,
    UNIQUE_ID_WINE_COOLER_PROGRAM_DOWN,
    UNIQUE_ID_WINE_COOLER_TEMP,
    UNIQUE_ID_WINE_COOLER_TEMP_DOWN,
)
from .helpers import cycles_remaining


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Set up the Candy sensors from config entry."""

    config_id = config_entry.entry_id
    coordinator = hass.data[DOMAIN][config_id][DATA_KEY_COORDINATOR]

    if isinstance(coordinator.data, WashingMachineStatus):
        status = coordinator.data
        programs = parse_wash_programs(config_entry.data.get(CONF_KEY_PROGRAMS, []))
        dl_programs = load_downloadable_programs(
            config_entry.data.get(CONF_KEY_DOWNLOADABLE_PROGRAMS, [])
        )
        entities: list[CandyBaseSensor] = [
            CandyWashingMachineSensor(coordinator, config_entry),
            CandyWashProgramSensor(coordinator, config_entry, programs, dl_programs),
            CandyWashCycleStatusSensor(coordinator, config_entry),
            CandyWashRemainingTimeSensor(coordinator, config_entry),
            CandyWashTemperatureSensor(coordinator, config_entry),
            CandyWashSpinSpeedSensor(coordinator, config_entry),
            CandyWashErrorSensor(coordinator, config_entry),
        ]
        registry = er.async_get(hass)

        def _was_registered(unique_id_template: str) -> bool:
            return (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, unique_id_template.format(config_id)
                )
                is not None
            )

        if status.fill_percent is not None or _was_registered(
            UNIQUE_ID_WASH_FILL_PERCENT
        ):
            entities.append(CandyWashFillPercentSensor(coordinator, config_entry))
        if status.delay_value is not None or _was_registered(UNIQUE_ID_WASH_DELAY):
            entities.append(CandyWashDelaySensor(coordinator, config_entry))
        if status.ntc_water is not None or _was_registered(UNIQUE_ID_WASH_NTC_WATER):
            entities.append(CandyWashNtcWaterSensor(coordinator, config_entry))
        if status.ntc_drum is not None or _was_registered(UNIQUE_ID_WASH_NTC_DRUM):
            entities.append(CandyWashNtcDrumSensor(coordinator, config_entry))
        if status.motor_speed_freq is not None or _was_registered(
            UNIQUE_ID_WASH_MOTOR_FREQ
        ):
            entities.append(CandyWashMotorFreqSensor(coordinator, config_entry))
        if status.soil_level is not None or _was_registered(UNIQUE_ID_WASH_SOIL_LEVEL):
            entities.append(CandyWashSoilLevelSensor(coordinator, config_entry))
        if status.dry_type is not None or _was_registered(UNIQUE_ID_WASH_DRY_PHASE):
            entities.append(CandyWashDryPhaseSensor(coordinator, config_entry))
        if programs:
            entities.append(
                CandyWashEstimatedDurationSensor(coordinator, config_entry, programs)
            )
            if any(p.liquid_detergent_dose is not None for p in programs):
                entities.append(
                    CandyWashLiquidDetergentSensor(coordinator, config_entry, programs)
                )
            if any(p.powder_detergent_dose is not None for p in programs):
                entities.append(
                    CandyWashPowderDetergentSensor(coordinator, config_entry, programs)
                )
            entities.append(
                CandyWashCycleCapacitySensor(coordinator, config_entry, programs)
            )
        entities.append(CandyWashScheduledFinishSensor(coordinator, config_entry))
        if programs:
            entities.append(CandyWashScheduledStartSensor(coordinator, config_entry))
        if config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL:
            if config_entry.data.get(CONF_KEY_CHECKUP_ENABLED):
                entities.append(CandyWashCheckUpResultSensor(coordinator, config_entry))
                entities.append(CandyWashLastCheckUpSensor(coordinator, config_entry))
            if config_entry.data.get(CONF_KEY_PURCHASE_DATE):
                entities.append(CandyWashPurchaseDateSensor(coordinator, config_entry))
        stats_coordinator = hass.data[DOMAIN][config_id].get(DATA_KEY_STATS_COORDINATOR)
        if stats_coordinator is not None:
            entities.append(CandyWashTotalCyclesSensor(stats_coordinator, config_entry))
            if config_entry.data.get(CONF_KEY_MAINTENANCE_ENABLED):
                entities.append(
                    CandyWashMaintFullCheckupSensor(stats_coordinator, config_entry)
                )
                if config_entry.data.get(CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED, True):
                    entities.append(
                        CandyWashMaintLimescaleSensor(stats_coordinator, config_entry)
                    )
                if config_entry.data.get(CONF_KEY_MAINTENANCE_FILTER_ENABLED, True):
                    entities.append(
                        CandyWashMaintFilterSensor(stats_coordinator, config_entry)
                    )
        async_add_entities(entities)
    elif isinstance(coordinator.data, TumbleDryerStatus):
        async_add_entities(
            [
                CandyTumbleDryerSensor(coordinator, config_entry),
                CandyTumbleProgramSensor(coordinator, config_entry),
                CandyTumbleStatusSensor(coordinator, config_entry),
                CandyTumbleRemainingTimeSensor(coordinator, config_entry),
            ]
        )
    elif isinstance(coordinator.data, OvenStatus):
        async_add_entities(
            [
                CandyOvenSensor(coordinator, config_entry),
                CandyOvenProgramSensor(coordinator, config_entry),
                CandyOvenTempSensor(coordinator, config_entry),
            ]
        )
    elif isinstance(coordinator.data, DishwasherStatus):
        async_add_entities(
            [
                CandyDishwasherSensor(coordinator, config_entry),
                CandyDishwasherProgramSensor(coordinator, config_entry),
                CandyDishwasherRemainingTimeSensor(coordinator, config_entry),
            ]
        )
    elif isinstance(coordinator.data, WineCoolerStatus):
        wc_status = coordinator.data
        entities = [
            CandyWineCoolerSensor(coordinator, config_entry),
            CandyWineCoolerProgramSensor(coordinator, config_entry),
            CandyWineCoolerTempSensor(coordinator, config_entry),
            CandyWineCoolerLightSensor(coordinator, config_entry),
            CandyWineCoolerErrorSensor(coordinator, config_entry),
        ]
        registry = er.async_get(hass)

        def _was_wc_registered(unique_id_template: str) -> bool:
            return (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, unique_id_template.format(config_id)
                )
                is not None
            )

        if wc_status.temp_down is not None or _was_wc_registered(
            UNIQUE_ID_WINE_COOLER_TEMP_DOWN
        ):
            entities.append(CandyWineCoolerTempDownSensor(coordinator, config_entry))
        if wc_status.program_down is not None or _was_wc_registered(
            UNIQUE_ID_WINE_COOLER_PROGRAM_DOWN
        ):
            entities.append(CandyWineCoolerProgramDownSensor(coordinator, config_entry))
        async_add_entities(entities)
    else:
        raise TypeError(f"Unable to determine machine type: {coordinator.data}")


class CandyBaseSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: DataUpdateCoordinator, config_entry: ConfigEntry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.config_id = config_entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        info = DeviceInfo(
            identifiers={(DOMAIN, self.config_id)},
            name=self.device_name(),
            manufacturer="Candy",
            suggested_area=self.suggested_area(),
        )
        if self.config_entry.data.get(CONF_KEY_MAC_ADDRESS):
            info["connections"] = {
                (
                    dr.CONNECTION_NETWORK_MAC,
                    self.config_entry.data[CONF_KEY_MAC_ADDRESS],
                )
            }
        if self.config_entry.data.get(CONF_KEY_MODE) == MODE_FULL_CONTROL:
            if self.config_entry.data.get(CONF_KEY_DEVICE_MODEL):
                info["model"] = self.config_entry.data[CONF_KEY_DEVICE_MODEL]
            if self.config_entry.data.get(CONF_KEY_SERIAL_NUMBER):
                info["serial_number"] = self.config_entry.data[CONF_KEY_SERIAL_NUMBER]
        return info

    @abstractmethod
    def device_name(self) -> str:
        pass

    @abstractmethod
    def suggested_area(self) -> str:
        pass


class CandyWashingMachineSensor(CandyBaseSensor):
    _attr_translation_key = "washing_machine"
    _attr_name = "Washing machine"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASHING_MACHINE.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        if self.hass.data[DOMAIN][self.config_id].get(DATA_KEY_WRITE_PENDING, 0):
            return "Sending command"
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(WashingMachineStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "temperature": status.temp,
            "spin_speed": status.spin_speed,
            "remaining_minutes": status.remaining_minutes
            if status.machine_state in [MachineState.RUNNING, MachineState.PAUSED]
            else 0,
            "remote_control": status.remote_control,
        }

        if status.fill_percent is not None:
            attributes["fill_percent"] = status.fill_percent

        if status.program_code is not None:
            attributes["program_code"] = status.program_code

        return attributes


class CandyWashProgramSensor(CandyBaseSensor):
    _attr_translation_key = "wash_program"
    _attr_name = "Wash program"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        programs: list[WashingMachineWashProgram],
        dl_programs: list[DownloadableProgram],
    ) -> None:
        super().__init__(coordinator, config_entry)
        self._programs = programs
        self._dl_programs = dl_programs

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WashingMachineStatus, self.coordinator.data)
        lang = self.config_entry.data.get(
            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
        )
        if status.recipe_id and status.recipe_id not in ("0", ""):
            dl_match = next(
                (
                    p
                    for p in self._dl_programs
                    if p.recipe_id == status.recipe_id
                    or str(p.position) == status.recipe_id
                ),
                None,
            )
            if dl_match is not None:
                return dl_match.display_name(lang)
        match = next(
            (p for p in self._programs if p.selector_position == status.program),
            None,
        )
        if match is not None:
            return match.localized_name(lang)
        dl_match = next(
            (p for p in self._dl_programs if p.position == status.program), None
        )
        if dl_match is not None:
            return dl_match.display_name(lang)
        return status.program

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(WashingMachineStatus, self.coordinator.data)
        attrs: dict[str, Any] = {}
        if status.program_code is not None:
            attrs["program_code"] = status.program_code
        if status.recipe_id and status.recipe_id not in ("0", ""):
            attrs["recipe_id"] = status.recipe_id
        return attrs

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"


class CandyWashCycleStatusSensor(CandyBaseSensor):
    _attr_translation_key = "wash_cycle_status"
    _attr_name = "Wash cycle status"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_CYCLE_STATUS.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WashingMachineStatus, self.coordinator.data)
        return str(status.program_state)

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"


class CandyWashRemainingTimeSensor(CandyBaseSensor):
    _attr_translation_key = "wash_remaining_time"
    _attr_name = "Wash cycle remaining time"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_REMAINING_TIME.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state in [MachineState.RUNNING, MachineState.PAUSED]:
            return status.remaining_minutes
        return 0

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:progress-clock"


class CandyWashTemperatureSensor(CandyBaseSensor):
    """Set temperature selected on the washing machine."""

    _attr_translation_key = "wash_temperature"
    _attr_name = "Wash temperature"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_TEMPERATURE.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).temp

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyWashSpinSpeedSensor(CandyBaseSensor):
    """Spin speed selected on the washing machine."""

    _attr_translation_key = "wash_spin_speed"
    _attr_name = "Wash spin speed"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SPIN_SPEED.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).spin_speed

    @property
    def native_unit_of_measurement(self) -> str:
        return "rpm"

    @property
    def icon(self) -> str:
        return "mdi:rotate-right"


class CandyWashFillPercentSensor(CandyBaseSensor):
    """Water fill level in the drum (0-100%)."""

    _attr_translation_key = "wash_fill_level"
    _attr_name = "Wash fill level"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_FILL_PERCENT.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).fill_percent

    @property
    def native_unit_of_measurement(self) -> str:
        return PERCENTAGE

    @property
    def icon(self) -> str:
        return "mdi:water-percent"


class CandyWashErrorSensor(CandyBaseSensor, RestoreSensor):
    """Error code reported by the washing machine (0 = no error)."""

    _attr_translation_key = "wash_error_code"
    _attr_name = "Wash error code"
    _restored_state: int | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if isinstance(last.native_value, int):
                self._restored_state = last.native_value

    @property
    def available(self) -> bool:
        return super().available or self._restored_state is not None

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_ERROR.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is not None:
            error = cast(WashingMachineStatus, self.coordinator.data).error
            if error is not None:
                return error
        return self._restored_state

    @property
    def icon(self) -> str:
        return "mdi:alert-circle-outline"


class CandyWashDelaySensor(CandyBaseSensor):
    """Delay start value set on the washing machine."""

    _attr_translation_key = "wash_delay_start"
    _attr_name = "Wash delay start"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DELAY.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).delay_value

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:timer-sand"


class CandyWashNtcWaterSensor(CandyBaseSensor):
    """Raw NTC water temperature sensor reading."""

    _attr_translation_key = "wash_ntc_water"
    _attr_name = "Wash NTC water"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_NTC_WATER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).ntc_water

    @property
    def icon(self) -> str:
        return "mdi:thermometer-water"


class CandyWashNtcDrumSensor(CandyBaseSensor):
    """Raw NTC drum temperature sensor reading."""

    _attr_translation_key = "wash_ntc_drum"
    _attr_name = "Wash NTC drum"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_NTC_DRUM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).ntc_drum

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyWashMotorFreqSensor(CandyBaseSensor):
    """Motor APS frequency reported by the washing machine."""

    _attr_translation_key = "wash_motor_frequency"
    _attr_name = "Wash motor frequency"

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_MOTOR_FREQ.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).motor_speed_freq

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfFrequency.HERTZ

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.FREQUENCY

    @property
    def icon(self) -> str:
        return "mdi:sine-wave"


class CandyWashSoilLevelSensor(CandyBaseSensor):
    """Current stain level reported by the washing machine."""

    _attr_translation_key = "wash_soil_level"
    _attr_name = "Wash stain level"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SOIL_LABELS.values())

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SOIL_LEVEL.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        level = cast(WashingMachineStatus, self.coordinator.data).soil_level
        return SOIL_LABELS.get(level) if level is not None else None

    @property
    def icon(self) -> str:
        return "mdi:water-opacity"


class CandyWashDryPhaseSensor(CandyBaseSensor):
    """Drying phase currently attached to the running wash program, if any."""

    _attr_translation_key = "wash_dry_phase"
    _attr_name = "Wash drying phase"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["off", *DRY_LABELS.values()]

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DRY_PHASE.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        dry_type = cast(WashingMachineStatus, self.coordinator.data).dry_type
        if not dry_type:
            return "off"
        return DRY_LABELS.get(dry_type)

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"


class CandyWashCheckUpResultSensor(CandyBaseSensor, RestoreSensor):
    """Result of the last completed automatic diagnostic (DisTestRes)."""

    _attr_translation_key = "wash_checkup_result"
    _attr_name = "Last check-up result"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["not_run", "ok", "problem"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _restored_state: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            if last.native_value in self._attr_options:
                self._restored_state = str(last.native_value)

    @property
    def available(self) -> bool:
        return super().available or self._restored_state is not None

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_CHECKUP_RESULT.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        _code_to_state = {1: "ok", 2: "problem"}
        if self.coordinator.data is not None:
            result = cast(WashingMachineStatus, self.coordinator.data).dis_test_res
            if result is not None:
                if result.code != 0:
                    return _code_to_state.get(result.code)
                cached = self.config_entry.data.get(CONF_KEY_CHECKUP_LAST_RESULT)
                if cached in _code_to_state:
                    return _code_to_state[cached]
                return "not_run"
        return self._restored_state

    @property
    def icon(self) -> str:
        return "mdi:stethoscope"


class CandyWashLastCheckUpSensor(CandyBaseSensor):
    """Timestamp of the last completed automatic diagnostic."""

    _attr_translation_key = "wash_last_checkup"
    _attr_name = "Last check-up"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def available(self) -> bool:
        return True

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_LAST_CHECKUP.format(self.config_id)

    @property
    def native_value(self) -> datetime.datetime | None:
        ts = self.config_entry.data.get(CONF_KEY_CHECKUP_LAST_DATE)
        if ts is None:
            return None
        return dt_util.utc_from_timestamp(ts)

    @property
    def icon(self) -> str:
        return "mdi:calendar-check"


class CandyWashPurchaseDateSensor(CandyBaseSensor):
    """Purchase date of the appliance, as reported by the cloud API."""

    _attr_translation_key = "wash_purchase_date"
    _attr_name = "Purchase date"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def available(self) -> bool:
        return True

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_PURCHASE_DATE.format(self.config_id)

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DATE

    @property
    def native_value(self) -> datetime.date | None:
        raw = self.config_entry.data.get(CONF_KEY_PURCHASE_DATE)
        if not raw:
            return None
        return datetime.date.fromisoformat(raw)

    @property
    def icon(self) -> str:
        return "mdi:calendar"


class CandyWashTotalCyclesSensor(CandyBaseSensor, RestoreSensor):
    """Total number of wash cycles completed by the washing machine."""

    _attr_translation_key = "wash_total_cycles"
    _attr_name = "Total wash cycles"
    _restored_cycles: int | None = None
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._restored_cycles = int(str(last.native_value))

    @property
    def available(self) -> bool:
        return super().available or self._restored_cycles is not None

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_TOTAL_CYCLES.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is not None:
            return cast(WashingMachineStatistics, self.coordinator.data).total_cycles
        return self._restored_cycles

    @property
    def icon(self) -> str:
        return "mdi:counter"


class CandyWashMaintFullCheckupSensor(CandyBaseSensor, RestoreSensor):
    """Cycles remaining until the next Full Check-up is due."""

    _attr_has_entity_name = True
    _attr_translation_key = "wash_maint_full_checkup"
    _attr_name = "Check-up maintenance remaining cycles"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _restored_value: int | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._restored_value = int(str(last.native_value))

    @property
    def available(self) -> bool:
        return super().available or self._restored_value is not None

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_MAINT_FULL_CHECKUP.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is not None:
            total = cast(WashingMachineStatistics, self.coordinator.data).total_cycles
            last = self.config_entry.data.get(CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP, 0)
            return cycles_remaining(total, last, MAINTENANCE_FULL_CHECKUP_THRESHOLD)
        return self._restored_value

    @property
    def icon(self) -> str:
        return "mdi:washing-machine"


class CandyWashMaintLimescaleSensor(CandyBaseSensor, RestoreSensor):
    """Cycles remaining until the next descale is due."""

    _attr_has_entity_name = True
    _attr_translation_key = "wash_maint_limescale"
    _attr_name = "Limescale maintenance remaining cycles"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _restored_value: int | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._restored_value = int(str(last.native_value))

    @property
    def available(self) -> bool:
        return super().available or self._restored_value is not None

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_MAINT_LIMESCALE.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is not None:
            total = cast(WashingMachineStatistics, self.coordinator.data).total_cycles
            last = self.config_entry.data.get(CONF_KEY_MAINTENANCE_LAST_LIMESCALE, 0)
            hardness = self.config_entry.data.get(CONF_KEY_WATER_HARDNESS, 2)
            threshold = MAINTENANCE_HARDNESS_THRESHOLDS[hardness]
            return cycles_remaining(total, last, threshold)
        return self._restored_value

    @property
    def icon(self) -> str:
        return "mdi:water-alert"


class CandyWashMaintFilterSensor(CandyBaseSensor, RestoreSensor):
    """Cycles remaining until the next filter clean is due."""

    _attr_has_entity_name = True
    _attr_translation_key = "wash_maint_filter"
    _attr_name = "Filter maintenance remaining cycles"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _restored_value: int | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._restored_value = int(str(last.native_value))

    @property
    def available(self) -> bool:
        return super().available or self._restored_value is not None

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_MAINT_FILTER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        if self.coordinator.data is not None:
            total = cast(WashingMachineStatistics, self.coordinator.data).total_cycles
            last = self.config_entry.data.get(CONF_KEY_MAINTENANCE_LAST_FILTER, 0)
            return cycles_remaining(total, last, MAINTENANCE_FILTER_THRESHOLD)
        return self._restored_value

    @property
    def icon(self) -> str:
        return "mdi:filter-check"


class CandyWashEstimatedDurationSensor(CandyBaseSensor):
    """Estimated cycle duration based on the selected program and soil level."""

    _attr_translation_key = "wash_estimated_duration"
    _attr_name = "Estimated cycle duration"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry)
        self._programs = programs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        watch_ids = []
        for uid in (UNIQUE_ID_WASH_PROGRAM_SELECT, UNIQUE_ID_WASH_SOIL_SELECT):
            eid = registry.async_get_entity_id(
                "select", DOMAIN, uid.format(self.config_id)
            )
            if eid:
                watch_ids.append(eid)
        if watch_ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, watch_ids, self._on_select_changed
                )
            )

        async def _subscribe_steam() -> None:
            steam_eid = registry.async_get_entity_id(
                "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)
            )
            if steam_eid:
                self.async_on_remove(
                    async_track_state_change_event(
                        self.hass, [steam_eid], self._on_select_changed
                    )
                )

        self.hass.async_create_task(_subscribe_steam())

    @callback
    def _on_select_changed(self, event) -> None:
        self.async_write_ha_state()

    def _steam_selected(self, registry) -> bool:
        eid = registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)
        )
        state = self.hass.states.get(eid) if eid else None
        return state is not None and state.state == "on"

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state in (
            MachineState.IDLE,
            MachineState.DELAYED_START_SELECTION,
            MachineState.DELAYED_START_PROGRAMMED,
        )

    @property
    def native_value(self) -> StateType:
        registry = er.async_get(self.hass)

        prog_eid = registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)
        )
        prog_state = self.hass.states.get(prog_eid) if prog_eid else None
        if prog_state is not None and prog_state.state not in (
            "unavailable",
            "unknown",
        ):
            program = next(
                (
                    p
                    for p in self._programs
                    if p.localized_name(
                        self.config_entry.data.get(
                            CONF_KEY_PROGRAM_LANGUAGE, self.hass.config.language
                        )
                    )
                    == prog_state.state
                ),
                None,
            )
        else:
            status = cast(WashingMachineStatus, self.coordinator.data)
            program = next(
                (p for p in self._programs if p.selector_position == status.program),
                None,
            )

        if program is None:
            if prog_state is not None and prog_state.state not in (
                "unavailable",
                "unknown",
            ):
                nfc_duration = prog_state.attributes.get("duration_minutes")
                if nfc_duration and int(nfc_duration) > 0:
                    return int(nfc_duration)
            return None

        if program.min_soil_level < program.max_soil_level:
            soil_eid = registry.async_get_entity_id(
                "select", DOMAIN, UNIQUE_ID_WASH_SOIL_SELECT.format(self.config_id)
            )
            soil_state = self.hass.states.get(soil_eid) if soil_eid else None
            if soil_state is not None and soil_state.state not in (
                "unavailable",
                "unknown",
            ):
                try:
                    soil = SOIL_LABELS_REVERSE[soil_state.state]
                except KeyError:
                    soil = program.default_soil_level
            else:
                device_status = cast(WashingMachineStatus, self.coordinator.data)
                if (
                    device_status.soil_level is not None
                    and program.min_soil_level
                    <= device_status.soil_level
                    <= program.max_soil_level
                ):
                    soil = device_status.soil_level
                else:
                    soil = program.default_soil_level

            if soil <= 1:
                minutes = program.duration_soil_min
            elif soil == 2:
                minutes = program.duration_soil_medium
            else:
                minutes = program.duration_soil_max
        else:
            minutes = program.default_duration

        if (
            minutes > 0
            and program.steam_type in STEAM_DURATION_OFFSETS
            and self._steam_selected(registry)
        ):
            minutes += STEAM_DURATION_OFFSETS[program.steam_type]

        return minutes if minutes > 0 else None

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_ESTIMATED_DURATION.format(self.config_id)

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def icon(self) -> str:
        return "mdi:timer-outline"


def _read_delay_minutes(hass, config_id) -> int:
    """Return the current delay in minutes from WashDelayNumber entity, falling back to coordinator data."""
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(config_id)
    )
    state = hass.states.get(eid) if eid else None
    if state is not None and state.state not in ("unavailable", "unknown"):
        return int(float(state.state))
    status = cast(
        WashingMachineStatus,
        hass.data[DOMAIN][config_id][DATA_KEY_COORDINATOR].data,
    )
    return status.delay_value or 0


class CandyWashScheduledStartSensor(CandyBaseSensor):
    """Scheduled start: now + delay. Only available when delay > 0 and machine is idle."""

    _attr_translation_key = "wash_scheduled_start"
    _attr_name = "Wash scheduled start"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        eid = registry.async_get_entity_id(
            "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(self.config_id)
        )
        if eid:
            self.async_on_remove(
                async_track_state_change_event(self.hass, [eid], self._on_dep_changed)
            )

    @callback
    def _on_dep_changed(self, event) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state not in (
            MachineState.IDLE,
            MachineState.DELAYED_START_SELECTION,
            MachineState.DELAYED_START_PROGRAMMED,
        ):
            return False
        return _read_delay_minutes(self.hass, self.config_id) > 0

    @property
    def native_value(self) -> datetime.datetime | None:
        delay = _read_delay_minutes(self.hass, self.config_id)
        if delay <= 0:
            return None
        return dt_util.now() + datetime.timedelta(minutes=delay)

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TIMESTAMP

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SCHEDULED_START.format(self.config_id)

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def icon(self) -> str:
        return "mdi:clock-start"


class CandyWashScheduledFinishSensor(CandyBaseSensor):
    """Scheduled finish: now + remaining (RUNNING/PAUSED) or now + delay + duration (IDLE)."""

    _attr_translation_key = "wash_scheduled_finish"
    _attr_name = "Wash scheduled finish"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        watch_ids = []
        domain_uid_pairs = [
            ("number", UNIQUE_ID_WASH_DELAY_NUMBER),
            ("select", UNIQUE_ID_WASH_PROGRAM_SELECT),
            ("select", UNIQUE_ID_WASH_SOIL_SELECT),
        ]
        for domain, uid in domain_uid_pairs:
            eid = registry.async_get_entity_id(
                domain, DOMAIN, uid.format(self.config_id)
            )
            if eid:
                watch_ids.append(eid)
        if watch_ids:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, watch_ids, self._on_dep_changed
                )
            )

        async def _subscribe_steam() -> None:
            steam_eid = registry.async_get_entity_id(
                "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(self.config_id)
            )
            if steam_eid:
                self.async_on_remove(
                    async_track_state_change_event(
                        self.hass, [steam_eid], self._on_dep_changed
                    )
                )

        self.hass.async_create_task(_subscribe_steam())

    @callback
    def _on_dep_changed(self, event) -> None:
        self.async_write_ha_state()

    def _estimated_duration_minutes(self) -> int | None:
        """Return the current value of the estimated duration sensor, or None."""
        registry = er.async_get(self.hass)
        eid = registry.async_get_entity_id(
            "sensor", DOMAIN, UNIQUE_ID_WASH_ESTIMATED_DURATION.format(self.config_id)
        )
        state = self.hass.states.get(eid) if eid else None
        if state is not None and state.state not in ("unavailable", "unknown"):
            with contextlib.suppress(ValueError):
                minutes = int(float(state.state))
                if minutes > 0:
                    return minutes
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state in (MachineState.RUNNING, MachineState.PAUSED):
            return (status.remaining_minutes or 0) > 0
        if status.machine_state in (
            MachineState.IDLE,
            MachineState.DELAYED_START_SELECTION,
            MachineState.DELAYED_START_PROGRAMMED,
        ):
            return self._estimated_duration_minutes() is not None
        return False

    @property
    def native_value(self) -> datetime.datetime | None:
        status = cast(WashingMachineStatus, self.coordinator.data)
        if status.machine_state in (MachineState.RUNNING, MachineState.PAUSED):
            remaining = status.remaining_minutes or 0
            if remaining <= 0:
                return None
            return dt_util.now() + datetime.timedelta(minutes=remaining)
        if status.machine_state in (
            MachineState.IDLE,
            MachineState.DELAYED_START_SELECTION,
            MachineState.DELAYED_START_PROGRAMMED,
        ):
            estimated = self._estimated_duration_minutes()
            if estimated is None:
                return None
            delay = _read_delay_minutes(self.hass, self.config_id)
            return dt_util.now() + datetime.timedelta(minutes=delay + estimated)
        return None

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TIMESTAMP

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_SCHEDULED_FINISH.format(self.config_id)

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def icon(self) -> str:
        return "mdi:clock-end"


def _resolve_program_from_select(
    hass,
    config_entry: ConfigEntry,
    programs: list[WashingMachineWashProgram],
) -> WashingMachineWashProgram | None:
    """Return the currently selected program, preferring the program-select entity state."""
    registry = er.async_get(hass)
    config_id = config_entry.entry_id
    lang = config_entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, hass.config.language)

    prog_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(config_id)
    )
    prog_state = hass.states.get(prog_eid) if prog_eid else None
    if prog_state is not None and prog_state.state not in ("unavailable", "unknown"):
        return next(
            (p for p in programs if p.localized_name(lang) == prog_state.state),
            None,
        )
    status = cast(
        WashingMachineStatus, hass.data[DOMAIN][config_id][DATA_KEY_COORDINATOR].data
    )
    return next(
        (p for p in programs if p.selector_position == status.program),
        None,
    )


class _CandyWashProgramAttributeSensor(CandyBaseSensor):
    """Base for sensors that track a per-program attribute from the Simply-Fi catalog."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config_entry: ConfigEntry,
        programs: list[WashingMachineWashProgram],
    ) -> None:
        super().__init__(coordinator, config_entry)
        self._programs = programs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        eid = registry.async_get_entity_id(
            "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_SELECT.format(self.config_id)
        )
        if eid:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [eid], self._on_program_changed
                )
            )

    @callback
    def _on_program_changed(self, event) -> None:
        self.async_write_ha_state()

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    def _current_program(self) -> WashingMachineWashProgram | None:
        return _resolve_program_from_select(
            self.hass, self.config_entry, self._programs
        )


class CandyWashLiquidDetergentSensor(_CandyWashProgramAttributeSensor):
    """Suggested liquid detergent dose for the selected program (1–4 scale)."""

    _attr_translation_key = "wash_liquid_detergent"
    _attr_name = "Wash liquid detergent dose"
    _attr_icon = "mdi:bottle-tonic"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_LIQUID_DETERGENT.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        program = self._current_program()
        if program is None or program.liquid_detergent_dose is None:
            return None
        return f"{program.liquid_detergent_dose}/4"


class CandyWashPowderDetergentSensor(_CandyWashProgramAttributeSensor):
    """Suggested powder detergent dose for the selected program (1–4 scale)."""

    _attr_translation_key = "wash_powder_detergent"
    _attr_name = "Wash powder detergent dose"
    _attr_icon = "mdi:shaker-outline"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_POWDER_DETERGENT.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        program = self._current_program()
        if program is None or program.powder_detergent_dose is None:
            return None
        return f"{program.powder_detergent_dose}/4"


class CandyWashCycleCapacitySensor(_CandyWashProgramAttributeSensor):
    """Maximum recommended load in kg for the selected program."""

    _attr_translation_key = "wash_cycle_capacity"
    _attr_name = "Wash max cycle capacity"
    _attr_icon = "mdi:weight-kilogram"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_CYCLE_CAPACITY.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        program = self._current_program()
        if program is None or program.max_cycle_capacity is None:
            return None
        return program.max_cycle_capacity

    @property
    def native_unit_of_measurement(self) -> str:
        return "kg"


class CandyTumbleDryerSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_dryer"
    _attr_name = "Tumble dryer"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_DRYER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(TumbleDryerStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "remaining_minutes": status.remaining_minutes,
            "remote_control": status.remote_control,
            "dry_level": status.dry_level,
            "dry_level_now": status.dry_level_selected,
            "refresh": status.refresh,
            "need_clean_filter": status.need_clean_filter,
            "water_tank_full": status.water_tank_full,
            "door_closed": status.door_closed,
        }

        return attributes


class CandyTumbleProgramSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_program"
    _attr_name = "Dryer program"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.program

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"


class CandyTumbleStatusSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_cycle_status"
    _attr_name = "Dryer cycle status"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_CYCLE_STATUS.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        if status.program_state in [DryerProgramState.STOPPED]:
            return str(status.cycle_state)
        return str(status.program_state)

    @property
    def icon(self) -> str:
        return "mdi:tumble-dryer"


class CandyTumbleRemainingTimeSensor(CandyBaseSensor):
    _attr_translation_key = "tumble_remaining_time"
    _attr_name = "Dryer cycle remaining time"

    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_REMAINING_TIME.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(TumbleDryerStatus, self.coordinator.data)
        if status.machine_state in [MachineState.RUNNING, MachineState.PAUSED]:
            return status.remaining_minutes
        return 0

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:progress-clock"


class CandyOvenSensor(CandyBaseSensor):
    _attr_translation_key = "oven"
    _attr_name = "Oven"

    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_OVEN.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(OvenStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:stove"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(OvenStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "selection": status.selection,
            "temperature": status.temp,
            "temperature_reached": status.temp_reached,
            "remote_control": status.remote_control,
        }

        if status.program_length_minutes is not None:
            attributes["program_length_minutes"] = status.program_length_minutes

        return attributes


class CandyOvenProgramSensor(CandyBaseSensor):
    _attr_translation_key = "oven_program"
    _attr_name = "Oven program"

    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_OVEN_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(OvenStatus, self.coordinator.data)
        return status.program

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(OvenStatus, self.coordinator.data)
        return {"selection": status.selection}

    @property
    def icon(self) -> str:
        return "mdi:stove"


class CandyOvenTempSensor(CandyBaseSensor):
    _attr_translation_key = "oven_temperature"
    _attr_name = "Oven temperature"

    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_OVEN_TEMP.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(OvenStatus, self.coordinator.data)
        return status.temp

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyDishwasherSensor(CandyBaseSensor):
    _attr_translation_key = "dishwasher"
    _attr_name = "Dishwasher"

    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(DishwasherStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:glass-wine"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(DishwasherStatus, self.coordinator.data)

        attributes = {
            "program": status.program,
            "remaining_minutes": 0
            if status.machine_state in [DishwasherState.IDLE, DishwasherState.FINISHED]
            else status.remaining_minutes,
            "remote_control": status.remote_control,
            "door_open": status.door_open,
            "eco_mode": status.eco_mode,
            "salt_empty": status.salt_empty,
            "rinse_aid_empty": status.rinse_aid_empty,
        }

        if status.door_open_allowed is not None:
            attributes["door_open_allowed"] = status.door_open_allowed

        if status.delayed_start_hours is not None:
            attributes["delayed_start_hours"] = status.delayed_start_hours

        return attributes


class CandyDishwasherProgramSensor(CandyBaseSensor):
    _attr_translation_key = "dishwasher_program"
    _attr_name = "Dishwasher program"

    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(DishwasherStatus, self.coordinator.data)
        return status.program

    @property
    def icon(self) -> str:
        return "mdi:glass-wine"


class CandyDishwasherRemainingTimeSensor(CandyBaseSensor):
    _attr_translation_key = "dishwasher_remaining_time"
    _attr_name = "Dishwasher remaining time"

    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_DISHWASHER_REMAINING_TIME.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(DishwasherStatus, self.coordinator.data)
        if status.machine_state in [DishwasherState.IDLE, DishwasherState.FINISHED]:
            return 0
        return status.remaining_minutes

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.MINUTES

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.DURATION

    @property
    def icon(self) -> str:
        return "mdi:progress-clock"


class CandyWineCoolerSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WINE_COOLER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return self.device_name()

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WINE_COOLER.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return str(status.machine_state)

    @property
    def icon(self) -> str:
        return "mdi:glass-wine"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        status = cast(WineCoolerStatus, self.coordinator.data)
        attributes: dict[str, Any] = {
            "program": str(status.program),
            "target_temperature": status.temp,
            "light": status.light,
            "remote_control": status.remote_control,
            "error": status.error,
        }
        if status.temp_down is not None:
            attributes["target_temperature_zone_down"] = status.temp_down
        if status.program_down is not None:
            attributes["program_zone_down"] = str(status.program_down)
        return attributes


class CandyWineCoolerProgramSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WINE_COOLER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return "Wine cooler program"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WINE_COOLER_PROGRAM.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return str(status.program)

    @property
    def icon(self) -> str:
        return "mdi:bottle-wine"


class CandyWineCoolerTempSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WINE_COOLER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return "Wine cooler target temperature"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WINE_COOLER_TEMP.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return status.temp

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyWineCoolerLightSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WINE_COOLER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return "Wine cooler light"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WINE_COOLER_LIGHT.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return "On" if status.light else "Off"

    @property
    def icon(self) -> str:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return "mdi:lightbulb" if status.light else "mdi:lightbulb-off"


class CandyWineCoolerErrorSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WINE_COOLER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def entity_category(self) -> EntityCategory:
        return EntityCategory.DIAGNOSTIC

    @property
    def name(self) -> str:
        return "Wine cooler error code"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WINE_COOLER_ERROR.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return status.error if status.error is not None else "None"

    @property
    def icon(self) -> str:
        return "mdi:alert-circle"


class CandyWineCoolerTempDownSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WINE_COOLER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return "Wine cooler lower zone target temperature"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WINE_COOLER_TEMP_DOWN.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return status.temp_down

    @property
    def device_class(self) -> SensorDeviceClass:
        return SensorDeviceClass.TEMPERATURE

    @property
    def state_class(self) -> SensorStateClass:
        return SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyWineCoolerProgramDownSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WINE_COOLER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return "Wine cooler lower zone program"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WINE_COOLER_PROGRAM_DOWN.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return str(status.program_down) if status.program_down is not None else None

    @property
    def icon(self) -> str:
        return "mdi:bottle-wine"
