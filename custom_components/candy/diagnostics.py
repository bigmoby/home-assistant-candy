"""Diagnostics platform for candy."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .client import CandyClient
from .const import (
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
)
from .dissector import dissect_telemetry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_IP_ADDRESS,
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_SERIAL_NUMBER,
    # Network and credential fields in raw endpoints
    "password",
    "PASSWORD",
    "passphrase",
    "pwd",
    "key",
    "encryption_key",
    "ENCRYPT_KEY",
    "ssid",
    "SSID",
    "bssid",
    "BSSID",
    "mac",
    "MAC",
    "macaddr",
    "mac_address",
    "ip",
    "IP",
    "ipaddr",
    "ip_address",
    "gateway",
    "netmask",
    "dns",
    "serial",
    "SERIAL",
    "serial_number",
    "sn",
    "SN",
}


def _serialize_data(data: Any) -> Any:
    """Safely serialize coordinator data or dataclasses to primitive types."""
    if data is None:
        return None
    if is_dataclass(data) and not isinstance(data, type):
        return asdict(data)
    if isinstance(data, dict):
        return data
    return str(data)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for the config entry."""
    data = hass.data[DOMAIN][entry.entry_id]

    coordinator = data.get(DATA_KEY_COORDINATOR)
    stats_coordinator = data.get(DATA_KEY_STATS_COORDINATOR)
    client: CandyClient | None = data.get(DATA_KEY_CLIENT)

    # 1. Fetch live machine endpoints if client is available
    endpoints: dict[str, Any]
    if client is not None:
        try:
            endpoints = await client.fetch_all_endpoints()
        except Exception as err:
            endpoints = {"error": f"Failed to fetch endpoints: {err!r}"}
    else:
        endpoints = {"status": "Client not initialized"}

    # 2. Perform deep telemetry dissection if read payload is present
    read_payload = endpoints.get("http-read.json")
    if (
        isinstance(read_payload, dict)
        and "error" not in read_payload
        and "status" not in read_payload
    ):
        dissection = dissect_telemetry(read_payload)
    else:
        dissection = {"status": "Live telemetry unavailable for dissection"}

    # 3. Collect device registry entries
    device_registry = dr.async_get(hass)
    device_entries = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    devices = [
        {
            "id": dev.id,
            "name": dev.name,
            "model": dev.model,
            "manufacturer": dev.manufacturer,
            "sw_version": dev.sw_version,
            "hw_version": dev.hw_version,
            "identifiers": [list(ident) for ident in dev.identifiers],
            "connections": [
                [
                    c[0],
                    "**REDACTED**"
                    if c[0] in ("mac", dr.CONNECTION_NETWORK_MAC)
                    else c[1],
                ]
                for c in dev.connections
            ],
        }
        for dev in device_entries
    ]

    # 4. Collect entity registry entries and live states
    entity_registry = er.async_get(hass)
    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    entities = []
    for ent in entity_entries:
        state = hass.states.get(ent.entity_id)
        entities.append(
            {
                "entity_id": ent.entity_id,
                "unique_id": ent.unique_id,
                "platform": ent.platform,
                "disabled": ent.disabled,
                "state": state.state if state else None,
                "attributes": dict(state.attributes) if state else {},
            }
        )

    diag_data = {
        "config_entry": entry.data,
        "config_entry_options": entry.options,
        "coordinator_data": _serialize_data(coordinator.data) if coordinator else None,
        "stats_coordinator_data": (
            _serialize_data(stats_coordinator.data) if stats_coordinator else None
        ),
        "device_info": devices,
        "entities": entities,
        "endpoints": endpoints,
        "dissection": dissection,
    }

    return async_redact_data(diag_data, TO_REDACT)
