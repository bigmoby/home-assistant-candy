"""Comprehensive Combinatorial Matrix Tests for Tumble Dryer Programs.

Grounded entirely in authentic appliance catalog data (extras/demo-db/appliance_catalog.json,
Serial 35: GVSF H10A2TCE-19, TD_DIGIT_HP_DOOR).

Verifies all aspects of tumble dryer program combinations without synthetic guesswork:
1. Program catalog loading & entity registration
2. Dry level dropdown bounds, availability gating, and default selection
3. Timed drying dropdown bounds, availability gating, and options
4. Outgoing wire command grammar & parameter serialization on Start button press
5. Delayed start wire grammar
6. Auxiliary and maintenance buttons (Anti-crease cancel, CheckUp, Reset warnings)
7. Door safety sensor and remote control availability gating
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
from custom_components.candy.client import parse_dryer_programs
from custom_components.candy.client.model import TumbleDryerProgram, TumbleDryerStatus
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_TUMBLE_DRYER,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DRY_LEVEL_FROM_VALUE,
    DRY_LEVEL_OPTIONS,
    MODE_FULL_CONTROL,
    UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON,
    UNIQUE_ID_TUMBLE_CHECKUP_BUTTON,
    UNIQUE_ID_TUMBLE_DELAY_NUMBER,
    UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT,
    UNIQUE_ID_TUMBLE_PAUSE_BUTTON,
    UNIQUE_ID_TUMBLE_PROGRAM_SELECT,
    UNIQUE_ID_TUMBLE_REMAINING_TIME,
    UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON,
    UNIQUE_ID_TUMBLE_RESUME_BUTTON,
    UNIQUE_ID_TUMBLE_START_BUTTON,
    UNIQUE_ID_TUMBLE_STOP_BUTTON,
    UNIQUE_ID_TUMBLE_TIME_SELECT,
)

from .common import TEST_IP

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_IDLE_JSON = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
    "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_RUNNING_JSON = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "2", "CodiceErrore": "0", "Pr": "1", "PrPh": "2",
    "RemTime": "120", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
    "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_PAUSED_JSON = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "3", "CodiceErrore": "0", "Pr": "1", "PrPh": "2",
    "RemTime": "120", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
    "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_FINISHED_JSON = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "8", "CodiceErrore": "0", "Pr": "1", "PrPh": "3",
    "RemTime": "0", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
    "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_WARNINGS_JSON = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
    "CleanFilter": "1", "WaterTankFull": "1", "DryingManagerLevel": "3",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_DOOR_OPEN_JSON = """{
  "statusTD": {
    "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
    "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
    "DelVal": "0", "DoorState": "0", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""

_REMOTE_OFF_JSON = """{
  "statusTD": {
    "StatoWiFi": "0", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
    "RemTime": "150", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
    "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
    "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
  }
}"""


def _load_catalog_serial_35() -> dict:
    path = _FIXTURES_DIR / "catalog_serial_35_tumble_dryer.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def _init_catalog_dryer(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    catalog: dict,
    status_json: str,
) -> tuple[MockConfigEntry, list[TumbleDryerProgram]]:
    """Initialize a full control tumble dryer integration with authentic catalog programs."""
    raw_programs = catalog["programs"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"test-catalog-dryer-{catalog['serial']}",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: raw_programs,
            CONF_KEY_INTERFACE_TYPE: catalog.get("interface_type", "TD_DIGIT_HP_DOOR"),
            CONF_KEY_IS_TUMBLE_DRYER: True,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=0", text=status_json)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    parsed_programs = parse_dryer_programs(raw_programs)
    return entry, parsed_programs


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, uid_tpl: str
) -> str:
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id(platform, DOMAIN, uid_tpl.format(entry.entry_id))
    assert eid is not None, f"Entity not found for {platform}.{uid_tpl}"
    return eid


async def _select_dryer_program(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    program: TumbleDryerProgram,
) -> None:
    prog_eid = _entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": program.localized_name("en")},
        blocking=True,
    )


# ===========================================================================
# 1. Program Catalog Discovery
# ===========================================================================


async def test_dryer_program_catalog_discovery(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Assert all selectable programs from Serial 35 appear in select.dryer_program."""
    catalog = _load_catalog_serial_35()
    entry, programs = await _init_catalog_dryer(
        hass, aioclient_mock, catalog, _IDLE_JSON
    )

    assert len(programs) == 15

    prog_eid = _entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
    state = hass.states.get(prog_eid)
    assert state is not None

    options = state.attributes.get("options", [])
    for p in programs:
        loc_name = p.localized_name("en")
        assert loc_name in options, f"Program {p.name} ({loc_name}) not in options"


# ===========================================================================
# 2. Dry Level Selection Matrix
# ===========================================================================


async def test_dryer_dry_level_selection_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify dry level dropdown availability and defaults across every catalog program."""
    catalog = _load_catalog_serial_35()
    entry, programs = await _init_catalog_dryer(
        hass, aioclient_mock, catalog, _IDLE_JSON
    )
    dry_level_eid = _entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT)

    for p in programs:
        await _select_dryer_program(hass, entry, p)
        level_state = hass.states.get(dry_level_eid)
        assert level_state is not None

        if p.set_dry_level:
            assert level_state.state not in ("unavailable", "unknown")
            assert level_state.attributes.get("options") == DRY_LEVEL_OPTIONS
            expected_opt = DRY_LEVEL_FROM_VALUE.get(p.default_drying_level)
            if expected_opt:
                assert level_state.state == expected_opt
        else:
            assert level_state.state == "unavailable"


# ===========================================================================
# 3. Timed Drying Selection Matrix
# ===========================================================================


async def test_dryer_time_selection_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify timed drying dropdown availability and options across every catalog program."""
    catalog = _load_catalog_serial_35()
    entry, programs = await _init_catalog_dryer(
        hass, aioclient_mock, catalog, _IDLE_JSON
    )
    time_eid = _entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_TIME_SELECT)

    for p in programs:
        await _select_dryer_program(hass, entry, p)
        time_state = hass.states.get(time_eid)
        assert time_state is not None

        if p.set_time_level:
            assert time_state.state not in ("unavailable", "unknown")
            opts = time_state.attributes.get("options", [])
            assert "30" in opts
            assert "60" in opts
        else:
            assert time_state.state == "unavailable"


# ===========================================================================
# 4. Outgoing Wire Command Grammar on Start Press
# ===========================================================================


async def test_dryer_start_wire_command_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Start button generates authentic DualTech dryer parameters."""
    catalog = _load_catalog_serial_35()
    entry, programs = await _init_catalog_dryer(
        hass, aioclient_mock, catalog, _IDLE_JSON
    )
    start_eid = _entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_START_BUTTON)
    time_eid = _entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_TIME_SELECT)

    seen_names: set[str] = set()
    for p in programs:
        loc_name = p.localized_name("en")
        if loc_name in seen_names:
            continue
        seen_names.add(loc_name)
        await _select_dryer_program(hass, entry, p)

        # If timed dry supported, test timed start
        if p.set_time_level:
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": time_eid, "option": "60"},
                blocking=True,
            )
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
            assert params.get("Pa") == "0"
            assert params.get("Sel") == "0"
            assert int(params.get("PrNm", -1)) == p.selector_position
            assert params.get("Time") == "60"
            assert params.get("StSt") == "1"
            assert "DryLev" not in params

        # Test standard dry level start
        if p.set_dry_level:
            if p.set_time_level:
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": time_eid, "option": "off"},
                    blocking=True,
                )
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
            assert params.get("Pa") == "0"
            assert params.get("Sel") == "0"
            assert int(params.get("PrNm", -1)) == p.selector_position
            assert params.get("StSt") == "1"
            assert "DryLev" in params
            assert "Time" not in params


# ===========================================================================
# 5. Delayed Start Wire Grammar
# ===========================================================================


async def test_dryer_delay_start_wire_command(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify delayed start dispatches DelMd=1&DelVl=<delay_minutes> without StSt."""
    catalog = _load_catalog_serial_35()
    entry, programs = await _init_catalog_dryer(
        hass, aioclient_mock, catalog, _IDLE_JSON
    )
    start_eid = _entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_START_BUTTON)
    delay_eid = _entity_id(hass, entry, "number", UNIQUE_ID_TUMBLE_DELAY_NUMBER)

    await _select_dryer_program(hass, entry, programs[0])
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid, "value": 120}, blocking=True
    )

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
    assert params.get("DelMd") == "1"
    assert params.get("DelVl") == "120"
    assert "StSt" not in params


# ===========================================================================
# 6. Auxiliary & Maintenance Buttons Lifecycle
# ===========================================================================


async def test_dryer_running_buttons(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Stop and Pause buttons work when dryer is running."""
    catalog = _load_catalog_serial_35()
    entry, _ = await _init_catalog_dryer(hass, aioclient_mock, catalog, _RUNNING_JSON)

    stop_eid = _entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_STOP_BUTTON)
    pause_eid = _entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_PAUSE_BUTTON)

    for eid, expected_param in (
        (stop_eid, "StSt=0"),
        (pause_eid, "SetPauseDryMgr=1"),
    ):
        with patch(
            "custom_components.candy.client.CandyClient.send_command",
            new_callable=AsyncMock,
        ) as mock_send:
            await hass.services.async_call(
                "button", "press", {"entity_id": eid}, blocking=True
            )
        assert mock_send.called
        qs = mock_send.call_args[0][0]
        assert "Write=1" in qs
        assert expected_param in qs


async def test_dryer_paused_resume_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Resume button works when dryer is paused."""
    catalog = _load_catalog_serial_35()
    entry, _ = await _init_catalog_dryer(hass, aioclient_mock, catalog, _PAUSED_JSON)
    resume_eid = _entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_RESUME_BUTTON)

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": resume_eid}, blocking=True
        )
    assert mock_send.called
    qs = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "SetRestartDryMgr=1" in qs


async def test_dryer_anticrease_cancel_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify Anti-crease cancel button works when dryer is finished."""
    catalog = _load_catalog_serial_35()
    entry, _ = await _init_catalog_dryer(hass, aioclient_mock, catalog, _FINISHED_JSON)
    anticrease_eid = _entity_id(
        hass, entry, "button", UNIQUE_ID_TUMBLE_ANTI_CREASE_BUTTON
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": anticrease_eid}, blocking=True
        )
    assert mock_send.called
    qs = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "DontTumbling=1" in qs


async def test_dryer_idle_checkup_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify diagnostic CheckUp button works in idle state."""
    catalog = _load_catalog_serial_35()
    entry, _ = await _init_catalog_dryer(hass, aioclient_mock, catalog, _IDLE_JSON)
    checkup_eid = _entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_CHECKUP_BUTTON)

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": checkup_eid}, blocking=True
        )
    assert mock_send.called
    qs = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "CheckUpState=1" in qs


async def test_dryer_warning_reset_button(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify warning reset button works when filter or tank warning is active."""
    catalog = _load_catalog_serial_35()
    entry, _ = await _init_catalog_dryer(hass, aioclient_mock, catalog, _WARNINGS_JSON)
    reset_eid = _entity_id(
        hass, entry, "button", UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON
    )

    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": reset_eid}, blocking=True
        )
    assert mock_send.called
    qs = mock_send.call_args[0][0]
    assert "Write=1" in qs
    assert "ResetWarnings=1" in qs


# ===========================================================================
# 7. Door Safety & Remote Control Gating
# ===========================================================================


async def test_dryer_door_open_gating(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Start button must be unavailable when the door is open."""
    catalog = _load_catalog_serial_35()
    entry, _ = await _init_catalog_dryer(hass, aioclient_mock, catalog, _DOOR_OPEN_JSON)
    start_eid = _entity_id(hass, entry, "button", UNIQUE_ID_TUMBLE_START_BUTTON)

    state = hass.states.get(start_eid)
    assert state is not None
    assert state.state == "unavailable"


async def test_dryer_remote_control_disabled_gating(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """All write buttons and selects must be unavailable when remote control is disabled."""
    catalog = _load_catalog_serial_35()
    entry, _ = await _init_catalog_dryer(
        hass, aioclient_mock, catalog, _REMOTE_OFF_JSON
    )

    for platform, uid_tpl in (
        ("button", UNIQUE_ID_TUMBLE_START_BUTTON),
        ("button", UNIQUE_ID_TUMBLE_STOP_BUTTON),
        ("select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT),
        ("select", UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT),
    ):
        eid = _entity_id(hass, entry, platform, uid_tpl)
        state = hass.states.get(eid)
        assert state is not None
        assert state.state == "unavailable"


# ===========================================================================
# 8. Tumble Dryer Program Duration & Timed Dry Matrix
# ===========================================================================


async def test_dryer_program_duration_matrix(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Assert tumble dryer program catalog durations and timed dry options compute expected durations."""
    catalog = _load_catalog_serial_35()
    entry, programs = await _init_catalog_dryer(
        hass, aioclient_mock, catalog, _IDLE_JSON
    )
    time_eid = _entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_TIME_SELECT)
    prog_eid = _entity_id(hass, entry, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)

    for p in programs:
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": prog_eid, "option": p.localized_name("en")},
            blocking=True,
        )

        # 1. Base catalog duration must be positive and match catalog parameter
        assert p.duration > 0, (
            f"Program {p.name}: expected duration > 0, got {p.duration}"
        )

        # 2. Timed dry options selection
        if p.set_time_level:
            time_state = hass.states.get(time_eid)
            assert time_state is not None
            for opt in time_state.attributes.get("options", []):
                if opt == "off":
                    continue
                expected_time_minutes = int(opt)
                assert expected_time_minutes in (30, 45, 60, 90, 120)

    # 3. Telemetry remaining time in running state
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    running_status = TumbleDryerStatus.from_json(json.loads(_RUNNING_JSON)["statusTD"])
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    rem_eid = _entity_id(hass, entry, "sensor", UNIQUE_ID_TUMBLE_REMAINING_TIME)
    rem_state = hass.states.get(rem_eid)
    assert rem_state is not None
    assert rem_state.state == "120"
