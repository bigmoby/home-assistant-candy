"""Config flow for Candy integration."""

from __future__ import annotations

import logging
from typing import Any

import async_timeout
from homeassistant import config_entries
from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import voluptuous as vol

from .client import detect_encryption, discover_devices
from .client.decryption import Encryption
from .const import CONF_INTEGRATION_TITLE, CONF_KEY_USE_ENCRYPTION, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
    }
)

MANUAL_IP_OPTION = "manual"


def _get_local_subnet(hass_ip: str) -> str:
    """Return the /24 subnet string for the given IP (e.g. '192.168.1.1' → '192.168.1.0')."""
    parts = hass_ip.split(".")[:3]
    return ".".join(parts) + ".0"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Candy."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialise config flow."""
        self._discovered: dict[str, str] = {}  # ip -> device type label

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — try auto-discovery first."""
        # On first call (no user_input) attempt LAN discovery
        if user_input is None:
            try:
                session = async_get_clientsession(self.hass)
                source_ip = await async_get_source_ip(self.hass)
                if source_ip:
                    subnet = _get_local_subnet(source_ip)
                    async with async_timeout.timeout(15):
                        self._discovered = await discover_devices(session, subnet)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug("LAN discovery failed, falling back to manual entry")
                self._discovered = {}

            if self._discovered:
                return await self.async_step_select()

        # No devices found or user came back from select with "manual" — show manual form
        return await self._handle_manual_ip(user_input)

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a discovered device or choose manual entry."""
        if user_input is not None:
            selected = user_input[CONF_IP_ADDRESS]
            if selected == MANUAL_IP_OPTION:
                return self.async_show_form(
                    step_id="user", data_schema=STEP_DATA_SCHEMA
                )
            return await self._configure_device(selected)

        # Build the selector list: "IP — Device Type" + manual option
        options = {ip: f"{ip} — {label}" for ip, label in self._discovered.items()}
        options[MANUAL_IP_OPTION] = "Enter IP address manually"

        select_schema = vol.Schema({vol.Required(CONF_IP_ADDRESS): vol.In(options)})
        return self.async_show_form(step_id="select", data_schema=select_schema)

    async def _handle_manual_ip(
        self, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Process a manually entered IP address."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_DATA_SCHEMA)

        errors: dict[str, str] = {}
        try:
            result = await self._configure_device(user_input[CONF_IP_ADDRESS])
        except Exception:  # pylint: disable=broad-except
            errors["base"] = "detect_encryption"
        else:
            return result

        return self.async_show_form(
            step_id="user", data_schema=STEP_DATA_SCHEMA, errors=errors
        )

    async def _configure_device(self, ip: str) -> ConfigFlowResult:
        """Detect encryption and create the config entry."""
        config_data: dict[str, Any] = {CONF_IP_ADDRESS: ip}
        errors: dict[str, str] = {}

        try:
            async with async_timeout.timeout(40):
                encryption_type, key = await detect_encryption(
                    session=async_get_clientsession(self.hass),
                    device_ip=ip,
                )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Failed to detect encryption")
            errors["base"] = "detect_encryption"
            return self.async_show_form(
                step_id="user", data_schema=STEP_DATA_SCHEMA, errors=errors
            )

        if encryption_type == Encryption.ENCRYPTION:
            config_data[CONF_KEY_USE_ENCRYPTION] = True
            config_data[CONF_PASSWORD] = key
        elif encryption_type == Encryption.NO_ENCRYPTION:
            config_data[CONF_KEY_USE_ENCRYPTION] = False
        elif encryption_type == Encryption.ENCRYPTION_WITHOUT_KEY:
            config_data[CONF_KEY_USE_ENCRYPTION] = True
            config_data[CONF_PASSWORD] = ""

        return self.async_create_entry(title=CONF_INTEGRATION_TITLE, data=config_data)
