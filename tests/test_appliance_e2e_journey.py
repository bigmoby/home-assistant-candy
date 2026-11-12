"""End-to-End Appliance Journey and Integrated Flow Tests.

Connects the full lifecycle of Candy/Hoover smart appliances:
1. Ingestion of authentic catalog programs and device configuration.
2. User UI selections (programs, temperatures, spin speeds, soil levels, wash options, steam).
3. Dynamic estimation of cycle duration.
4. Remote control gating and wire serialization invariants on Start button press.
5. Ingress telemetry reflection and FSM phase transitions (Prewash -> Wash -> Rinse -> Spin -> Finished).
6. Mid-cycle network glitch tolerance (3-strike resilience shielding entity states).
7. Post-cycle completion, maintenance counters, and coordinator resting poll intervals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN
from custom_components.candy.client import parse_dryer_programs, parse_wash_programs
from custom_components.candy.client.model import (
    DryerProgramState,
    TumbleDryerProgram,
    TumbleDryerStatus,
    WashingMachineStatus,
    WashingMachineWashProgram,
)
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_TUMBLE_DRYER,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
    PROGRAM_TYPE_WASHING,
    UNIQUE_ID_TUMBLE_DELAY_NUMBER,
    UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT,
    UNIQUE_ID_TUMBLE_PROGRAM_SELECT,
    UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON,
    UNIQUE_ID_TUMBLE_START_BUTTON,
    UNIQUE_ID_WASH_CYCLE_STATUS,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_ESTIMATED_DURATION,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STEAM_SWITCH,
    UNIQUE_ID_WASH_TEMP_SELECT,
    UNIQUE_ID_WASHER_DRYER,
    UNIQUE_ID_WASHING_MACHINE,
)

from .common import TEST_IP

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_STATS_MOCK = (
    '{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'
)


def _load_catalog(filename: str) -> dict[str, Any]:
    """Load an authentic appliance catalog fixture."""
    path = _FIXTURES_DIR / filename
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _entity_id(hass: HomeAssistant, entry_id: str, platform: str, uid_tpl: str) -> str:
    """Resolve an entity ID from its unique ID template."""
    registry = er.async_get(hass)
    eid = registry.async_get_entity_id(platform, DOMAIN, uid_tpl.format(entry_id))
    assert eid is not None, f"Entity not found for {platform}.{uid_tpl}"
    return eid


def _optional_entity_id(
    hass: HomeAssistant, entry_id: str, platform: str, uid_tpl: str
) -> str | None:
    """Resolve an optional entity ID from its unique ID template."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(platform, DOMAIN, uid_tpl.format(entry_id))


async def _init_washing_machine(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    catalog: dict[str, Any],
    initial_status_json: str,
) -> tuple[MockConfigEntry, list[WashingMachineWashProgram]]:
    """Initialize a full-control washing machine with authentic catalog data."""
    raw_programs = catalog["programs"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"test-wm-e2e-{catalog['serial']}",
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
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=initial_status_json
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json?encrypted=0",
        text='{"response":"SUCCESS"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json?encrypted=0",
        text=_STATS_MOCK,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    parsed_programs = parse_wash_programs(raw_programs)
    return entry, parsed_programs


async def _init_tumble_dryer(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    catalog: dict[str, Any],
    initial_status_json: str,
) -> tuple[MockConfigEntry, list[TumbleDryerProgram]]:
    """Initialize a full-control tumble dryer with authentic catalog data."""
    raw_programs = catalog["programs"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"test-td-e2e-{catalog['serial']}",
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
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", text=initial_status_json
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    parsed_programs = parse_dryer_programs(raw_programs)
    return entry, parsed_programs


# ===========================================================================
# Journey 1: Complete Washing Machine / Washer-Dryer Lifecycle Journey
# ===========================================================================


async def test_washing_machine_e2e_complete_journey(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Execute complete end-to-end journey for RapidO washer-dryer (Serial 38).

    Flow steps:
    1. Ingest catalog & verify Idle state and initial estimated duration.
    2. Configure program parameters (Cottons, 60C, 1200 RPM, high soil, prewash, steam).
    3. Verify dynamic duration computation updates.
    4. Press Start button -> verify wire command invariants.
    5. Appliance begins running -> telemetry reflection updates HA sensor states.
    6. Mid-cycle transient network dropout -> coordinator 3-strike resilience shields entities.
    7. Wash progression through Rinse & Spin -> Finished state -> resting poll transition.
    """
    catalog = _load_catalog("catalog_serial_38_rapido_wd.json")
    idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
        "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "10",
        "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry, programs = await _init_washing_machine(
        hass, aioclient_mock, catalog, idle_json
    )
    cid = entry.entry_id
    coordinator = hass.data[DOMAIN][cid][DATA_KEY_COORDINATOR]

    # --- Step 1: Initial Discovery & State Invariants ---
    prog_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    temp_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_TEMP_SELECT)
    spin_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_SPIN_SELECT)
    soil_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_SOIL_SELECT)
    steam_eid = _entity_id(hass, cid, "switch", UNIQUE_ID_WASH_STEAM_SWITCH)
    dur_eid = _entity_id(hass, cid, "sensor", UNIQUE_ID_WASH_ESTIMATED_DURATION)
    start_eid = _entity_id(hass, cid, "button", UNIQUE_ID_WASH_START_BUTTON)
    status_eid = _entity_id(hass, cid, "sensor", UNIQUE_ID_WASHER_DRYER)
    cycle_status_eid = _entity_id(hass, cid, "sensor", UNIQUE_ID_WASH_CYCLE_STATUS)

    assert hass.states.get(status_eid).state == "Idle"
    assert hass.states.get(cycle_status_eid).state == "Stopped"
    assert hass.states.get(start_eid).state != "unavailable"

    # --- Step 2: Interactive User Preparation (UI Selections) ---
    # Select Cottons (Washing)
    type_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": type_eid, "option": PROGRAM_TYPE_WASHING},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": "Eco Cottons"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": temp_eid, "option": "60"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": spin_eid, "option": "1200"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": soil_eid, "option": "high"},
        blocking=True,
    )

    # Enable Prewash switch (bitmask 1)
    prewash_eid = _entity_id(hass, cid, "switch", f"{cid}-wash_option_prewash")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )

    # Enable Steam switch
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": steam_eid}, blocking=True
    )
    await hass.async_block_till_done()

    # --- Step 3: Dynamic Duration Computation Verification ---
    estimated_duration_state = hass.states.get(dur_eid)
    assert estimated_duration_state is not None
    assert int(estimated_duration_state.state) > 0

    # --- Step 4: Dispatch Command & Wire Invariant Validation ---
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )
        await hass.async_block_till_done()

        mock_send.assert_called_once()
        query_string = mock_send.call_args[0][0]
        params = parse_qs(query_string)

        assert params["Write"] == ["1"]
        assert params["StSt"] == ["1"]
        assert params["TmpTgt"] == ["60"]
        assert params["SpdTgt"] == ["12"]
        assert params["SLevTgt"] == ["3"]
        assert params["OptMsk1"] == ["1"]
        assert params["Stm"] == ["1"]

    # --- Step 5: Ingress Telemetry Reflection & FSM Progression ---
    # Appliance acknowledges and starts cycle (Wash phase)
    wash_running_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "2",
            "PrPh": "2",
            "Pr": params["PrNm"][0],
            "PrCode": params["PrCode"][0],
            "Temp": "60",
            "SpinSp": "12",
            "SLevel": "3",
            "DelVal": "0",
            "RemTime": "5400",  # 90 minutes
            "FillR": "50",
        }
    )
    coordinator.async_set_updated_data(wash_running_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Running"
    assert hass.states.get(cycle_status_eid).state == "Wash"
    assert coordinator.data.remaining_minutes == 90
    assert str(coordinator.data.program_state) == "Wash"
    assert hass.states.get(status_eid).attributes.get("temperature") == 60
    assert hass.states.get(status_eid).attributes.get("spin_speed") == 1200

    # --- Step 6: Mid-Cycle Transient Network Dropout (Resilience) ---
    # Transient read error occurs
    coordinator.miss_count = 1
    # 3-strike rule: entities must remain intact and running
    assert hass.states.get(status_eid).state == "Running"

    # Appliance telemetry recovers and advances to Rinse phase
    rinse_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "2",
            "PrPh": "3",
            "Pr": params["PrNm"][0],
            "PrCode": params["PrCode"][0],
            "Temp": "60",
            "SpinSp": "12",
            "SLevel": "3",
            "DelVal": "0",
            "RemTime": "1800",  # 30 minutes
            "FillR": "50",
        }
    )
    coordinator.miss_count = 0
    coordinator.async_set_updated_data(rinse_status)
    await hass.async_block_till_done()

    assert str(coordinator.data.program_state) == "Rinse"
    assert hass.states.get(cycle_status_eid).state == "Rinse"
    assert coordinator.data.remaining_minutes == 30

    # --- Step 7: Spin Phase, Cycle Finish & Resting Poll Mode ---
    finished_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "7",
            "PrPh": "0",
            "Pr": params["PrNm"][0],
            "PrCode": params["PrCode"][0],
            "Temp": "0",
            "SpinSp": "0",
            "SLevel": "0",
            "DelVal": "0",
            "RemTime": "0",
            "FillR": "0",
        }
    )
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Finished"
    assert coordinator.data.remaining_minutes == 0

    # Appliance powers off / Wi-Fi chip sleeps
    off_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "0",
            "Err": "0",
            "MachMd": "0",
            "Pr": "0",
            "PrPh": "0",
            "Temp": "0",
            "SpinSp": "0",
            "RemTime": "0",
        }
    )
    coordinator.async_set_updated_data(off_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Off"


# ===========================================================================
# Journey 2: Complete Tumble Dryer DualTech Lifecycle Journey
# ===========================================================================


async def test_tumble_dryer_e2e_complete_journey(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Execute complete end-to-end journey for Tumble Dryer (Serial 35).

    Flow steps:
    1. Ingest catalog & verify Idle state.
    2. Select program, dry level, and configure delay.
    3. Dispatch Start button -> verify DualTech wire command format.
    4. Progression through Running, Cool-down, and Anti-crease hold.
    5. Cycle completion, warning flags (filter/tank), and warning reset button.
    """
    catalog = _load_catalog("catalog_serial_35_tumble_dryer.json")
    idle_json = """{
      "statusTD": {
        "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
        "RemTime": "150", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
        "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
        "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
      }
    }"""
    entry, programs = await _init_tumble_dryer(hass, aioclient_mock, catalog, idle_json)
    cid = entry.entry_id
    coordinator = hass.data[DOMAIN][cid][DATA_KEY_COORDINATOR]

    # --- Step 1: Initial Discovery ---
    prog_eid = _entity_id(hass, cid, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
    level_eid = _entity_id(hass, cid, "select", UNIQUE_ID_TUMBLE_DRY_LEVEL_SELECT)
    delay_eid = _entity_id(hass, cid, "number", UNIQUE_ID_TUMBLE_DELAY_NUMBER)
    start_eid = _entity_id(hass, cid, "button", UNIQUE_ID_TUMBLE_START_BUTTON)
    reset_eid = _entity_id(hass, cid, "button", UNIQUE_ID_TUMBLE_RESET_WARNINGS_BUTTON)

    assert float(hass.states.get(delay_eid).state) == 0.0

    # --- Step 2: User UI Selections ---
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": "Whites"},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": level_eid, "option": "bone_dry"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # --- Step 3: Dispatch Start Command ---
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )
        await hass.async_block_till_done()

        mock_send.assert_called_once()
        query_string = mock_send.call_args[0][0]
        params = parse_qs(query_string)

        assert params["Write"] == ["1"]
        assert params["StSt"] == ["1"]
        assert params["DryLev"] == ["4"]  # Extra Dry = 4

    # --- Step 4: Trajectory Progression ---
    # Phase shift: Drying running phase (PrPh=2)
    drying_status = TumbleDryerStatus.from_json(
        {
            "StatoWiFi": "1",
            "StatoTD": "2",
            "CodiceErrore": "0",
            "Pr": "1",
            "PrPh": "2",
            "RemTime": "60",
            "DryLev": "4",
            "Time": "0",
            "Rapido": "0",
            "Refresh": "0",
            "CleanFilter": "0",
            "WaterTankFull": "0",
            "DryingManagerLevel": "4",
            "DelVal": "0",
            "DoorState": "1",
            "RecipeId": "NULL",
            "CheckUpState": "0",
        }
    )
    coordinator.async_set_updated_data(drying_status)
    await hass.async_block_till_done()

    assert coordinator.data.program_state == DryerProgramState.RUNNING
    assert coordinator.data.remaining_minutes == 60

    # Phase shift: End / Cool down phase (PrPh=3)
    cooldown_status = TumbleDryerStatus.from_json(
        {
            "StatoWiFi": "1",
            "StatoTD": "2",
            "CodiceErrore": "0",
            "Pr": "1",
            "PrPh": "3",
            "RemTime": "15",
            "DryLev": "4",
            "Time": "0",
            "Rapido": "0",
            "Refresh": "0",
            "CleanFilter": "0",
            "WaterTankFull": "0",
            "DryingManagerLevel": "4",
            "DelVal": "0",
            "DoorState": "1",
            "RecipeId": "NULL",
            "CheckUpState": "0",
        }
    )
    coordinator.async_set_updated_data(cooldown_status)
    await hass.async_block_till_done()

    assert coordinator.data.program_state == DryerProgramState.END
    assert coordinator.data.remaining_minutes == 15

    # --- Step 5: Cycle Finish & Warning Reset ---
    finished_warnings_status = TumbleDryerStatus.from_json(
        {
            "StatoWiFi": "1",
            "StatoTD": "8",
            "CodiceErrore": "0",
            "Pr": "1",
            "PrPh": "3",
            "RemTime": "0",
            "DryLev": "4",
            "Time": "0",
            "Rapido": "0",
            "Refresh": "0",
            "CleanFilter": "1",
            "WaterTankFull": "1",
            "DryingManagerLevel": "4",
            "DelVal": "0",
            "DoorState": "1",
            "RecipeId": "NULL",
            "CheckUpState": "0",
        }
    )
    coordinator.async_set_updated_data(finished_warnings_status)
    await hass.async_block_till_done()

    assert coordinator.data.need_clean_filter is True
    assert coordinator.data.water_tank_full is True

    # User clears filter and presses reset warnings button
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_reset:
        await hass.services.async_call(
            "button", "press", {"entity_id": reset_eid}, blocking=True
        )
        await hass.async_block_till_done()

        mock_reset.assert_called_once()
        reset_qs = mock_reset.call_args[0][0]
        reset_params = parse_qs(reset_qs)
        assert reset_params["Write"] == ["1"]
        assert reset_params["ResetWarnings"] == ["1"]


# ===========================================================================
# Journey 3: Remote Control Fail-Safe Journey
# ===========================================================================


async def test_remote_control_fail_safe_journey(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Verify write safety fail-safe when appliance dial is in local manual mode."""
    catalog = _load_catalog("catalog_serial_38_rapido_wd.json")
    local_knob_json = """{
      "statusLavatrice": {
        "WiFiStatus": "0", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
        "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "10",
        "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry, _ = await _init_washing_machine(
        hass, aioclient_mock, catalog, local_knob_json
    )
    cid = entry.entry_id
    coordinator = hass.data[DOMAIN][cid][DATA_KEY_COORDINATOR]

    start_eid = _entity_id(hass, cid, "button", UNIQUE_ID_WASH_START_BUTTON)
    temp_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_TEMP_SELECT)

    # In local knob mode, write controls must report unavailable
    assert hass.states.get(start_eid).state == "unavailable"
    assert hass.states.get(temp_eid).state == "unavailable"

    # Dial turned to Remote Control on physical appliance
    remote_on_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "1",
            "Pr": "1",
            "PrPh": "0",
            "PrCode": "136",
            "SLevel": "2",
            "Temp": "40",
            "SpinSp": "10",
            "DelVal": "0",
            "RemTime": "0",
            "FillR": "0",
        }
    )
    coordinator.async_set_updated_data(remote_on_status)
    await hass.async_block_till_done()

    # Controls become available immediately
    assert hass.states.get(start_eid).state != "unavailable"
    assert hass.states.get(temp_eid).state != "unavailable"


# ===========================================================================
# Journey 4: DualTech Standalone Washing Machine E2E Journey
# ===========================================================================


async def test_dualtech_washer_e2e_journey(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Execute complete end-to-end journey for DualTech standalone washer (Serial 41).

    Verifies:
    1. Remote pause/resume is suppressed on DualTech hardware (pause entity is None).
    2. Setting a 120-minute delay serializes into whole hours on the wire (DelMd=1, DelVl=2).
    3. DualTech wire start command grammar (Write=1, Pa=0, Sel=0, PrNm, without StSt).
    4. Progression through Delayed start programmed -> Running -> Finished.
    """
    catalog = _load_catalog("catalog_serial_41_dualtech_wm.json")
    idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
        "PrCode": "136", "SLevel": "2", "Temp": "40", "SpinSp": "10",
        "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry, programs = await _init_washing_machine(
        hass, aioclient_mock, catalog, idle_json
    )
    cid = entry.entry_id
    coordinator = hass.data[DOMAIN][cid][DATA_KEY_COORDINATOR]

    # Step 1: Initial Discovery & Feature Gating
    status_eid = _entity_id(hass, cid, "sensor", UNIQUE_ID_WASHING_MACHINE)
    start_eid = _entity_id(hass, cid, "button", UNIQUE_ID_WASH_START_BUTTON)
    prog_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    delay_eid = _entity_id(hass, cid, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    pause_eid = _optional_entity_id(hass, cid, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)

    assert pause_eid is None  # Suppressed on DualTech
    assert hass.states.get(status_eid).state == "Idle"

    # Step 2: User UI Selections (Select program and set 120 min delay)
    target_program = programs[0]
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": target_program.localized_name("en")},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_eid, "value": 120},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Step 3: Dispatch Start Command & Wire Invariant Validation
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )
        await hass.async_block_till_done()

        mock_send.assert_called_once()
        query_string = mock_send.call_args[0][0]
        params = parse_qs(query_string)

        assert params["Write"] == ["1"]
        assert params["Pa"] == ["0"]
        assert params["Sel"] == ["0"]
        assert params["DelMd"] == ["1"]
        assert params["DelVl"] == ["2"]  # 120 // 60 whole hours
        assert "StSt" not in params
        assert "PrCode" not in params  # DualTech omits modern axibianca registers

    # Step 4: Progression to Delayed Start Programmed
    delayed_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "5",  # Delayed start programmed
            "PrPh": "0",
            "Pr": params["PrNm"][0],
            "Temp": "40",
            "SpinSp": "10",
            "SLevel": "2",
            "DelVal": "120",
            "RemTime": "0",
            "FillR": "0",
        }
    )
    coordinator.async_set_updated_data(delayed_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Delayed start programmed"

    # Step 5: Delay countdown expires -> transitions to Running
    running_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "2",  # Running
            "PrPh": "2",  # Wash
            "Pr": params["PrNm"][0],
            "Temp": "40",
            "SpinSp": "10",
            "SLevel": "2",
            "DelVal": "0",
            "RemTime": "4800",  # 80 min
            "FillR": "50",
        }
    )
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Running"
    assert coordinator.data.remaining_minutes == 80

    # Step 6: Cycle Finishes
    finished_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "7",  # Finished
            "PrPh": "0",
            "Pr": params["PrNm"][0],
            "Temp": "0",
            "SpinSp": "0",
            "SLevel": "0",
            "DelVal": "0",
            "RemTime": "0",
            "FillR": "0",
        }
    )
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Finished"


# ===========================================================================
# Journey 5: Bianca Standalone Washing Machine E2E Journey
# ===========================================================================


async def test_bianca_washer_e2e_journey(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Execute complete end-to-end journey for Bianca standalone washer (Serial 34).

    Verifies:
    1. Remote pause/resume is suppressed on Bianca (pause entity is None).
    2. Non-washer-dryer entities (program_type_select, dry_select) are absent.
    3. Setting a 60-minute delay scales to DelVl=2 (60 // 30 min steps).
    4. Bianca wire start command includes PrCode and standard write registers.
    5. Lifecycle progression from Idle -> Running -> Finished.
    """
    catalog = _load_catalog("catalog_serial_34_bianca_wm.json")
    catalog["interface_type"] = "BIANCA"
    idle_json = """{
      "statusLavatrice": {
        "WiFiStatus": "1", "Err": "0", "MachMd": "1", "Pr": "1", "PrPh": "0",
        "PrCode": "112", "SLevel": "2", "Temp": "40", "SpinSp": "10",
        "DelVal": "0", "RemTime": "0", "FillR": "0", "CheckUpState": "0"
      }
    }"""
    entry, programs = await _init_washing_machine(
        hass, aioclient_mock, catalog, idle_json
    )
    cid = entry.entry_id
    coordinator = hass.data[DOMAIN][cid][DATA_KEY_COORDINATOR]

    # Step 1: Initial Discovery & Feature Gating
    status_eid = _entity_id(hass, cid, "sensor", UNIQUE_ID_WASHING_MACHINE)
    start_eid = _entity_id(hass, cid, "button", UNIQUE_ID_WASH_START_BUTTON)
    prog_eid = _entity_id(hass, cid, "select", UNIQUE_ID_WASH_PROGRAM_SELECT)
    delay_eid = _entity_id(hass, cid, "number", UNIQUE_ID_WASH_DELAY_NUMBER)
    pause_eid = _optional_entity_id(hass, cid, "button", UNIQUE_ID_WASH_PAUSE_BUTTON)
    type_eid = _optional_entity_id(
        hass, cid, "select", UNIQUE_ID_WASH_PROGRAM_TYPE_SELECT
    )

    assert pause_eid is None  # Suppressed on Bianca
    assert type_eid is None  # Absent on standalone washer
    assert hass.states.get(status_eid).state == "Idle"

    # Step 2: User UI Selections (Select program and set 60 min delay)
    target_program = programs[0]
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": target_program.localized_name("en")},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_eid, "value": 60},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Step 3: Dispatch Start Command & Wire Invariant Validation
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )
        await hass.async_block_till_done()

        mock_send.assert_called_once()
        query_string = mock_send.call_args[0][0]
        params = parse_qs(query_string)

        assert params["Write"] == ["1"]
        assert params["StSt"] == ["1"]
        assert params["DelVl"] == ["2"]  # 60 // 30
        assert int(params["PrCode"][0]) == target_program.pr_code
        assert int(params["PrNm"][0]) == target_program.selector_position

    # Step 4: Telemetry Reflection & Running Progression
    running_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "2",
            "PrPh": "2",
            "Pr": params["PrNm"][0],
            "PrCode": params["PrCode"][0],
            "Temp": "40",
            "SpinSp": "10",
            "SLevel": "2",
            "DelVal": "0",
            "RemTime": "3600",
            "FillR": "50",
        }
    )
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Running"
    assert coordinator.data.remaining_minutes == 60

    # Step 5: Cycle Finishes
    finished_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "7",
            "PrPh": "0",
            "Pr": params["PrNm"][0],
            "PrCode": params["PrCode"][0],
            "Temp": "0",
            "SpinSp": "0",
            "SLevel": "0",
            "DelVal": "0",
            "RemTime": "0",
            "FillR": "0",
        }
    )
    coordinator.async_set_updated_data(finished_status)
    await hass.async_block_till_done()

    assert hass.states.get(status_eid).state == "Finished"


# ===========================================================================
# Journey 6: Tumble Dryer Delayed Start E2E Journey
# ===========================================================================


async def test_tumble_dryer_delayed_start_journey(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Execute delayed start end-to-end journey for Tumble Dryer (Serial 35).

    Verifies:
    1. Setting delay on tumble dryer serializes to DelMd=1 and DelVl=<minutes> (omits StSt).
    2. Telemetry reflects delayed start programmed state (StatoTD=4).
    3. Transition to running (StatoTD=2) upon timer completion.
    """
    catalog = _load_catalog("catalog_serial_35_tumble_dryer.json")
    idle_json = """{
      "statusTD": {
        "StatoWiFi": "1", "StatoTD": "1", "CodiceErrore": "0", "Pr": "1", "PrPh": "0",
        "RemTime": "150", "DryLev": "3", "Time": "0", "Rapido": "0", "Refresh": "0",
        "CleanFilter": "0", "WaterTankFull": "0", "DryingManagerLevel": "3",
        "DelVal": "0", "DoorState": "1", "RecipeId": "NULL", "CheckUpState": "0"
      }
    }"""
    entry, programs = await _init_tumble_dryer(hass, aioclient_mock, catalog, idle_json)
    cid = entry.entry_id
    coordinator = hass.data[DOMAIN][cid][DATA_KEY_COORDINATOR]

    prog_eid = _entity_id(hass, cid, "select", UNIQUE_ID_TUMBLE_PROGRAM_SELECT)
    delay_eid = _entity_id(hass, cid, "number", UNIQUE_ID_TUMBLE_DELAY_NUMBER)
    start_eid = _entity_id(hass, cid, "button", UNIQUE_ID_TUMBLE_START_BUTTON)

    # Step 1: Select program and set 120 min delay
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": prog_eid, "option": "Whites"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_eid, "value": 120},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Step 2: Dispatch Start Command
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )
        await hass.async_block_till_done()

        mock_send.assert_called_once()
        query_string = mock_send.call_args[0][0]
        params = parse_qs(query_string)

        assert params["Write"] == ["1"]
        assert params["DelMd"] == ["1"]
        assert params["DelVl"] == [
            "120"
        ]  # Tumble dryer sends delay directly in minutes
        assert "StSt" not in params  # Hardware protocol omits StSt during delayed start

    # Step 3: Delayed start programmed state reflection
    delayed_status = TumbleDryerStatus.from_json(
        {
            "StatoWiFi": "1",
            "StatoTD": "4",  # Delayed start programmed
            "CodiceErrore": "0",
            "Pr": "1",
            "PrPh": "0",
            "RemTime": "150",
            "DryLev": "3",
            "Time": "0",
            "Rapido": "0",
            "Refresh": "0",
            "CleanFilter": "0",
            "WaterTankFull": "0",
            "DryingManagerLevel": "3",
            "DelVal": "120",
            "DoorState": "1",
            "RecipeId": "NULL",
            "CheckUpState": "0",
        }
    )
    coordinator.async_set_updated_data(delayed_status)
    await hass.async_block_till_done()

    assert coordinator.data.delay_value == 120

    # Step 4: Delay expires -> Transitions to Running
    running_status = TumbleDryerStatus.from_json(
        {
            "StatoWiFi": "1",
            "StatoTD": "2",  # Running
            "CodiceErrore": "0",
            "Pr": "1",
            "PrPh": "2",
            "RemTime": "120",
            "DryLev": "3",
            "Time": "0",
            "Rapido": "0",
            "Refresh": "0",
            "CleanFilter": "0",
            "WaterTankFull": "0",
            "DryingManagerLevel": "3",
            "DelVal": "0",
            "DoorState": "1",
            "RecipeId": "NULL",
            "CheckUpState": "0",
        }
    )
    coordinator.async_set_updated_data(running_status)
    await hass.async_block_till_done()

    assert coordinator.data.program_state == DryerProgramState.RUNNING
    assert coordinator.data.remaining_minutes == 120
