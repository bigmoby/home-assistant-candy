"""DataUpdateCoordinator for Candy integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import CandyClient
from .client.model import WashingMachineStatus


class CandyDataUpdateCoordinator(DataUpdateCoordinator[Any]):
    """Data update coordinator for Candy devices with compound state handling."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        name: str,
        update_interval: timedelta,
        update_method: Callable[[], Any],
        client: CandyClient,
    ) -> None:
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=update_interval,
            update_method=update_method,
        )
        self.client = client
        self._autodose_lock = asyncio.Lock()
        self._desired_detergent: bool | None = None
        self._desired_softener: bool | None = None

    def sync_autodose_state(self, status: Any) -> None:
        """Sync desired autodose state from fresh telemetry when no command is in flight."""
        if not self._autodose_lock.locked() and isinstance(
            status, WashingMachineStatus
        ):
            if status.detergent_on is not None:
                self._desired_detergent = bool(status.detergent_on)
            if status.softener_on is not None:
                self._desired_softener = bool(status.softener_on)

    def _resolve_target_detergent(self) -> bool:
        if self._desired_detergent is not None:
            return self._desired_detergent
        if (
            isinstance(self.data, WashingMachineStatus)
            and self.data.detergent_on is not None
        ):
            return bool(self.data.detergent_on)
        return False

    def _resolve_target_softener(self) -> bool:
        if self._desired_softener is not None:
            return self._desired_softener
        if (
            isinstance(self.data, WashingMachineStatus)
            and self.data.softener_on is not None
        ):
            return bool(self.data.softener_on)
        return False

    async def async_set_detergent_autodose(self, detergent_on: bool) -> None:
        """Set detergent autodose state."""
        self._desired_detergent = detergent_on
        target_soft = self._resolve_target_softener()
        await self._apply_autodose(detergent_on, target_soft)

    async def async_set_softener_autodose(self, softener_on: bool) -> None:
        """Set softener autodose state."""
        self._desired_softener = softener_on
        target_det = self._resolve_target_detergent()
        await self._apply_autodose(target_det, softener_on)

    async def _apply_autodose(self, target_det: bool, target_soft: bool) -> None:
        """Apply compound autodose state to hardware with concurrency locking."""
        if self.data is not None and not isinstance(self.data, WashingMachineStatus):
            raise ValueError("Autodose is only supported for washing machines.")

        async with self._autodose_lock:
            actual_det = (
                self._desired_detergent
                if self._desired_detergent is not None
                else target_det
            )
            actual_soft = (
                self._desired_softener
                if self._desired_softener is not None
                else target_soft
            )

            status = self.data if isinstance(self.data, WashingMachineStatus) else None
            prior_det = status.detergent_on if status is not None else None
            prior_soft = status.softener_on if status is not None else None

            if status is not None:
                status.detergent_on = actual_det
                status.softener_on = actual_soft
                self.async_update_listeners()

            try:
                await self.client.set_autodose(actual_det, actual_soft)
                await self.async_request_refresh()
            except Exception:
                if status is not None:
                    status.detergent_on = prior_det
                    status.softener_on = prior_soft
                    self.async_update_listeners()
                self._desired_detergent = (
                    bool(prior_det) if prior_det is not None else None
                )
                self._desired_softener = (
                    bool(prior_soft) if prior_soft is not None else None
                )
                raise
