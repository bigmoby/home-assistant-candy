r"""Comprehensive Combinatorial Matrix Tests for Washing Machine & Washer-Dryer Programs.

Grounded entirely in authentic appliance catalog data (extras/demo-db/appliance_catalog.json,
Serial 38: RapidO Washer-Dryer ROW 4854DXH\\1-S) and APK duration rules
(extras/decompiled/candy/assets/assisted/full_remaining_time_value_v11.json).

Verifies all aspects of program combinations without synthetic guesswork:
1. Program catalog loading & entity registration across all program types (Wash, Wash+Dry, Dry)
2. Temperature bounds, default selection, and allowed dropdown options
3. Spin speed bounds, default selection, and allowed dropdown options
4. Soil level availability, bounds, and defaults
5. Wash option switches (Prewash, Hygiene+, etc.) availability against available_options
6. Option switch reset on switching to an incompatible program
7. Steam switch availability and gating against program.steam
8. Dry target selection & wash/dry combinations
9. Outgoing wire command grammar & register sanitization on Start button press
10. AutoClean maintenance cycle exclusion from select and execution via limescale button
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
    DRY_TARGET_CUPBOARD_DRY,
    DRY_TARGET_DURATIONS,
    DRY_TARGET_NO_DRY,
    FLANGIA_PROGRAMS_TO_HIDE,
    MODE_FULL_CONTROL,
    PROGRAM_TYPE_DRYING,
    PROGRAM_TYPE_WASH_AND_DRY,
    PROGRAM_TYPE_WASHING,
    PROGRAM_TYPES,
    SOIL_LABELS,
    STEAM_DURATION_OFFSETS,
    UNIQUE_ID_WASH_DRY_SELECT,
    UNIQUE_ID_WASH_ESTIMATED_DURATION,
    UNIQUE_ID_WASH_LIMESCALE_BUTTON,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT,
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


def _load_catalog_serial_38() -> dict:
    path = _FIXTURES_DIR / "catalog_serial_38_rapido_wd.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_catalog_serial_33() -> dict:
    path = _FIXTURES_DIR / "catalog_serial_33_dualtech_wd.json"
    with open(path, encoding="utf-8") as f:
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


async def _init_catalog_appliance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    catalog: dict,
    status_json: str = _IDLE_JSON,
) -> tuple[MockConfigEntry, list[WashingMachineWashProgram]]:
    """Initialize a full control integration with authentic catalog programs."""
    raw_programs = catalog["programs"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"test-catalog-{catalog['serial']}",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: raw_programs,
            CONF_KEY_INTERFACE_TYPE: catalog.get("interface_type", "RAPIDO_4DIG_STM"),
            CONF_KEY_IS_WASHER_DRYER: catalog.get("type") == "washer_dryer",
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


def _state(hass: HomeAssistant, entry: MockConfigEntry, platform: str, uid_tpl: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        platform, DOMAIN, uid_tpl.format(entry.entry_id)
    )
    if entity_id is None:
        return None
    return hass.states.get(entity_id)


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, uid_tpl: str
) -> str:
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id(platform, DOMAIN, uid_tpl.format(entry.entry_id))
    assert eid is not None, f"Entity not found for {platform}.{uid_tpl}"
    return eid


def _is_selectable(p: WashingMachineWashProgram, interface_type: str) -> bool:
    """Return True if the program is user-selectable from select.wash_program."""
    if "autoclean" in p.name.lower():
        return False
    return not (
        is_dualtech(interface_type) and p.name.upper() in FLANGIA_PROGRAMS_TO_HIDE
    )


async def _select_program(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    program: WashingMachineWashProgram,
) -> None:
    """Select a program, ensuring the appropriate program type is active on washer-dryers."""
    registry = er.async_get(hass)
    type_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT.format(entry.entry_id)
    )
    if type_eid is not None:
        if program.is_dry:
            target_type = PROGRAM_TYPE_DRYING
        elif program.is_wash_and_dry:
            target_type = PROGRAM_TYPE_WASH_AND_DRY
        else:
            target_type = PROGRAM_TYPE_WASHING

        current_type = hass.states.get(type_eid)
        if current_type is None or current_type.state != target_type:
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": type_eid, "option": target_type},
                blocking=True,
            )

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
    dry_target: str | None,
    options_mask: int,
) -> int | None:
    if program.is_dry:
        dry_duration = DRY_TARGET_DURATIONS.get(dry_target, 0) if dry_target else 0
        return (
            dry_duration
            if dry_duration > 0
            else (program.default_duration if program.default_duration > 0 else None)
        )

    if program.min_soil_level < program.max_soil_level:
        base = program.duration_for_soil(soil_level)
    else:
        base = program.default_duration

    if base <= 0:
        return None

    minutes = base
    if steam_on and program.steam_type in STEAM_DURATION_OFFSETS:
        minutes += STEAM_DURATION_OFFSETS[program.steam_type]

    if dry_target:
        minutes += DRY_TARGET_DURATIONS.get(dry_target, 0)

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
# 1. Program Discovery & Localization
# ===========================================================================


async def test_program_catalog_discovery(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Assert all selectable programs from Serial 38 appear across program type modes."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)

    assert len(programs) == 22

    interface_type = str(catalog.get("interface_type", ""))
    selectable = [p for p in programs if _is_selectable(p, interface_type)]
    assert (
        len(selectable) == 21
    )  # 22 minus AUTOCLEAN (TUMBLING is hidden only on DualTech)

    type_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    prog_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)

    observed_program_names: set[str] = set()

    for p_type in PROGRAM_TYPES:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": type_eid, "option": p_type},
            blocking=True,
        )
        state = hass.states.get(prog_eid)
        assert state is not None
        for opt in state.attributes.get("options", []):
            observed_program_names.add(opt)

    for p in selectable:
        loc_name = p.localized_name("en")
        assert loc_name in observed_program_names, (
            f"Program {p.name} ({loc_name}) not exposed in select options"
        )
        assert p.pr_code is not None

    # AUTOCLEAN must NOT be in standard program select options
    autoclean_prog = next((p for p in programs if "autoclean" in p.name.lower()), None)
    assert autoclean_prog is not None
    assert autoclean_prog.localized_name("en") not in observed_program_names


async def test_dualtech_program_catalog_discovery(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Assert DualTech Serial 33 programs appear and FLANGIA bezel slots are hidden."""
    catalog = _load_catalog_serial_33()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)

    assert len(programs) == 20

    interface_type = str(catalog.get("interface_type", ""))
    assert is_dualtech(interface_type)

    selectable = [p for p in programs if _is_selectable(p, interface_type)]
    assert (
        len(selectable) == 18
    )  # 20 minus SMART_FI_PLUS and TUMBLING (both in FLANGIA_PROGRAMS_TO_HIDE)

    type_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    prog_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)

    observed_program_names: set[str] = set()

    for p_type in PROGRAM_TYPES:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": type_eid, "option": p_type},
            blocking=True,
        )
        state = hass.states.get(prog_eid)
        assert state is not None
        for opt in state.attributes.get("options", []):
            observed_program_names.add(opt)

    for p in selectable:
        loc_name = p.localized_name("en")
        assert loc_name in observed_program_names, (
            f"DualTech program {p.name} ({loc_name}) not exposed in select options"
        )
        assert p.pr_code is not None

    # SMART_FI_PLUS and TUMBLING must NOT be exposed in select options on DualTech
    for hidden_name in ("SMART_FI_PLUS", "TUMBLING"):
        hidden_prog = next((p for p in programs if p.name.upper() == hidden_name), None)
        assert hidden_prog is not None
        assert hidden_prog.localized_name("en") not in observed_program_names


# ===========================================================================
# 2. Temperature Bounds & Constraint Matrix
# ===========================================================================


async def test_temperature_selection_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Verify temperature dropdown bounds and defaults across every catalog program."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    temp_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        await _select_program(hass, entry, p)
        temp_state = hass.states.get(temp_eid)
        assert temp_state is not None

        if p.is_dry or p.max_temperature in (0, 255):
            assert temp_state.state in ("unavailable", str(p.default_temperature))
        else:
            assert temp_state.state not in ("unavailable", "unknown")
            opts = temp_state.attributes.get("options", [])
            for opt in opts:
                assert int(opt) <= p.max_temperature, (
                    f"Program {p.name} exposes temperature {opt} > max_temp {p.max_temperature}"
                )
            if str(p.default_temperature) in opts:
                assert temp_state.state == str(p.default_temperature)


# ===========================================================================
# 3. Spin Speed Bounds & Constraint Matrix
# ===========================================================================


async def test_spin_speed_selection_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Verify spin speed dropdown bounds and defaults across every catalog program."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    spin_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        await _select_program(hass, entry, p)
        spin_state = hass.states.get(spin_eid)
        assert spin_state is not None

        if p.is_dry or p.max_spin_speed in (0, 255):
            assert spin_state.state in ("unavailable", str(p.default_spin_speed))
        else:
            assert spin_state.state not in ("unavailable", "unknown")
            opts = spin_state.attributes.get("options", [])
            for opt in opts:
                assert int(opt) <= p.max_spin_speed, (
                    f"Program {p.name} exposes spin {opt} > max_spin {p.max_spin_speed}"
                )
            if str(p.default_spin_speed) in opts:
                assert spin_state.state == str(p.default_spin_speed)


# ===========================================================================
# 4. Soil Level Selection & Gating Matrix
# ===========================================================================


async def test_soil_level_selection_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Verify soil level availability is gated strictly by min_soil < max_soil."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    soil_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        await _select_program(hass, entry, p)
        soil_state = hass.states.get(soil_eid)
        assert soil_state is not None

        if not p.is_dry and p.min_soil_level < p.max_soil_level:
            assert soil_state.state not in ("unavailable", "unknown"), (
                f"Program {p.name} has soil range [{p.min_soil_level}, {p.max_soil_level}] "
                "but soil select is unavailable"
            )
        else:
            assert soil_state.state == "unavailable", (
                f"Program {p.name} has fixed soil level {p.min_soil_level} "
                "but soil select is available"
            )


# ===========================================================================
# 5. Wash Options Availability & Auto-Reset on Program Switch
# ===========================================================================


async def test_wash_options_availability_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Verify each WashOptionSwitch reports available strictly matching available_options."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    interface_type = str(catalog.get("interface_type", ""))

    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        await _select_program(hass, entry, p)

        for bitmask, _, uid_suffix, name in WASH_OPTIONS:
            sw_state = _state(hass, entry, "switch", f"{{0}}-{uid_suffix}")
            if sw_state is None:
                continue

            expected_available = bool(p.available_options & bitmask) and not p.is_dry
            is_available = sw_state.state != "unavailable"

            assert is_available == expected_available, (
                f"Program {p.name} option {name} (bitmask {bitmask}): "
                f"expected available={expected_available} "
                f"(available_options={p.available_options}), got {is_available}"
            )


async def test_wash_option_resets_on_switching_to_incompatible_program(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Turning an option ON in a supported program must auto-reset when switching to an unsupported one."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    interface_type = str(catalog.get("interface_type", ""))

    selectable = [p for p in programs if _is_selectable(p, interface_type)]
    prog_with_prewash = next((p for p in selectable if p.available_options & 1), None)
    prog_without_prewash = next(
        (p for p in selectable if not (p.available_options & 1)), None
    )

    assert prog_with_prewash is not None
    assert prog_without_prewash is not None

    prewash_eid = _entity_id(hass, entry, "switch", "{0}-wash_option_prewash")

    # 1. Select supporting program
    await _select_program(hass, entry, prog_with_prewash)
    assert hass.states.get(prewash_eid).state == "off"

    # 2. Turn prewash ON
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )
    assert hass.states.get(prewash_eid).state == "on"

    # 3. Switch to program without prewash support
    await _select_program(hass, entry, prog_without_prewash)
    state = hass.states.get(prewash_eid)
    assert state.state == "unavailable"


# ===========================================================================
# 6. Steam Switch Gating Matrix
# ===========================================================================


async def test_steam_switch_availability_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Verify steam switch availability strictly reflects program.steam."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    steam_eid = _entity_id(hass, entry, "switch", UNIQUE_ID_WASH_STEAM_SWITCH)
    interface_type = str(catalog.get("interface_type", ""))

    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        await _select_program(hass, entry, p)
        steam_state = hass.states.get(steam_eid)
        assert steam_state is not None

        expected_available = bool(p.steam) and not p.is_dry
        is_available = steam_state.state != "unavailable"

        assert is_available == expected_available, (
            f"Program {p.name}: expected steam switch available={expected_available} "
            f"(steam={p.steam}), got {is_available}"
        )


# ===========================================================================
# 7. Dry Target Gating & Selection
# ===========================================================================


async def test_dry_target_gating_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Verify dry target select options and availability across washer-dryer programs."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    dry_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        await _select_program(hass, entry, p)
        dry_state = hass.states.get(dry_eid)
        assert dry_state is not None

        if p.is_dry:
            assert DRY_TARGET_NO_DRY not in dry_state.attributes.get("options", [])
        elif not p.dry_supported:
            assert dry_state.state == DRY_TARGET_NO_DRY


# ===========================================================================
# 8. Outgoing Wire Command Grammar & Register Sanitization Matrix
# ===========================================================================


async def test_start_wire_command_sanitization_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Pressing Start on any catalog program generates compliant query string without illegal bits."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    start_eid = _entity_id(hass, entry, "button", UNIQUE_ID_WASH_START_BUTTON)
    dry_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    for p in [pr for pr in programs if _is_selectable(pr, interface_type)]:
        await _select_program(hass, entry, p)

        if p.is_dry:
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": dry_eid, "option": DRY_TARGET_CUPBOARD_DRY},
                blocking=True,
            )

        with patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send:
            await hass.services.async_call(
                "button", "press", {"entity_id": start_eid}, blocking=True
            )

        assert mock_send.called, f"Program {p.name}: Start button did not send command"
        qs: str = mock_send.call_args[0][0]

        params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)

        # 1. Basic write command integrity
        assert params.get("Write") == "1"
        assert params.get("StSt") == "1"

        # 2. Program selector dial position and code
        assert int(params.get("PrNm", -1)) == p.selector_position
        assert int(params.get("PrCode", -1)) == p.pr_code

        # 3. Temperature sanitization
        if "TmpTgt" in params and p.max_temperature not in (0, 255):
            assert int(params["TmpTgt"]) <= p.max_temperature, (
                f"Program {p.name}: sent TmpTgt={params['TmpTgt']} > max_temp {p.max_temperature}"
            )

        # 4. Spin speed sanitization
        if "SpdTgt" in params and p.max_spin_speed not in (0, 255):
            assert int(params["SpdTgt"]) * 100 <= p.max_spin_speed, (
                f"Program {p.name}: sent SpdTgt={params['SpdTgt']} > max_spin {p.max_spin_speed}"
            )

        # 5. Soil level sanitization: SLevTgt must not exceed max_soil_level
        if "SLevTgt" in params and p.max_soil_level > 0:
            assert int(params["SLevTgt"]) <= p.max_soil_level, (
                f"Program {p.name}: sent SLevTgt={params['SLevTgt']} > max_soil {p.max_soil_level}"
            )

        # 6. OptMsk1 illegal bits prevention: wire OptMsk1 must NEVER contain bits outside available_options
        if "OptMsk1" in params:
            sent_mask = int(params["OptMsk1"])
            illegal_bits = sent_mask & (~p.available_options)
            assert illegal_bits == 0, (
                f"Program {p.name}: sent OptMsk1={sent_mask} containing illegal bits {illegal_bits} "
                f"(allowed available_options={p.available_options})"
            )


# ===========================================================================
# 9. AutoClean Maintenance Program Gating
# ===========================================================================


async def test_autoclean_maintenance_button_execution(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """AutoClean is executed via the dedicated limescale maintenance button, sending pr_code=104."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)

    autoclean_prog = next((p for p in programs if "autoclean" in p.name.lower()), None)
    assert autoclean_prog is not None

    limescale_eid = _entity_id(hass, entry, "button", UNIQUE_ID_WASH_LIMESCALE_BUTTON)
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": limescale_eid}, blocking=True
        )

    assert mock_send.called
    qs: str = mock_send.call_args[0][0]
    params = dict(item.split("=", 1) for item in qs.split("&") if "=" in item)
    assert params.get("Write") == "1"
    assert int(params.get("PrCode", 0)) == autoclean_prog.pr_code
    assert int(params.get("PrNm", 0)) == autoclean_prog.selector_position


# ===========================================================================
# 10. Estimated Duration Combinatorial Matrix (Serial 38 & Serial 33)
# ===========================================================================


async def test_estimated_duration_matrix_serial_38(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Assert estimated duration sensor computes exact times across all program combinations on Serial 38 WD."""
    catalog = _load_catalog_serial_38()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    dur_eid = _entity_id(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    soil_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    steam_eid = _entity_id(hass, entry, "switch", UNIQUE_ID_WASH_STEAM_SWITCH)
    dry_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    interface_type = str(catalog.get("interface_type", ""))
    registry = er.async_get(hass)

    selectable_programs = [p for p in programs if _is_selectable(p, interface_type)]

    for p in selectable_programs:
        await _select_program(hass, entry, p)

        dry_state = hass.states.get(dry_eid)
        active_dry = (
            dry_state.state
            if dry_state and dry_state.state != DRY_TARGET_NO_DRY
            else None
        )

        # 1. Base duration
        expected = _calculate_expected_duration(
            p,
            soil_level=p.default_soil_level,
            steam_on=False,
            dry_target=active_dry,
            options_mask=0,
        )
        dur_state = hass.states.get(dur_eid)
        assert dur_state is not None
        assert dur_state.state == str(expected), (
            f"Program {p.name}: default duration mismatch. Expected {expected}, got {dur_state.state}"
        )

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
                        dry_target=active_dry,
                        options_mask=0,
                    )
                    dur_state = hass.states.get(dur_eid)
                    assert dur_state is not None
                    assert dur_state.state == str(expected_soil), (
                        f"Program {p.name} at soil {s}: Expected {expected_soil}, got {dur_state.state}"
                    )
            # Reset back to default soil
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": soil_eid, "option": SOIL_LABELS[p.default_soil_level]},
                blocking=True,
            )

        # 3. Steam switch offset
        if p.steam and p.steam_type in STEAM_DURATION_OFFSETS:
            await hass.services.async_call(
                "switch", "turn_on", {"entity_id": steam_eid}, blocking=True
            )
            expected_steam = _calculate_expected_duration(
                p,
                soil_level=p.default_soil_level,
                steam_on=True,
                dry_target=active_dry,
                options_mask=0,
            )
            dur_state = hass.states.get(dur_eid)
            assert dur_state is not None
            assert dur_state.state == str(expected_steam), (
                f"Program {p.name} with steam: Expected {expected_steam}, got {dur_state.state}"
            )
            await hass.services.async_call(
                "switch", "turn_off", {"entity_id": steam_eid}, blocking=True
            )

        # 4. Extra wash options deltas for supported options
        if not p.is_dry:
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
                            dry_target=active_dry,
                            options_mask=bitmask,
                        )
                        dur_state = hass.states.get(dur_eid)
                        assert dur_state is not None
                        assert dur_state.state == str(expected_opt), (
                            f"Program {p.name} with option {uid_suffix}: Expected {expected_opt}, got {dur_state.state}"
                        )
                        await hass.services.async_call(
                            "switch", "turn_off", {"entity_id": opt_eid}, blocking=True
                        )


async def test_estimated_duration_matrix_serial_33(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Assert estimated duration sensor computes exact times across all program combinations on Serial 33 DualTech WD."""
    catalog = _load_catalog_serial_33()
    entry, programs = await _init_catalog_appliance(hass, aioclient_mock, catalog)
    dur_eid = _entity_id(hass, entry, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    dry_eid = _entity_id(hass, entry, "select", UNIQUE_ID_WASH_DRY_SELECT)
    interface_type = str(catalog.get("interface_type", ""))

    selectable_programs = [p for p in programs if _is_selectable(p, interface_type)]

    for p in selectable_programs:
        await _select_program(hass, entry, p)
        dur_state = hass.states.get(dur_eid)
        dry_state = hass.states.get(dry_eid) if dry_eid else None
        active_dry = (
            dry_state.state
            if dry_state
            and dry_state.state not in (DRY_TARGET_NO_DRY, "unavailable", "unknown")
            else None
        )
        expected = _calculate_expected_duration(
            p,
            soil_level=p.default_soil_level,
            steam_on=False,
            dry_target=active_dry,
            options_mask=0,
        )
        if expected is not None:
            assert dur_state is not None
            assert dur_state.state == str(expected), (
                f"Program {p.name} (Serial 33): Expected {expected}, got {dur_state.state}"
            )
