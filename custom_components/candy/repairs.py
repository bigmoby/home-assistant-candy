"""Repair flows for Candy integration."""

from __future__ import annotations

import logging
from typing import Any

import async_timeout
from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.const import CONF_IP_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .client.cloud import SimplyFiCloudError, fetch_appliance_data
from .config_flow import CLOUD_SCHEMA, _language_schema, apply_cloud_appliance_data
from .const import CONF_KEY_PROGRAM_LANGUAGE, DOMAIN, LEGACY_DISHWASHER_CONTROL_ENTITIES

_LOGGER = logging.getLogger(__name__)


class DishwasherFullControlRepairFlow(RepairsFlow):
    """Handler for migrating a <= 1.7.0 dishwasher to Full Control or Read-Only."""

    def __init__(self, entry_id: str) -> None:
        """Initialise the repair flow for the given config entry."""
        super().__init__()
        self._entry_id = entry_id
        self._pending_data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Let the user choose between Full Control login or keeping Read-Only."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        return self.async_show_menu(
            step_id="init",
            menu_options=["switch_to_full_control", "keep_read_only"],
            description_placeholders={"entry_title": entry.title},
        )

    async def async_step_switch_to_full_control(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Collect Simply-Fi credentials and fetch cloud data for Full Control."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is None:
            return self.async_show_form(
                step_id="switch_to_full_control", data_schema=CLOUD_SCHEMA
            )

        errors: dict[str, str] = {}
        try:
            async with async_timeout.timeout(30):
                appliance = await fetch_appliance_data(
                    session=async_get_clientsession(self.hass),
                    email=user_input["email"],
                    password=user_input["password"],
                    device_ip=entry.data[CONF_IP_ADDRESS],
                )
        except SimplyFiCloudError as err:
            _LOGGER.warning("Simply-Fi cloud fetch failed in repair flow: %s", err)
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="switch_to_full_control",
                data_schema=CLOUD_SCHEMA,
                errors=errors,
            )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error in repair flow cloud fetch")
            errors["base"] = "cloud_auth"
            return self.async_show_form(
                step_id="switch_to_full_control",
                data_schema=CLOUD_SCHEMA,
                errors=errors,
            )

        self._pending_data = apply_cloud_appliance_data(
            dict(entry.data),
            appliance,
            is_washing_machine=False,
            is_tumble_dryer=False,
            is_dishwasher=True,
        )
        return await self.async_step_language()

    async def async_step_language(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Choose appliance language, save updated entry data, and reload."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is None:
            current_lang = self._pending_data.get(
                CONF_KEY_PROGRAM_LANGUAGE,
                entry.data.get(CONF_KEY_PROGRAM_LANGUAGE, "en"),
            )
            return self.async_show_form(
                step_id="language",
                data_schema=_language_schema(current_lang),
            )

        self._pending_data[CONF_KEY_PROGRAM_LANGUAGE] = user_input[
            CONF_KEY_PROGRAM_LANGUAGE
        ]
        self.hass.config_entries.async_update_entry(entry, data=self._pending_data)
        self.hass.async_create_task(
            self.hass.config_entries.async_reload(entry.entry_id)
        )
        return self.async_create_entry(data={})

    async def async_step_keep_read_only(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Remove orphaned <= 1.7.0 control entities and keep Read-Only mode."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        if user_input is None:
            return self.async_show_form(
                step_id="keep_read_only",
                data_schema=vol.Schema({}),
            )

        entity_reg = er.async_get(self.hass)
        for platform, uid_template in LEGACY_DISHWASHER_CONTROL_ENTITIES:
            entity_id = entity_reg.async_get_entity_id(
                platform, DOMAIN, uid_template.format(entry.entry_id)
            )
            if entity_id is not None:
                entity_reg.async_remove(entity_id)

        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repair flow for Candy issues."""
    entry_id = data.get("entry_id") if isinstance(data, dict) else None
    if isinstance(entry_id, str) and hass.config_entries.async_get_entry(entry_id):
        return DishwasherFullControlRepairFlow(entry_id)
    return ConfirmRepairFlow()
