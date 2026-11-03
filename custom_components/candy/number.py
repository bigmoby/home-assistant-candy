from __future__ import annotations

from typing import cast

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import CandyClient, WashingMachineStatus
from .client.model import MachineState, TumbleDryerStatus
from .const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MODE,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DOMAIN,
    MODE_FULL_CONTROL,
    UNIQUE_ID_TUMBLE_DELAY_NUMBER,
    UNIQUE_ID_WASH_DELAY_NUMBER,
)
from .helpers import (
    dryer_device_info,
    is_dualtech,
    remote_control_enabled,
    wash_device_info,
)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
) -> None:
    config_id = config_entry.entry_id

    if config_entry.data.get(CONF_KEY_MODE) != MODE_FULL_CONTROL:
        return

    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][config_id][
        DATA_KEY_COORDINATOR
    ]
    if isinstance(coordinator.data, WashingMachineStatus):
        client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
        async_add_entities([WashDelayNumber(coordinator, config_entry, client)])
    elif isinstance(coordinator.data, TumbleDryerStatus):
        client = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]
        async_add_entities([CandyDryerDelayNumber(coordinator, config_entry, client)])


class WashDelayNumber(CoordinatorEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 1380
    _attr_native_step = 30
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"
    _attr_name = "Wash delay"
    _attr_translation_key = "wash_delay_number"

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
        self._delay_minutes: int = 0
        if is_dualtech(config_entry.data.get(CONF_KEY_INTERFACE_TYPE, "")):
            self._attr_native_step = 60

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_WASH_DELAY_NUMBER.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if not remote_control_enabled(self.coordinator.data):
            return False
        status = cast(WashingMachineStatus, self.coordinator.data)
        return status.machine_state in {
            MachineState.IDLE,
            MachineState.OFF,
            MachineState.FINISHED1,
            MachineState.FINISHED2,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return wash_device_info(self.config_entry)

    @property
    def native_value(self) -> float:
        return self._delay_minutes

    async def async_set_native_value(self, value: float) -> None:
        self._delay_minutes = int(value)
        self.async_write_ha_state()


class CandyDryerDelayNumber(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 60
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"
    _attr_translation_key = "dryer_delay_number"

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
        self._delay_minutes: int = 0

    @property
    def unique_id(self) -> str:
        return UNIQUE_ID_TUMBLE_DELAY_NUMBER.format(self.config_id)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if not remote_control_enabled(self.coordinator.data):
            return False
        status = cast(TumbleDryerStatus, self.coordinator.data)
        return status.machine_state in {
            MachineState.IDLE,
            MachineState.FINISHED1,
            MachineState.FINISHED2,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return dryer_device_info(self.config_entry)

    @property
    def native_value(self) -> float:
        return self._delay_minutes

    async def async_set_native_value(self, value: float) -> None:
        self._delay_minutes = int(value)
        self.async_write_ha_state()
