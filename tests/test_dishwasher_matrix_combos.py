"""Comprehensive Combinatorial Matrix Tests for Dishwasher Programs.

Grounded entirely in authentic appliance catalog data (catalog_serial_40_brava_dw.json,
Candy Brava CDIN 4D530PB, interface BRAVA_BI_DIGIT_OD) and legacy touch interfaces.

Verifies all aspects of dishwasher program combinations without synthetic guesswork:
1. Program catalog loading & entity registration across all 9 catalog cycles.
2. Option switch availability gating per program (Eco, MetaCarico, ExtraDry, TreinUno, OpenDoorOpt).
3. Incompatible option switch auto-reset when changing programs.
4. Outgoing wire command grammar & parameter serialization on Start button press.
5. Selector position (w1) dynamic resolution from catalog cycle IDs.
6. Interface-dependent motorized door command filtering (_OD vs non-_OD).
7. Legacy Touch / Built-in wire grammar (OpzProg p/m/0, no w1, hour-denominated delay).
8. Fallback program catalog handling when cloud programs are absent.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DISHWASHER_PROGRAM_PANEL,
    DISHWASHER_PROGRAMS,
    MODE_FULL_CONTROL,
    UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH,
    UNIQUE_ID_DISHWASHER_DELAY_NUMBER,
    UNIQUE_ID_DISHWASHER_ECO_SWITCH,
    UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH,
    UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH,
    UNIQUE_ID_DISHWASHER_PROGRAM_SELECT,
    UNIQUE_ID_DISHWASHER_START_BUTTON,
    UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH,
)

from .common import TEST_IP, init_integration

_CATALOG_PATH = Path(__file__).parent / "fixtures" / "catalog_serial_40_brava_dw.json"
_READY = "dishwasher/remote_ready.json"
_STATS = '{"statusCounters": {"s1": "10"}}'


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


async def _setup_brava_dishwasher(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    interface_type: str = "BRAVA_BI_DIGIT_OD",
) -> tuple[MockConfigEntry, dict[str, str]]:
    catalog = _load_dw_catalog()
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: interface_type,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )

    entities = {
        "select": _entity_id(
            hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT
        ),
        "start": _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON),
        "delay": _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER),
        "eco": _entity_id(hass, entry, "switch", UNIQUE_ID_DISHWASHER_ECO_SWITCH),
        "half_load": _entity_id(
            hass, entry, "switch", UNIQUE_ID_DISHWASHER_HALF_LOAD_SWITCH
        ),
        "extra_dry": _entity_id(
            hass, entry, "switch", UNIQUE_ID_DISHWASHER_EXTRA_DRY_SWITCH
        ),
        "three_in_one": _entity_id(
            hass, entry, "switch", UNIQUE_ID_DISHWASHER_THREE_IN_ONE_SWITCH
        ),
    }

    auto_door_id = _optional_entity_id(
        hass, entry, "switch", UNIQUE_ID_DISHWASHER_AUTO_DOOR_SWITCH
    )
    if auto_door_id:
        entities["auto_door"] = auto_door_id

    return entry, entities


async def test_brava_all_9_catalog_programs_option_availability_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify that every program in the authentic Brava catalog accurately gates option switches.

    Bitmask definitions:
      Bit 0 (1): Extra Dry
      Bit 1 (2): Half Load
      Bit 2 (4): Eco
      Bit 3 (8): 3-in-1 Tablet
      Bit 4 (16): Motorized Auto Door
    """
    _, entities = await _setup_brava_dishwasher(hass, aioclient_mock)
    select_id = entities["select"]

    # Expected option permissions for all 9 programs from catalog_serial_40_brava_dw.json
    program_matrix = [
        # (program_name, extra_dry, half_load, eco, three_in_one, auto_door)
        ("Eco 45°C", True, True, True, True, True),  # opt_mask 31 (11111)
        ("Intensive 75°C", True, True, True, True, True),  # opt_mask 31 (11111)
        ("Night 55°C", False, False, True, True, True),  # opt_mask 28 (11100)
        ("Universal 60°C", True, True, True, True, True),  # opt_mask 31 (11111)
        ("Auto Daily 55 - 65°C", True, True, True, True, True),  # opt_mask 31 (11111)
        ("Delicate 45°C", True, True, True, True, True),  # opt_mask 31 (11111)
        ("ZOOM 39' 60°C", False, False, True, True, True),  # opt_mask 28 (11100)
        ("Rapid 24' 50°C", False, False, False, True, False),  # opt_mask 8  (01000)
        ("Pre-wash - 5 min", False, False, False, True, False),  # opt_mask 8  (01000)
    ]

    for (
        prog_name,
        exp_ed,
        exp_hl,
        exp_eco,
        exp_3in1,
        exp_ad,
    ) in program_matrix:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": select_id, "option": prog_name},
            blocking=True,
        )

        assert (
            hass.states.get(entities["extra_dry"]).state != "unavailable"
        ) == exp_ed, f"{prog_name} ExtraDry mismatch"
        assert (
            hass.states.get(entities["half_load"]).state != "unavailable"
        ) == exp_hl, f"{prog_name} HalfLoad mismatch"
        assert (hass.states.get(entities["eco"]).state != "unavailable") == exp_eco, (
            f"{prog_name} Eco mismatch"
        )
        assert (
            hass.states.get(entities["three_in_one"]).state != "unavailable"
        ) == exp_3in1, f"{prog_name} ThreeInOne mismatch"
        assert (
            hass.states.get(entities["auto_door"]).state != "unavailable"
        ) == exp_ad, f"{prog_name} AutoDoor mismatch"


async def test_incompatible_options_auto_reset_on_program_switching(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When an option is enabled and user switches to a program disallowing it, switch becomes unavailable."""
    _, entities = await _setup_brava_dishwasher(hass, aioclient_mock)
    select_id = entities["select"]

    # 1. Under Eco 45°C (all allowed), turn on Half Load and Extra Dry
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "Eco 45°C"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entities["half_load"]},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entities["extra_dry"]},
        blocking=True,
    )
    assert hass.states.get(entities["half_load"]).state == "on"
    assert hass.states.get(entities["extra_dry"]).state == "on"

    # 2. Switch to ZOOM 39' 60°C (disallows Half Load & Extra Dry)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "ZOOM 39' 60°C"},
        blocking=True,
    )
    assert hass.states.get(entities["half_load"]).state == "unavailable"
    assert hass.states.get(entities["extra_dry"]).state == "unavailable"


async def test_outgoing_wire_command_and_selector_w1_serialization(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify that pressing Start transmits the exact wire grammar with w1 selector position."""
    _, entities = await _setup_brava_dishwasher(hass, aioclient_mock)
    select_id = entities["select"]

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json",
        text='{"response":"OK"}',
    )

    # Test cases: (program, delay, options_to_turn_on, exp_prog, exp_w1, exp_opz, exp_open_door, exp_3in1, exp_ed)
    test_cases = [
        # Eco 45°C (cycle 8, pos 1) with 60 min delay and 3-in-1 (8) + AutoDoor (16) = 24
        (
            "Eco 45°C",
            60,
            ["three_in_one", "auto_door"],
            "P8",
            "1",
            "24",
            "1",
            "1",
            "0",
        ),
        # Intensive 75°C (cycle 2, pos 2) with Extra Dry (1) = 1
        ("Intensive 75°C", 0, ["extra_dry"], "P2", "2", "1", "0", "0", "1"),
        # Auto Daily (cycle 16, pos 5) with Eco (4) + Half Load (2) = 6
        (
            "Auto Daily 55 - 65°C",
            0,
            ["eco", "half_load"],
            "P16",
            "5",
            "6",
            "0",
            "0",
            "0",
        ),
        # Rapid 24' (cycle 20, pos 8) with 3-in-1 (8) = 8
        ("Rapid 24' 50°C", 0, ["three_in_one"], "P20", "8", "8", "0", "1", "0"),
    ]

    for (
        prog_name,
        delay_val,
        opts_on,
        exp_prog,
        exp_w1,
        exp_opz,
        exp_od,
        exp_3in1,
        exp_ed,
    ) in test_cases:
        # Select program
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": select_id, "option": prog_name},
            blocking=True,
        )

        # Set delay
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entities["delay"], "value": delay_val},
            blocking=True,
        )

        # Reset and apply switches
        for opt_key in (
            "eco",
            "half_load",
            "extra_dry",
            "three_in_one",
            "auto_door",
        ):
            if (
                opt_key in entities
                and hass.states.get(entities[opt_key]).state != "unavailable"
            ):
                svc = "turn_on" if opt_key in opts_on else "turn_off"
                await hass.services.async_call(
                    "switch",
                    svc,
                    {"entity_id": entities[opt_key]},
                    blocking=True,
                )

        # Press Start
        await hass.services.async_call(
            "button", "press", {"entity_id": entities["start"]}, blocking=True
        )

        write_calls = [
            call
            for call in aioclient_mock.mock_calls
            if "http-write.json" in str(call[1])
        ]
        assert len(write_calls) > 0
        url = str(write_calls[-1][1])
        parsed = urlparse(url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        assert params.get("StartStop") == "1"
        assert params.get("Program") == exp_prog
        assert params.get("w1") == exp_w1
        assert params.get("DelayStart") == str(delay_val)
        assert params.get("OpzProg") == exp_opz
        assert params.get("OpenDoorOpt") == exp_od
        assert params.get("TreinUno") == exp_3in1
        assert params.get("ExtraDry") == exp_ed


async def test_non_od_brava_model_strictly_excludes_open_door_opt(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Interface without _OD suffix must not register auto_door and excludes OpenDoorOpt."""
    _, entities = await _setup_brava_dishwasher(
        hass, aioclient_mock, interface_type="BRAVA_BI_DIGIT"
    )

    # auto_door switch should not exist
    assert "auto_door" not in entities

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json",
        text='{"response":"OK"}',
    )

    await hass.services.async_call(
        "button", "press", {"entity_id": entities["start"]}, blocking=True
    )

    write_calls = [
        call for call in aioclient_mock.mock_calls if "http-write.json" in str(call[1])
    ]
    assert len(write_calls) > 0
    url = str(write_calls[-1][1])
    parsed = urlparse(url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    assert "OpenDoorOpt" not in params
    assert params.get("StartStop") == "1"


async def test_legacy_touch_dishwasher_wire_command_and_delay_hours(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Family 1 Legacy Wi-Fi Touch dishwashers send OpzProg as p/m/0, omit w1, and scale delay in hours."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture("dishwasher/idle.json"),
        statistics_response=_STATS,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "DishwasherInterfaceTypeFSTouch",
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )

    start_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON)
    delay_id = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)

    # Set delay to 120 minutes (2 hours)
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_id, "value": 120},
        blocking=True,
    )

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json",
        text='{"response":"OK"}',
    )

    # Press start with default program P1 (from idle.json which reports OpzProg="p" -> P1+)
    await hass.services.async_call(
        "button", "press", {"entity_id": start_id}, blocking=True
    )

    write_calls = [
        call for call in aioclient_mock.mock_calls if "http-write.json" in str(call[1])
    ]
    assert len(write_calls) > 0
    url = str(write_calls[-1][1])
    params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

    assert params.get("StartStop") == "1"
    assert params.get("Program") == "P1"
    assert params.get("OpzProg") == "p"
    assert "w1" not in params
    # idle.json has no r15, so 120 min // 60 = 2 hours
    assert params.get("DelayStart") == "2"


async def test_default_catalog_fallback_dropdown_and_w1_resolution(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When no cloud catalog is configured, fallback programs map accurately."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
        },
    )

    select_id = _entity_id(hass, entry, "select", UNIQUE_ID_DISHWASHER_PROGRAM_SELECT)
    start_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON)

    state = hass.states.get(select_id)
    assert state is not None
    assert state.state == DISHWASHER_PROGRAM_PANEL
    expected_options = [DISHWASHER_PROGRAM_PANEL, *DISHWASHER_PROGRAMS.keys()]
    assert state.attributes["options"] == expected_options

    # Select fallback program 'intensive_75' (position 2 in DISHWASHER_PROGRAMS, cycle P2)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "intensive_75"},
        blocking=True,
    )

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json",
        text='{"response":"OK"}',
    )

    await hass.services.async_call(
        "button", "press", {"entity_id": start_id}, blocking=True
    )

    write_calls = [
        call for call in aioclient_mock.mock_calls if "http-write.json" in str(call[1])
    ]
    assert len(write_calls) > 0
    params = {
        k: v[0] for k, v in parse_qs(urlparse(str(write_calls[-1][1])).query).items()
    }

    assert params.get("Program") == "P2"
    assert params.get("w1") == "2"  # intensive_75 maps to selector position 2
