"""Light platform for Candy integration."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import CandyClient
from .client.model import WineCoolerStatus
from .const import (
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DEVICE_NAME_WINE_COOLER,
    DEVICE_TRANSLATION_KEYS,
    DOMAIN,
    SUGGESTED_AREA_KITCHEN,
    UNIQUE_ID_WINE_COOLER_LIGHT_ENTITY,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Candy light entities."""
    config_id = config_entry.entry_id
    coordinator: DataUpdateCoordinator[Any] = hass.data[DOMAIN][config_id][
        DATA_KEY_COORDINATOR
    ]
    client: CandyClient = hass.data[DOMAIN][config_id][DATA_KEY_CLIENT]

    if isinstance(coordinator.data, WineCoolerStatus):
        async_add_entities([CandyWineCoolerLight(coordinator, client, config_id)])


class CandyWineCoolerLight(CoordinatorEntity[DataUpdateCoordinator[Any]], LightEntity):
    """Controllable light entity for Candy Wine Cooler."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    _attr_has_entity_name = True
    _attr_translation_key = "wine_cooler_light"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[Any],
        client: CandyClient,
        config_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.client = client
        self.config_id = config_id
        self._attr_unique_id = UNIQUE_ID_WINE_COOLER_LIGHT_ENTITY.format(config_id)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_id)},
            name=DEVICE_NAME_WINE_COOLER,
            translation_key=DEVICE_TRANSLATION_KEYS[DEVICE_NAME_WINE_COOLER],
            manufacturer="Candy",
            suggested_area=SUGGESTED_AREA_KITCHEN,
        )

    @property
    def is_on(self) -> bool:
        status = cast(WineCoolerStatus, self.coordinator.data)
        return bool(status.light) if status is not None else False

    @property
    def icon(self) -> str:
        return "mdi:lightbulb" if self.is_on else "mdi:lightbulb-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the wine cooler light."""
        status = cast(WineCoolerStatus, self.coordinator.data)
        if status is not None:
            await self.client.set_wine_cooler_light(True, status)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the wine cooler light."""
        status = cast(WineCoolerStatus, self.coordinator.data)
        if status is not None:
            await self.client.set_wine_cooler_light(False, status)
            await self.coordinator.async_request_refresh()
