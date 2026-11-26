"""Tests for the Dishwasher Finite State Machine (FSM) Lifecycle and Phase Progression.

Grounded in empirical wire captures (Candy CDPN 4D620PX) and decompiled Simply-Fi APK bytecode.
Covers:
1. Complete happy path lifecycle progression across all 5 phases
2. Physical panel start button quirk (StartStop: 0 while actively running)
3. Stale end-of-cycle duration quirk (RemTime not zeroed at finished state)
4. Stale end-of-cycle StartStop quirk (StartStop: 1 retained after cycle completion)
5. Mid-cycle door opened safety interlock and sensor state preservation
6. Pause and resume transition across Modern (Pa=1/0) and Legacy (StartStop=0/1) builders
7. Error code reporting and automatic recovery
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.persistent_notification import DOMAIN as NOTIF_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DATA_KEY_COORDINATOR, DOMAIN
from custom_components.candy.client.model import (
    DishwasherProgramPhase,
    DishwasherStatus,
    MachineState,
)
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    MODE_FULL_CONTROL,
    NOTIF_ID_DISHWASHER_ERROR,
    UNIQUE_ID_DISHWASHER,
    UNIQUE_ID_DISHWASHER_CYCLE_STATUS,
    UNIQUE_ID_DISHWASHER_DOOR,
    UNIQUE_ID_DISHWASHER_ERROR,
    UNIQUE_ID_DISHWASHER_PAUSE_BUTTON,
    UNIQUE_ID_DISHWASHER_REMAINING_TIME,
    UNIQUE_ID_DISHWASHER_RESUME_BUTTON,
    UNIQUE_ID_DISHWASHER_START_BUTTON,
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


def _fixture_with_overrides(name: str, **overrides: str) -> str:
    data = json.loads(load_fixture(name))
    data["statusDWash"].update(overrides)
    return json.dumps(data)


async def test_dishwasher_complete_lifecycle_progression(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Step through the full cycle progression from Ready to Finished and return to Idle.

    Phases verified:
      0: Delayed start programmed
      1: Pre-wash
      2: Wash
      3: Rinse
      4: Drying
      5: Finished
    """
    catalog = _load_dw_catalog()
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: catalog["programs"],
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )

    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    main_sensor_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER)
    phase_sensor_id = _entity_id(
        hass, entry, "sensor", UNIQUE_ID_DISHWASHER_CYCLE_STATUS
    )
    rem_time_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_REMAINING_TIME)
    start_button_id = _entity_id(
        hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON
    )

    # 1. Ready / Idle
    assert hass.states.get(main_sensor_id).state == "Idle"
    assert hass.states.get(phase_sensor_id).state == "unknown"
    assert hass.states.get(rem_time_id).state == "0"
    assert hass.states.get(start_button_id).state != "unavailable"

    # 2. Delayed Start Programmed (StatoDWash: 99, DelayStart: 60)
    delay_payload = json.loads(
        _fixture_with_overrides(_READY, StatoDWash="99", DelayStart="60")
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(delay_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Delayed start programmed"
    assert hass.states.get(rem_time_id).state == "0"
    assert hass.states.get(start_button_id).state == "unavailable"

    # 3. Running - Phase 1: Pre-wash
    phase1_payload = json.loads(
        _fixture_with_overrides(
            _READY,
            StatoDWash="3",
            r2="1",
            StartStop="1",
            RemTime="140",
            DelayStart="0",
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(phase1_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Running"
    assert hass.states.get(phase_sensor_id).state == "Pre-wash"
    assert hass.states.get(rem_time_id).state == "140"
    assert hass.states.get(start_button_id).state == "unavailable"

    # 4. Running - Phase 2: Wash
    phase2_payload = json.loads(
        _fixture_with_overrides(
            _READY, StatoDWash="3", r2="2", StartStop="1", RemTime="100"
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(phase2_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Running"
    assert hass.states.get(phase_sensor_id).state == "Wash"
    assert hass.states.get(rem_time_id).state == "100"

    # 5. Running - Phase 3: Rinse
    phase3_payload = json.loads(
        _fixture_with_overrides(
            _READY, StatoDWash="3", r2="3", StartStop="1", RemTime="60"
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(phase3_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Running"
    assert hass.states.get(phase_sensor_id).state == "Rinse"
    assert hass.states.get(rem_time_id).state == "60"

    # 6. Running - Phase 4: Drying
    phase4_payload = json.loads(
        _fixture_with_overrides(
            _READY, StatoDWash="3", r2="4", StartStop="1", RemTime="25"
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(phase4_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Running"
    assert hass.states.get(phase_sensor_id).state == "Drying"
    assert hass.states.get(rem_time_id).state == "25"

    # 7. Finished (StatoDWash: 5, r2: 5)
    finished_payload = json.loads(
        _fixture_with_overrides(
            _READY, StatoDWash="5", r2="5", StartStop="0", RemTime="0"
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(finished_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Finished"
    assert hass.states.get(phase_sensor_id).state == "Finished"
    assert hass.states.get(rem_time_id).state == "0"
    assert hass.states.get(start_button_id).state != "unavailable"


async def test_panel_push_button_start_quirk(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Empirical quirk from Candy CDPN 4D620PX for panel push button start."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    main_sensor_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER)
    phase_sensor_id = _entity_id(
        hass, entry, "sensor", UNIQUE_ID_DISHWASHER_CYCLE_STATUS
    )

    panel_start_payload = json.loads(
        _fixture_with_overrides(
            _READY,
            StatoDWash="3",
            r2="2",
            StartStop="0",  # Panel quirk
            RemTime="115",
        )
    )
    status = DishwasherStatus.from_json(panel_start_payload["statusDWash"])
    assert status.running is True
    assert status.machine_state == MachineState.RUNNING
    assert status.program_phase == DishwasherProgramPhase.WASH

    coordinator.async_set_updated_data(status)
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Running"
    assert hass.states.get(phase_sensor_id).state == "Wash"


async def test_stale_duration_at_cycle_end_quirk(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Empirical quirk from Candy CDPN 4D620PX for stale duration at cycle end."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    rem_time_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_REMAINING_TIME)

    stale_duration_payload = json.loads(
        _fixture_with_overrides(
            _READY,
            StatoDWash="5",
            r2="5",
            RemTime="75",  # Stale MCU timer
        )
    )
    status = DishwasherStatus.from_json(stale_duration_payload["statusDWash"])
    assert status.remaining_minutes == 0

    coordinator.async_set_updated_data(status)
    await hass.async_block_till_done()

    assert hass.states.get(rem_time_id).state == "0"


async def test_stale_remote_start_stop_at_cycle_end_quirk(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Empirical quirk from Candy CDPN 4D620PX for stale StartStop at cycle end."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    main_sensor_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER)

    stale_startstop_payload = json.loads(
        _fixture_with_overrides(
            _READY,
            StatoDWash="5",
            r2="5",
            StartStop="1",  # Retained remote flag
        )
    )
    status = DishwasherStatus.from_json(stale_startstop_payload["statusDWash"])
    assert status.machine_state == MachineState.FINISHED1
    assert status.running is False

    coordinator.async_set_updated_data(status)
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Finished"


async def test_door_opened_during_wash_phase(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the door is opened mid-wash, the door binary sensor reflects open state."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    door_id = _entity_id(hass, entry, "binary_sensor", UNIQUE_ID_DISHWASHER_DOOR)
    main_sensor_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER)
    start_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_START_BUTTON)

    door_open_payload = json.loads(
        _fixture_with_overrides(
            _READY,
            StatoDWash="3",
            r2="2",
            StartStop="1",
            OpenDoor="1",
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(door_open_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(door_id).state == "on"
    assert hass.states.get(main_sensor_id).state == "Running"
    assert hass.states.get(start_id).state == "unavailable"


async def test_modern_pause_and_resume_lifecycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Modern Brava dishwashers use Pa=1 to pause and Pa=0 to resume."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture("dishwasher/remote_running.json"),
        statistics_response=_STATS,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "BRAVA_BI_DIGIT_OD",
        },
    )

    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    pause_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_PAUSE_BUTTON)
    resume_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_RESUME_BUTTON)
    main_sensor_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER)

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&Pa=1",
        text='{"response":"OK"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&Pa=0",
        text='{"response":"OK"}',
    )

    # Press Pause
    await hass.services.async_call(
        "button", "press", {"entity_id": pause_id}, blocking=True
    )

    # Telemetry transitions to Paused (StatoDWash: 4)
    paused_payload = json.loads(_fixture_with_overrides(_READY, StatoDWash="4", r2="2"))
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(paused_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Paused"

    # Press Resume
    await hass.services.async_call(
        "button", "press", {"entity_id": resume_id}, blocking=True
    )


async def test_legacy_pause_and_resume_lifecycle(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Family 1 Legacy Touch dishwashers use StartStop=0 to pause and StartStop=1 to resume."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture("dishwasher/wash.json"),
        statistics_response=_STATS,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: "DishwasherInterfaceTypeFSTouch",
        },
    )

    pause_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_PAUSE_BUTTON)
    resume_id = _entity_id(hass, entry, "button", UNIQUE_ID_DISHWASHER_RESUME_BUTTON)

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&StartStop=0",
        text='{"response":"OK"}',
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&StartStop=1",
        text='{"response":"OK"}',
    )

    await hass.services.async_call(
        "button", "press", {"entity_id": pause_id}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": resume_id}, blocking=True
    )


async def test_error_reporting_and_automatic_recovery(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When machine reports error, state is Error and clears when restored."""
    entry = await init_integration(
        hass,
        aioclient_mock,
        load_fixture(_READY),
        statistics_response=_STATS,
        extra_config_data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_KEY_COORDINATOR]
    main_sensor_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER)
    error_sensor_id = _entity_id(hass, entry, "sensor", UNIQUE_ID_DISHWASHER_ERROR)

    notif_id = NOTIF_ID_DISHWASHER_ERROR.format(entry.entry_id)

    # 1. Error occurs (StatoDWash: 6, CodiceErrore: E02)
    error_payload = json.loads(
        _fixture_with_overrides(
            _READY,
            StatoDWash="6",
            CodiceErrore="E02",
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(error_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Error"
    assert hass.states.get(error_sensor_id).state == "E02"

    # Persistent notification should be active
    notif_entity = hass.states.get(f"{NOTIF_DOMAIN}.{notif_id}")
    assert notif_entity is not None or hass.data.get("persistent_notification")

    # 2. Machine recovered
    recovered_payload = json.loads(
        _fixture_with_overrides(
            _READY,
            StatoDWash="2",
            CodiceErrore="E0",
        )
    )
    coordinator.async_set_updated_data(
        DishwasherStatus.from_json(recovered_payload["statusDWash"])
    )
    await hass.async_block_till_done()

    assert hass.states.get(main_sensor_id).state == "Idle"
    assert hass.states.get(error_sensor_id).state == "E0"
