from abc import abstractmethod
from collections.abc import Mapping
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import WashingMachineStatus
from .client.model import (
    DishwasherState,
    DishwasherStatus,
    DryerProgramState,
    MachineState,
    OvenStatus,
    TumbleDryerStatus,
)
from .const import (
    DATA_KEY_COORDINATOR,
    DEVICE_NAME_DISHWASHER,
    DEVICE_NAME_OVEN,
    DEVICE_NAME_TUMBLE_DRYER,
    DEVICE_NAME_WASHING_MACHINE,
    DOMAIN,
    SUGGESTED_AREA_BATHROOM,
    SUGGESTED_AREA_KITCHEN,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_DISHWASHER_REMAINING_TIME,
    UNIQUE_ID_OVEN,
    UNIQUE_ID_OVEN_TEMP,
    UNIQUE_ID_TUMBLE_CYCLE_STATUS,
    UNIQUE_ID_TUMBLE_DRYER,
    UNIQUE_ID_TUMBLE_REMAINING_TIME,
    UNIQUE_ID_WASH_CYCLE_STATUS,
    UNIQUE_ID_WASH_DELAY,
    UNIQUE_ID_WASH_ERROR,
    UNIQUE_ID_WASH_FILL_PERCENT,
    UNIQUE_ID_WASH_MOTOR_FREQ,
    UNIQUE_ID_WASH_NTC_DRUM,
    UNIQUE_ID_WASH_NTC_WATER,
    UNIQUE_ID_WASH_REMAINING_TIME,
    UNIQUE_ID_WASH_SPIN_SPEED,
    UNIQUE_ID_WASH_TEMPERATURE,
    UNIQUE_ID_WASHING_MACHINE,
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Set up the Candy sensors from config entry."""

    config_id = config_entry.entry_id
    coordinator = hass.data[DOMAIN][config_id][DATA_KEY_COORDINATOR]

    if isinstance(coordinator.data, WashingMachineStatus):
        status = coordinator.data
        entities: list[CandyBaseSensor] = [
            CandyWashingMachineSensor(coordinator, config_id),
            CandyWashCycleStatusSensor(coordinator, config_id),
            CandyWashRemainingTimeSensor(coordinator, config_id),
            CandyWashTemperatureSensor(coordinator, config_id),
            CandyWashSpinSpeedSensor(coordinator, config_id),
            CandyWashErrorSensor(coordinator, config_id),
        ]
        if status.fill_percent is not None:
            entities.append(CandyWashFillPercentSensor(coordinator, config_id))
        if status.delay_value is not None:
            entities.append(CandyWashDelaySensor(coordinator, config_id))
        if status.ntc_water is not None:
            entities.append(CandyWashNtcWaterSensor(coordinator, config_id))
        if status.ntc_drum is not None:
            entities.append(CandyWashNtcDrumSensor(coordinator, config_id))
        if status.motor_speed_freq is not None:
            entities.append(CandyWashMotorFreqSensor(coordinator, config_id))
        async_add_entities(entities)
    elif isinstance(coordinator.data, TumbleDryerStatus):
        async_add_entities(
            [
                CandyTumbleDryerSensor(coordinator, config_id),
                CandyTumbleStatusSensor(coordinator, config_id),
                CandyTumbleRemainingTimeSensor(coordinator, config_id),
            ]
        )
    elif isinstance(coordinator.data, OvenStatus):
        async_add_entities(
            [
                CandyOvenSensor(coordinator, config_id),
                CandyOvenTempSensor(coordinator, config_id),
            ]
        )
    elif isinstance(coordinator.data, DishwasherStatus):
        async_add_entities(
            [
                CandyDishwasherSensor(coordinator, config_id),
                CandyDishwasherRemainingTimeSensor(coordinator, config_id),
            ]
        )
    else:
        raise TypeError(f"Unable to determine machine type: {coordinator.data}")


class CandyBaseSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: DataUpdateCoordinator, config_id: str):
        super().__init__(coordinator)
        self.config_id = config_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_id)},
            name=self.device_name(),
            manufacturer="Candy",
            suggested_area=self.suggested_area(),
        )

    @abstractmethod
    def device_name(self) -> str:
        pass

    @abstractmethod
    def suggested_area(self) -> str:
        pass


class CandyWashingMachineSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return self.device_name()

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASHING_MACHINE.format(self.config_id)

    @property
    def native_value(self) -> StateType:
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


class CandyWashCycleStatusSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash cycle status"

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
    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash cycle remaining time"

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
    def icon(self) -> str:
        return "mdi:progress-clock"


class CandyWashTemperatureSensor(CandyBaseSensor):
    """Set temperature selected on the washing machine."""

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash temperature"

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

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash spin speed"

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

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash fill level"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_FILL_PERCENT.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).fill_percent

    @property
    def native_unit_of_measurement(self) -> str:
        return "%"

    @property
    def icon(self) -> str:
        return "mdi:water-percent"


class CandyWashErrorSensor(CandyBaseSensor):
    """Error code reported by the washing machine (0 = no error)."""

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash error code"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_ERROR.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).error

    @property
    def icon(self) -> str:
        return "mdi:alert-circle-outline"


class CandyWashDelaySensor(CandyBaseSensor):
    """Delay start value set on the washing machine."""

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash delay start"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DELAY.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).delay_value

    @property
    def native_unit_of_measurement(self) -> str:
        return UnitOfTime.HOURS

    @property
    def icon(self) -> str:
        return "mdi:timer-sand"


class CandyWashNtcWaterSensor(CandyBaseSensor):
    """Raw NTC water temperature sensor reading."""

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash NTC water"

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

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash NTC drum"

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

    def device_name(self) -> str:
        return DEVICE_NAME_WASHING_MACHINE

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Wash motor frequency"

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_MOTOR_FREQ.format(self.config_id)

    @property
    def native_value(self) -> StateType:
        return cast(WashingMachineStatus, self.coordinator.data).motor_speed_freq

    @property
    def native_unit_of_measurement(self) -> str:
        return "Hz"

    @property
    def icon(self) -> str:
        return "mdi:sine-wave"


class CandyTumbleDryerSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return self.device_name()

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


class CandyTumbleStatusSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Dryer cycle status"

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
    def device_name(self) -> str:
        return DEVICE_NAME_TUMBLE_DRYER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_BATHROOM

    @property
    def name(self) -> str:
        return "Dryer cycle remaining time"

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
    def icon(self) -> str:
        return "mdi:progress-clock"


class CandyOvenSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return self.device_name()

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


class CandyOvenTempSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_OVEN

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return "Oven temperature"

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
    def icon(self) -> str:
        return "mdi:thermometer"


class CandyDishwasherSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return self.device_name()

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


class CandyDishwasherRemainingTimeSensor(CandyBaseSensor):
    def device_name(self) -> str:
        return DEVICE_NAME_DISHWASHER

    def suggested_area(self) -> str:
        return SUGGESTED_AREA_KITCHEN

    @property
    def name(self) -> str:
        return "Dishwasher remaining time"

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
    def icon(self) -> str:
        return "mdi:progress-clock"
