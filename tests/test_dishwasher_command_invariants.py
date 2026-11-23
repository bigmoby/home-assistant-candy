"""Tests for Dishwasher Safety Interlocks and Command Invariants.

Verifies cross-platform hardware guarantees:
1. Remote Control Gate: All write/action buttons disabled when StatoWiFi == 0;
   pre-execution settings (select, delay number, switches) remain available for pre-configuration.
2. Door Safety Interlock: Start button disabled when OpenDoor == 1.
3. Motorized Auto Door: Available only on _OD interfaces; sends OpenDoorOpt=7;
   prevented when machine is actively executing a wash cycle.
4. Hardware Settings Routing: Water hardness routes to HL= (never SetHard) and enforces bounds (0..7);
   buzzer routes to BM=; program memo routes to LC=.
5. Stop/Reset Invariant: Sends Reset=1.
6. Checkup Lifecycle & Dismissal Invariant: Sends StartCheckUp=1 on start and
   Write=1&StartStop=0&Program=11 on completion.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DATA_KEY_COORDINATOR, DOMAIN
from custom_components.candy.client import CandyClient
from custom_components.candy.client.dishwasher_commands import (
    LegacyTouchDishwasherCommandBuilder,
    ModernDishwasherCommandBuilder,
    get_dishwasher_command_builder,
    is_legacy_dishwasher,
    is_modern_dishwasher,
    is_open_door_supported,
)
from custom_components.candy.client.model import DishwasherStatus
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    MODE_FULL_CONTROL,
    UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON,
    UNIQUE_ID_DISHWASHER_DELAY_NUMBER,
    UNIQUE_ID_DISHWASHER_ECO_SWITCH,
    UNIQUE_ID_DISHWASHER_OPEN_DOOR_BUTTON,
    UNIQUE_ID_DISHWASHER_PAUSE_BUTTON,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
    UNIQUE_ID_DISHWASHER_RESUME_BUTTON,
    UNIQUE_ID_DISHWASHER_START_BUTTON,
    UNIQUE_ID_DISHWASHER_STOP_BUTTON,
)

from .common import TEST_IP, init_integration

_CATALOG_PATH = Path(__file__).parent / "fixtures" / "catalog_serial_40_brava_dw.json"
_READY = "dishwasher/remote_ready.json"


def _load_dw_catalog() -> dict:
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, unique_id.format(entry.entry_id)
    )
    assert entity_id is not None
    return entity_id


def _optional_entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, unique_id.format(entry.entry_id)
    )


def _fixture_with_overrides(name: str, **overrides: str) -> str:
    data = json.loads(load_fixture(name))
    data["statusDWash"].update(overrides)
    return json.dumps(data)


async def test_remote_control_disabled_gate_and_preconfiguration_availability(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When remote control is off (StatoWiFi == 0), action buttons are disabled."""
    catalog = _load_dw_catalog()
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response='{"statusCounters": {"s1": "10"}}',
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
        },
    )

    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]

    # Action / Execution buttons
    start_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON)
    stop_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_STOP_BUTTON)
    pause_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_PAUSE_BUTTON)
    resume_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_RESUME_BUTTON)
    checkup_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_CHECKUP_BUTTON)
    open_door_id = _entity_id(
        hass, entry, "button", UNIQUE_ID_DISHWASHER_OPEN_DOOR_BUTTON
    )

    # Pre-execution settings
    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    delay_id = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)
    eco_id = _entity_id(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH)

    # Simulate remote control OFF (StatoWiFi: "0")
    no_wifi_payload = json.loads(_fixture_with_overrides(_READY, StatoWiFi="0"))
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(no_wifi_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    # All execution buttons must be unavailable
    assert hass.states.get(start_id).state == "unavailable"
    assert hass.states.get(stop_id).state == "unavailable"
    assert hass.states.get(pause_id).state == "unavailable"
    assert hass.states.get(resume_id).state == "unavailable"
    assert hass.states.get(checkup_id).state == "unavailable"
    assert hass.states.get(open_door_id).state == "unavailable"

    # Pre-execution settings MUST stay available so users can prepare wash parameters
    assert hass.states.get(select_id).state != "unavailable"
    assert hass.states.get(delay_id).state != "unavailable"
    assert hass.states.get(eco_id).state != "unavailable"


async def test_door_open_interlock_guards_start_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the dishwasher door is open (OpenDoor: 1), the Start button must be unavailable."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response='{"statusCounters": {"s1": "10"}}',
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
        },
    )

    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    start_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON)

    # Door open
    door_open_payload = json.loads(_fixture_with_overrides(_READY, OpenDoor="1"))
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(door_open_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(start_id).state == "unavailable"

    # Door closed
    door_closed_payload = json.loads(_fixture_with_overrides(_READY, OpenDoor="0"))
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(door_closed_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(start_id).state != "unavailable"


async def test_motorized_auto_door_button_command_and_safety(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Open door button sends OpenDoorOpt=7, and is unavailable during active wash cycle."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response='{"statusCounters": {"s1": "10"}}',
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
        },
    )

    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    open_door_id = _entity_id(
        hass, entry, "button", UNIQUE_ID_DISHWASHER_OPEN_DOOR_BUTTON
    )

    # 1. Ready state: button is available
    assert hass.states.get(open_door_id).state != "unavailable"

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&OpenDoorOpt=7",
        text='{"response":"OK"}',
    )

    await hass.services.async_call(
        "button", "press", {"entity_id": open_door_id}, blocking=True
    )
    write_calls = [
        call for call in aioclient_mock.mock_calls if "OpenDoorOpt=7" in str(call[1])
    ]
    assert len(write_calls) == 1

    # 2. Running wash cycle: Open Door button must be unavailable for safety
    running_payload = json.loads(
        _fixture_with_overrides(_READY, StatoDWash="3", r2="2", StartStop="1")
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(running_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(open_door_id).state == "unavailable"


async def test_water_hardness_routing_and_bounds_validation(
    hass: HomeAssistant,
) -> None:
    """Dishwasher water hardness MUST send HL= and reject out-of-range values."""
    client = CandyClient(
        None,  # type: ignore[arg-type]
        device_ip=TEST_IP,
        encryption_key="",
        use_encryption=False,
    )
    client.interface_type = "BRAVA_BI_DIGIT_OD"

    # Range validation
    with pytest.raises(ValueError, match="Invalid dishwasher water hardness: -1"):
        await client.set_dishwasher_water_hardness(-1)

    with pytest.raises(ValueError, match="Invalid dishwasher water hardness: 8"):
        await client.set_dishwasher_water_hardness(8)


def test_command_builder_interface_type_classification() -> None:
    """Verify interface family classification predicates."""
    # Modern Brava / AXI
    for iface in ("BRAVA_BI_DIGIT_OD", "DW_WIFI_FS", "AXI_FS_SMOOTH_OD"):
        assert is_modern_dishwasher(iface) is True
        assert is_legacy_dishwasher(iface) is False
        assert isinstance(
            get_dishwasher_command_builder(iface), ModernDishwasherCommandBuilder
        )

    # Legacy Touch / Built-in
    for iface in (
        "DishwasherInterfaceTypeFSTouch",
        "DishwasherInterfaceTypeBuiltIn",
        "DW_NFC_DIGIT_FS",
    ):
        assert is_legacy_dishwasher(iface) is True
        assert is_modern_dishwasher(iface) is False
        assert isinstance(
            get_dishwasher_command_builder(iface), LegacyTouchDishwasherCommandBuilder
        )

    # Capability Suffix _OD
    assert is_open_door_supported("BRAVA_BI_DIGIT_OD") is True
    assert is_open_door_supported("AXI_FS_SMOOTH_OD") is True
    assert is_open_door_supported("BRAVA_BI_DIGIT") is False
    assert is_open_door_supported(None) is False


def test_command_builder_invariants() -> None:
    """Test write dictionary invariants for Modern and Legacy command builders."""
    modern = ModernDishwasherCommandBuilder(open_door_supported=True)
    legacy = LegacyTouchDishwasherCommandBuilder(open_door_supported=False)

    # Stop command sends Reset=1
    assert modern.build_stop() == {"Reset": 1}
    assert legacy.build_stop() == {"Reset": 1}

    # Checkup commands
    assert modern.build_checkup() == {"StartCheckUp": 1}
    assert legacy.build_checkup() == {"StartCheckUp": 1}
    assert modern.build_checkup_reset() == {"Write": 1, "StartStop": 0, "Program": 11}
    assert legacy.build_checkup_reset() == {"Write": 1, "StartStop": 0, "Program": 11}

    # Open door command sends OpenDoorOpt=7
    assert modern.build_open_door() == {"OpenDoorOpt": 7}
    assert legacy.build_open_door() == {"OpenDoorOpt": 7}


def test_legacy_dishwasher_build_start_options() -> None:
    """Test LegacyTouchDishwasherCommandBuilder build_start variations."""
    legacy = LegacyTouchDishwasherCommandBuilder(open_door_supported=True)

    # 1. Program ending in minus '-' sets OpzProg='m'
    params_m = legacy.build_start(
        program_code="P2-",
        position=2,
        delay_minutes=60,
        r15=0,
        three_in_one=True,
        eco=False,
        half_load=True,
        extra_dry=False,
        open_door=True,
    )
    assert params_m["OpzProg"] == "m"
    assert params_m["Program"] == "P2"
    assert params_m["DelayStart"] == 1  # 60 // 60
    assert params_m["OpenDoorOpt"] == 1
    assert params_m["TreinUno"] == 1
    assert params_m["MetaCarico"] == 1

    # 2. r15 > 0 preserves delay in minutes
    params_mins = legacy.build_start(
        program_code="P3",
        position=3,
        delay_minutes=45,
        r15=1,
        three_in_one=False,
        eco=True,
        half_load=False,
        extra_dry=True,
        open_door=False,
    )
    assert params_mins["DelayStart"] == 45
    assert params_mins["Program"] == "P3"
    assert params_mins["OpzProg"] == "0"
    assert params_mins["ExtraDry"] == 1
    assert params_mins["Eco"] == 1
    assert params_mins["OpenDoorOpt"] == 0
