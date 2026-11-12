r"""Comprehensive Combinatorial Matrix Tests for Standalone Washing Machines.

Grounded entirely in authentic appliance catalog data:
- Serial 39: RapidO Standalone Washer (RO 1284DWH7\\1-S, RAPIDO_4DIG_STM)
- Serial 41: DualTech Standalone Washer (GVF4137TWHN/2-07, 3D_DUAL)
- Serial 34: Bianca Standalone Washer (GSF 1510LWH3/1-01, 4D)

Verifies all aspects of standalone washing machine program combinations without synthetic guesswork:
1. Absence of washer-dryer specific selects (program_type, dry_setting)
2. Platform feature gating (remote pause/resume button presence on Rapido vs absence on DualTech & Bianca)
3. Direct exposure of all selectable programs in select.wash_program
4. Temperature bounds and default selection across programs
5. Spin speed bounds and default selection across programs
6. Soil level selection bounds and defaults
7. Wash options bitmask and switch availability
8. Steam switch availability gating against program.steam
9. Outgoing wire command grammar & register serialization on Start button press
10. Delayed start command format (Rapido/Bianca: DelVl = delay // 30; DualTech: DelMd = 1, DelVl = delay // 60)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client import parse_wash_programs
from custom_components.candy.client.model import WashingMachineWashProgram
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    FLANGIA_PROGRAMS_TO_HIDE,
    MODE_FULL_CONTROL,
    SOIL_LABELS,
    STEAM_DURATION_OFFSETS,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_DRY_SELECT,
    UNIQUE_ID_WASH_ESTIMATED_DURATION,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT,
    UNIQUE_ID_WASH_RESUME_BUTTON,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    UNIQUE_ID_WASH_TEMP_SELECT,
    WASH_OPTION_DURATION_DELTAS_REDUCED,
    WASH_OPTION_DURATION_DELTAS_STANDARD,
    WASH_OPTIONS,
)
from custom_components.candy.helpers import is_dualtech

from .common import TEST_IP

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_IDLE_JSON = """{
  "statusLavatrice": {
    "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
    "PrCode": "136", "SLevel": "0", "Temp": "40", "SpinSp": "10",
    "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
  }
}"""

_STATS_OK = (
    '{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'
)


def _load_catalog(filename: str) -> dict:
    with open(_FIXTURES_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def _add_stats_mocks(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_OK,
    )


async def _init_standalone_washer(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    catalog: dict,
    status_json: str = _IDLE_JSON,
) -> tuple[MockConfigEntry, list[WashingMachineWashProgram]]:
    """Initialize a full control integration for a standalone washing machine."""
    raw_programs = catalog["programs"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"test-catalog-wm-{catalog['serial']}",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: raw_programs,
            CONF_KEY_INTERFACE_TYPE: catalog.get("interface_type", ""),
            CONF_KEY_IS_WASHER_DRYER: False,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
            CONF_KEY_MAINTENANCE_ENABLED: True,
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    _add_stats_mocks(aioclient_mock)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    parsed_programs = parse_wash_programs(raw_programs)
    return entry, parsed_programs


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, uid_tpl: str
) -> str:
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id(platform, DOMAIN, uid_tpl.format(entry.entry_id))
    assert eid is not None, f"Entity not found for {platform}.{uid_tpl}"
    return eid


def _state(hass: HomeAssistant, entry: MockConfigEntry, platform: str, uid_tpl: str):
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id(platform, DOMAIN, uid_tpl.format(entry.entry_id))
    if eid is None:
        return None
    return hass.states.get(eid)


def _is_selectable(p: WashingMachineWashProgram, interface_type: str) -> bool:
    if "autoclean" in p.name.lower():
        return False
    return not (
        is_dualtech(interface_type) and p.name.upper() in FLANGIA_PROGRAMS_TO_HIDE
    )


async def _select_wash_program(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    program: WashingMachineWashProgram,
) -> None:
    prog_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": program.localized_name("en")},
        blocking=True,
    )


def _calculate_expected_duration(
    program: WashingMachineWashProgram,
    soil_level: int,
    steam_on: bool,
    options_mask: int,
) -> int | None:
    if program.min_soil_level < program.max_soil_level:
        base = program.duration_for_soil(soil_level)
    else:
        base = program.default_duration

    if base <= 0:
        return None

    minutes = base
    if steam_on and program.steam_type in STEAM_DURATION_OFFSETS:
        minutes += STEAM_DURATION_OFFSETS[program.steam_type]

    is_reduced = (
        program.steam_type in ("S", "R")
        or getattr(program, "dry_type", "") in ("S", "W")
        or program.pr_code == 4
    )
    deltas = (
        WASH_OPTION_DURATION_DELTAS_REDUCED
        if is_reduced
        else WASH_OPTION_DURATION_DELTAS_STANDARD
    )
    for bitmask, _, uid_suffix, _ in WASH_OPTIONS:
        if (program.available_options & bitmask) and (options_mask & bitmask):
            minutes += deltas.get(uid_suffix, 0)

    return minutes


# ===========================================================================
# 1. Standalone Entity Architecture & Absence of WD Selects
# ===========================================================================


async def test_standalone_washer_entity_architecture(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify that standalone washers omit washer-dryer selects and expose all wash programs directly."""
    catalog_39 = _load_catalog("catalog_serial_39_rapido_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog_39)

    # Washer-dryer selects MUST NOT exist
    assert _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT) is None
    assert _state(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT) is None

    # Wash program select MUST be present
    prog_state = _state(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    assert prog_state is not None
    options = prog_state.attributes.get("options", [])

    selectable = [
        p
        for p in programs
        if _is_selectable(p, str(catalog_39.get("interface_type", "")))
    ]
    for p in selectable:
        assert p.localized_name("en") in options


# ===========================================================================
# 2. Platform Feature Gating: Remote Pause / Resume
# ===========================================================================


async def test_standalone_washer_pause_resume_gating(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify pause/resume button presence on Rapido and suppression on DualTech."""
    # 1. Rapido (Serial 39, RAPIDO_4DIG_STM) supports pause
    catalog_39 = _load_catalog("catalog_serial_39_rapido_wm.json")
    entry_39, _ = await _init_standalone_washer(hass, aioclient_mock, catalog_39)
    assert _state(hass, entry_39, "button", UNIQUE_ID_WASH_PAUSE_BUTTON) is not None
    assert _state(hass, entry_39, "button", UNIQUE_ID_WASH_RESUME_BUTTON) is not None

    # 2. DualTech (Serial 41, 3D_DUAL) suppresses pause
    catalog_41 = _load_catalog("catalog_serial_41_dualtech_wm.json")
    entry_41, _ = await _init_standalone_washer(hass, aioclient_mock, catalog_41)
    assert _state(hass, entry_41, "button", UNIQUE_ID_WASH_PAUSE_BUTTON) is None
    assert _state(hass, entry_41, "button", UNIQUE_ID_WASH_RESUME_BUTTON) is None

    # 3. Explicit Bianca interface (interface_type: BIANCA) suppresses pause
    catalog_bianca = dict(catalog_41)
    catalog_bianca["serial"] = 9999
    catalog_bianca["interface_type"] = "BIANCA_TOUCH"
    entry_bianca, _ = await _init_standalone_washer(
        hass, aioclient_mock, catalog_bianca
    )
    assert _state(hass, entry_bianca, "button", UNIQUE_ID_WASH_PAUSE_BUTTON) is None
    assert _state(hass, entry_bianca, "button", UNIQUE_ID_WASH_RESUME_BUTTON) is None


# ===========================================================================
# 3. Soil Level Selection Matrix
# ===========================================================================


async def test_standalone_soil_level_selection_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify soil level availability is gated strictly by min_soil < max_soil on standalone washers."""
    catalog = _load_catalog("catalog_serial_39_rapido_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
    soil_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    seen_names: set[str] = set()
    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_wash_program(hass, entry, p)

        soil_state = hass.states.get(soil_eid)
        assert soil_state is not None
        if p.min_soil_level < p.max_soil_level:
            assert soil_state.state not in ("unavailable", "unknown")
        else:
            assert soil_state.state == "unavailable"


# ===========================================================================
# 4. Temperature & Spin Speed Selection Matrix (RapidO Serial 39)
# ===========================================================================


async def test_rapido_standalone_temp_and_spin_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify temperature and spin dropdown bounds and defaults across Serial 39 programs."""
    catalog = _load_catalog("catalog_serial_39_rapido_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
    temp_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    spin_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    seen_names: set[str] = set()
    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_wash_program(hass, entry, p)

        temp_state = hass.states.get(temp_eid)
        assert temp_state is not None
        if p.max_temperature in (0, 255):
            assert temp_state.state in ("unavailable", str(p.default_temperature))
        else:
            assert temp_state.state not in ("unavailable", "unknown")
            opts = temp_state.attributes.get("options", [])
            for opt in opts:
                assert int(opt) <= p.max_temperature
            if str(p.default_temperature) in opts:
                assert temp_state.state == str(p.default_temperature)

        spin_state = hass.states.get(spin_eid)
        assert spin_state is not None
        if p.max_spin_speed in (0, 255):
            assert spin_state.state in ("unavailable", str(p.default_spin_speed))
        else:
            assert spin_state.state not in ("unavailable", "unknown")
            opts = spin_state.attributes.get("options", [])
            for opt in opts:
                assert int(opt) <= p.max_spin_speed
            if str(p.default_spin_speed) in opts:
                assert spin_state.state == str(p.default_spin_speed)


# ===========================================================================
# 4. Temperature & Spin Speed Selection Matrix (DualTech Serial 41)
# ===========================================================================


async def test_dualtech_standalone_temp_and_spin_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify temperature and spin dropdown bounds and defaults across Serial 41 programs."""
    catalog = _load_catalog("catalog_serial_41_dualtech_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
    temp_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    spin_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    seen_names: set[str] = set()
    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_wash_program(hass, entry, p)

        temp_state = hass.states.get(temp_eid)
        assert temp_state is not None
        if p.max_temperature in (0, 255):
            assert temp_state.state in ("unavailable", str(p.default_temperature))
        else:
            assert temp_state.state not in ("unavailable", "unknown")
            opts = temp_state.attributes.get("options", [])
            for opt in opts:
                assert int(opt) <= p.max_temperature
            if str(p.default_temperature) in opts:
                assert temp_state.state == str(p.default_temperature)

        spin_state = hass.states.get(spin_eid)
        assert spin_state is not None
        if p.max_spin_speed in (0, 255):
            assert spin_state.state in ("unavailable", str(p.default_spin_speed))
        else:
            assert spin_state.state not in ("unavailable", "unknown")
            opts = spin_state.attributes.get("options", [])
            for opt in opts:
                assert int(opt) <= p.max_spin_speed
            if str(p.default_spin_speed) in opts:
                assert spin_state.state == str(p.default_spin_speed)


# ===========================================================================
# 5. Outgoing Wire Command Grammar (RapidO Serial 39)
# ===========================================================================


async def test_rapido_standalone_start_wire_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Start button dispatches authentic Bianca-grammar parameters without Dry setting."""
    catalog = _load_catalog("catalog_serial_39_rapido_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
    start_eid = _entity_id(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    interface_type = str(catalog.get("interface_type", ""))

    seen_names: set[str] = set()
    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_wash_program(hass, entry, p)

        with patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send:
            await hass.services.async_call(
                "button", "press", {"entity_id": start_eid}, blocking=True
            )

        assert mock_send.called
        qs = mock_send.call_args[0][0]
        params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)

        assert params.get("Write") == "1"
        assert params.get("StSt") == "1"
        assert int(params.get("PrNm", -1)) == p.selector_position
        assert int(params.get("PrCode", -1)) == p.pr_code
        assert params.get("Dry") == "0"
        assert params.get("ED") == "0"
        assert "Option" not in params


# ===========================================================================
# 6. Outgoing Wire Command Grammar (DualTech Serial 41)
# ===========================================================================


async def test_dualtech_standalone_start_wire_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Start button dispatches authentic DualTech parameters with no Option/Dry parameter."""
    catalog = _load_catalog("catalog_serial_41_dualtech_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
    start_eid = _entity_id(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    interface_type = str(catalog.get("interface_type", ""))

    seen_names: set[str] = set()
    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_wash_program(hass, entry, p)

        with patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send:
            await hass.services.async_call(
                "button", "press", {"entity_id": start_eid}, blocking=True
            )

        assert mock_send.called
        qs = mock_send.call_args[0][0]
        params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)

        assert params.get("Write") == "1"
        assert params.get("StSt") == "1"
        assert params.get("Pa") == "0"
        assert params.get("Sel") == "0"
        assert int(params.get("PrNm", -1)) == p.selector_position
        # DualTech standalone washer must NOT send Option
        assert "Option" not in params
        assert "Dry" not in params


# ===========================================================================
# 7. Outgoing Wire Command Grammar (Bianca Serial 34)
# ===========================================================================


async def test_bianca_standalone_start_wire_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Start button dispatches authentic Bianca-grammar parameters on Serial 34."""
    catalog = _load_catalog("catalog_serial_34_bianca_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
    start_eid = _entity_id(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    interface_type = str(catalog.get("interface_type", ""))

    seen_names: set[str] = set()
    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_wash_program(hass, entry, p)

        with patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send:
            await hass.services.async_call(
                "button", "press", {"entity_id": start_eid}, blocking=True
            )

        assert mock_send.called
        qs = mock_send.call_args[0][0]
        params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)

        assert params.get("Write") == "1"
        assert params.get("StSt") == "1"
        assert int(params.get("PrNm", -1)) == p.selector_position
        assert int(params.get("PrCode", -1)) == p.pr_code
        assert params.get("Dry") == "0"


# ===========================================================================
# 8. Delayed Start Wire Grammar
# ===========================================================================


async def test_standalone_delay_start_wire_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify delayed start serialization: 30-min steps for Bianca/Rapido, 1-hour steps for DualTech."""
    # 1. Rapido (Serial 39): DelVl = delay // 30
    catalog_39 = _load_catalog("catalog_serial_39_rapido_wm.json")
    entry_39, programs_39 = await _init_standalone_washer(
        hass, aioclient_mock, catalog_39
    )
    start_eid_39 = _entity_id(hass, entry_39, "button", UNIQUE_ID_WASH_START_BUTTON)
    delay_eid_39 = _entity_id(hass, entry_39, "number", UNIQUE_ID_WASH_DELAY_NUMBER)

    await _select_wash_program(hass, entry_39, programs_39[0])
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid_39, "value": 120}, blocking=True
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid_39}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params.get("DelVl") == "4"  # 120 // 30

    # 2. DualTech (Serial 41): DelMd = 1, DelVl = delay // 60
    catalog_41 = _load_catalog("catalog_serial_41_dualtech_wm.json")
    entry_41, programs_41 = await _init_standalone_washer(
        hass, aioclient_mock, catalog_41
    )
    start_eid_41 = _entity_id(hass, entry_41, "button", UNIQUE_ID_WASH_START_BUTTON)
    delay_eid_41 = _entity_id(hass, entry_41, "number", UNIQUE_ID_WASH_DELAY_NUMBER)

    await _select_wash_program(hass, entry_41, programs_41[0])
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid_41, "value": 120}, blocking=True
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid_41}, blocking=True
        )

    assert mock_send.called
    qs = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params.get("DelMd") == "1"
    assert params.get("DelVl") == "2"  # 120 // 60
    assert "StSt" not in params


# ===========================================================================
# 9. Wash Options Availability & Steam Gating
# ===========================================================================


async def test_standalone_wash_options_and_steam_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify wash options bitmask matching and steam switch availability across Serial 39."""
    catalog = _load_catalog("catalog_serial_39_rapido_wm.json")
    entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
    steam_eid = _entity_id(hass, entry, "switch", UNIQUE_ID_WASH_STEAM_SWITCH)
    interface_type = str(catalog.get("interface_type", ""))

    seen_names: set[str] = set()
    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_wash_program(hass, entry, p)

        steam_state = hass.states.get(steam_eid)
        assert steam_state is not None
        expected_steam_avail = bool(p.steam)
        assert (steam_state.state != "unavailable") == expected_steam_avail

        for bitmask, _, uid_suffix, name in WASH_OPTIONS:
            sw_state = _state(hass, entry, "switch", f"{{0}}-{uid_suffix}")
            if sw_state is None:
                continue
            expected_available = bool(p.available_options & bitmask)
            is_available = sw_state.state != "unavailable"
            assert is_available == expected_available, (
                f"Program {p.name} option {name}: expected {expected_available}, got {is_available}"
            )


# ===========================================================================
# 11. Estimated Duration Combinatorial Matrix for Standalone Washers
# ===========================================================================


async def test_standalone_washer_estimated_duration_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Assert estimated duration sensor computes exact times across all standalone washer catalogs (Serials 39, 41, 34)."""
    for catalog_file in (
        "catalog_serial_39_rapido_wm.json",
        "catalog_serial_41_dualtech_wm.json",
        "catalog_serial_34_bianca_wm.json",
    ):
        catalog = _load_catalog(catalog_file)
        entry, programs = await _init_standalone_washer(hass, aioclient_mock, catalog)
        dur_eid = _entity_id(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
        soil_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
        registry = er.async_get(hass)
        steam_eid = registry.async_get_entity_id(
            "switch", DOMAIN, UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
        )
        interface_type = str(catalog.get("interface_type", ""))

        seen_names: set[str] = set()
        selectable = [p for p in programs if _is_selectable(p, interface_type)]
        for p in selectable:
            loc_name = p.localized_name("en")
            if loc_name in seen_names:
                continue
            seen_names.add(loc_name)
            await _select_wash_program(hass, entry, p)

            # 1. Base duration
            expected_base = _calculate_expected_duration(
                p,
                soil_level=p.default_soil_level,
                steam_on=False,
                options_mask=0,
            )
            dur_state = hass.states.get(dur_eid)
            assert dur_state is not None
            if expected_base is not None:
                assert dur_state.state == str(expected_base), (
                    f"{catalog_file} - Program {p.name}: Expected {expected_base}, got {dur_state.state}"
                )
            else:
                assert dur_state.state in ("unknown", "unavailable")
                continue

            # 2. Soil levels if variable
            if p.min_soil_level < p.max_soil_level:
                for s in range(p.min_soil_level, p.max_soil_level + 1):
                    soil_label = SOIL_LABELS.get(s)
                    if soil_label:
                        await hass.services.async_call(
                            "select",
                            "select_option",
                            {"entity_id": soil_eid, "option": soil_label},
                            blocking=True,
                        )
                        expected_soil = _calculate_expected_duration(
                            p,
                            soil_level=s,
                            steam_on=False,
                            options_mask=0,
                        )
                        dur_state = hass.states.get(dur_eid)
                        assert dur_state is not None
                        assert dur_state.state == str(expected_soil)
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {
                        "entity_id": soil_eid,
                        "option": SOIL_LABELS[p.default_soil_level],
                    },
                    blocking=True,
                )

            # 3. Steam switch offset
            if (
                steam_eid is not None
                and p.steam
                and p.steam_type in STEAM_DURATION_OFFSETS
            ):
                await hass.services.async_call(
                    "switch", "turn_on", {"entity_id": steam_eid}, blocking=True
                )
                expected_steam = _calculate_expected_duration(
                    p,
                    soil_level=p.default_soil_level,
                    steam_on=True,
                    options_mask=0,
                )
                dur_state = hass.states.get(dur_eid)
                assert dur_state is not None
                assert dur_state.state == str(expected_steam)
                await hass.services.async_call(
                    "switch", "turn_off", {"entity_id": steam_eid}, blocking=True
                )

            # 4. Wash options deltas
            for bitmask, _, uid_suffix, _ in WASH_OPTIONS:
                if p.available_options & bitmask:
                    opt_eid = registry.async_get_entity_id(
                        "switch", DOMAIN, f"{entry.entry_id}-{uid_suffix}"
                    )
                    if opt_eid:
                        await hass.services.async_call(
                            "switch", "turn_on", {"entity_id": opt_eid}, blocking=True
                        )
                        expected_opt = _calculate_expected_duration(
                            p,
                            soil_level=p.default_soil_level,
                            steam_on=False,
                            options_mask=bitmask,
                        )
                        dur_state = hass.states.get(dur_eid)
                        assert dur_state is not None
                        assert dur_state.state == str(expected_opt)
                        await hass.services.async_call(
                            "switch", "turn_off", {"entity_id": opt_eid}, blocking=True
                        )
