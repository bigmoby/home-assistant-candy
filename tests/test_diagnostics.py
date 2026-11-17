"""Tests for the diagnostics platform."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy.const import (
    CONF_KEY_MAC_ADDRESS,
    CONF_KEY_SERIAL_NUMBER,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
)
from custom_components.candy.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_happy_path(hass):
    """Both coordinators present — sensitive fields are redacted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="diag-happy",
        data={
            CONF_IP_ADDRESS: "192.168.0.10",
            CONF_PASSWORD: "secret",
            CONF_KEY_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
            CONF_KEY_SERIAL_NUMBER: "SN12345",
        },
    )
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = {"machine_state": "idle"}
    stats_coordinator = MagicMock()
    stats_coordinator.data = {"total_cycles": 42}

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_STATS_COORDINATOR: stats_coordinator,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator_data"] == {"machine_state": "idle"}
    assert result["stats_coordinator_data"] == {"total_cycles": 42}
    config_data = result["config_entry"]
    assert config_data[CONF_IP_ADDRESS] == "**REDACTED**"
    assert config_data[CONF_PASSWORD] == "**REDACTED**"
    assert config_data[CONF_KEY_MAC_ADDRESS] == "**REDACTED**"
    assert config_data[CONF_KEY_SERIAL_NUMBER] == "**REDACTED**"
    assert result["endpoints"] == {"status": "Client not initialized"}
    assert result["dissection"] == {
        "status": "Live telemetry unavailable for dissection"
    }


async def test_diagnostics_no_stats_coordinator(hass):
    """Stats coordinator absent — stats_coordinator_data is None."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="diag-no-stats", data={})
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = {"machine_state": "running"}

    hass.data[DOMAIN] = {entry.entry_id: {DATA_KEY_COORDINATOR: coordinator}}

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator_data"] == {"machine_state": "running"}
    assert result["stats_coordinator_data"] is None


async def test_diagnostics_coordinators_none_data(hass):
    """Coordinators present but data is None — both data fields are None."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="diag-none-data", data={})
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = None
    stats_coordinator = MagicMock()
    stats_coordinator.data = None

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_STATS_COORDINATOR: stats_coordinator,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator_data"] is None
    assert result["stats_coordinator_data"] is None


async def test_diagnostics_with_client_all_endpoints(hass):
    """Test diagnostics with live client returning all supported endpoints."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="diag-full",
        data={
            CONF_IP_ADDRESS: "192.168.1.100",
            CONF_PASSWORD: "secret_password",
            CONF_KEY_MAC_ADDRESS: "11:22:33:44:55:66",
            CONF_KEY_SERIAL_NUMBER: "31009999",
        },
    )
    entry.add_to_hass(hass)

    client = MagicMock()
    client.fetch_all_endpoints = AsyncMock(
        return_value={
            "http-read.json": {
                "statusLavatrice": {
                    "MachMd": "2",
                    "PrPh": "3",
                    "PrNm": "11",
                    "Temp": "40",
                    "SpinSp": "10",
                    "RemTime": "1800",
                    "WiFiStatus": "1",
                    "OptMsk1": "128",
                    "FillR": "80",
                }
            },
            "http-getStatistics.json": {
                "statusCounters": {
                    "Program1": "10",
                    "Temp40": "25",
                }
            },
        }
    )

    coordinator = MagicMock()
    coordinator.data = {"machine_state": "running"}

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_CLIENT: client,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Verify endpoints present and http-config excluded
    endpoints = result["endpoints"]
    assert "http-read.json" in endpoints
    assert "http-config.json" not in endpoints
    assert "http-getStatistics.json" in endpoints

    # Verify sensitive data redacted in config_entry
    config_entry_diag = result["config_entry"]
    assert config_entry_diag[CONF_PASSWORD] == "**REDACTED**"
    assert config_entry_diag[CONF_IP_ADDRESS] == "**REDACTED**"
    assert config_entry_diag[CONF_KEY_MAC_ADDRESS] == "**REDACTED**"
    assert config_entry_diag[CONF_KEY_SERIAL_NUMBER] == "**REDACTED**"

    # Verify deep telemetry dissection
    dissection = result["dissection"]
    assert dissection["appliance_family"] == "Washing Machine / Washer-Dryer"
    assert dissection["root_key"] == "statusLavatrice"
    assert dissection["remote_control"]["remote_control_enabled"] is True

    # Check decoded registers
    regs = {r["register"]: r for r in dissection["decoded_registers"]}
    assert regs["MachMd"]["meaning"] == "Running"
    assert regs["PrPh"]["meaning"] == "Rinse"
    assert "40 °C wash temperature" in regs["Temp"]["meaning"]
    assert "1000 RPM spin speed" in regs["SpinSp"]["meaning"]
    assert "Wash options bitmask 128" in regs["OptMsk1"]["meaning"]


async def test_diagnostics_with_tumble_dryer_dissection(hass):
    """Test diagnostics with tumble dryer telemetry payload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="diag-td",
        data={CONF_IP_ADDRESS: "192.168.1.101"},
    )
    entry.add_to_hass(hass)

    client = MagicMock()
    client.fetch_all_endpoints = AsyncMock(
        return_value={
            "http-read.json": {
                "statusTD": {
                    "StatoTD": "2",
                    "PrPh": "2",
                    "Pr": "5",
                    "DryLev": "3",
                    "RemTime": "45",
                    "StatoWiFi": "1",
                    "WaterTankFull": "0",
                }
            },
            "http-getStatistics.json": {
                "status": "Statistics counters not supported for this appliance family"
            },
        }
    )

    coordinator = MagicMock()
    coordinator.data = {"machine_state": "running"}

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_CLIENT: client,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    dissection = result["dissection"]
    assert dissection["appliance_family"] == "Tumble Dryer"
    assert dissection["root_key"] == "statusTD"
    assert dissection["remote_control"]["remote_control_enabled"] is True

    regs = {r["register"]: r for r in dissection["decoded_registers"]}
    assert regs["StatoTD"]["meaning"] == "Running"
    assert regs["PrPh"]["meaning"] == "Running (Active Drying)"
    assert regs["DryLev"]["meaning"] == "Store / Cupboard Dry"
    assert regs["WaterTankFull"]["meaning"] == "Water tank OK"


async def test_diagnostics_client_exception_handling(hass):
    """Test diagnostics handles client endpoint fetch failure gracefully."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="diag-err",
        data={CONF_IP_ADDRESS: "192.168.1.102"},
    )
    entry.add_to_hass(hass)

    client = MagicMock()
    client.fetch_all_endpoints = AsyncMock(
        side_effect=RuntimeError("Connection timeout")
    )

    coordinator = MagicMock()
    coordinator.data = {"machine_state": "offline"}

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_CLIENT: client,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "error" in result["endpoints"]
    assert "Connection timeout" in result["endpoints"]["error"]
    assert result["dissection"]["status"] == "Live telemetry unavailable for dissection"


async def test_diagnostics_device_and_entities(hass):
    """Test diagnostics collects device registry and entity registry info."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="diag-registry",
        data={
            CONF_IP_ADDRESS: "192.168.1.103",
            CONF_KEY_MAC_ADDRESS: "AA:BB:CC:DD:EE:FF",
        },
    )
    entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        connections={(dr.CONNECTION_NETWORK_MAC, "AA:BB:CC:DD:EE:FF")},
        manufacturer="Candy",
        model="RapidO Pro",
        sw_version="v2.1",
    )

    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get_or_create(
        domain="sensor",
        platform=DOMAIN,
        unique_id=f"{entry.entry_id}-status",
        config_entry=entry,
        device_id=device.id,
    )

    hass.states.async_set(
        entity_entry.entity_id,
        "idle",
        {"temperature": 40, "mac_address": "AA:BB:CC:DD:EE:FF"},
    )

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: None,
            DATA_KEY_CLIENT: None,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Check device info
    devices = result["device_info"]
    assert len(devices) == 1
    assert devices[0]["manufacturer"] == "Candy"
    assert devices[0]["model"] == "RapidO Pro"
    assert devices[0]["connections"][0][1] == "**REDACTED**"

    # Check entity info
    entities = result["entities"]
    assert len(entities) == 1
    assert entities[0]["entity_id"] == entity_entry.entity_id
    assert entities[0]["state"] == "idle"
    assert entities[0]["attributes"]["temperature"] == 40
    assert entities[0]["attributes"]["mac_address"] == "**REDACTED**"


async def test_diagnostics_dataclass_serialization(hass):
    """Test diagnostics serializes dataclass coordinator data properly."""

    @dataclass
    class MockStatus:
        machine_state: str
        program_id: int

    entry = MockConfigEntry(domain=DOMAIN, unique_id="diag-dataclass", data={})
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = MockStatus(machine_state="idle", program_id=3)

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["coordinator_data"] == {
        "machine_state": "idle",
        "program_id": 3,
    }


async def test_diagnostics_arbitrary_object_serialization(hass):
    """Test diagnostics serializes arbitrary objects via str()."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="diag-str-obj", data={})
    entry.add_to_hass(hass)

    class CustomObject:
        def __str__(self):
            return "custom_str_representation"

    coordinator = MagicMock()
    coordinator.data = CustomObject()

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["coordinator_data"] == "custom_str_representation"
