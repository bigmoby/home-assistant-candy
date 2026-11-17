"""Unit tests for custom_components.candy.switch to achieve 100% coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy.client import (
    CandyClient,
    WashingMachineStatus,
    parse_wash_programs,
)
from custom_components.candy.client.model import (
    DryerCycleState,
    DryerProgramState,
    MachineState,
    TumbleDryerStatus,
    WashProgramState,
)
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DOMAIN,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    UNIQUE_ID_WASH_DETERGENT_AUTODOSE,
    UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH,
    UNIQUE_ID_WASH_NFC_SWITCH,
    UNIQUE_ID_WASH_OPTION_PREWASH,
    UNIQUE_ID_WASH_PROGRAM_SELECT,
    UNIQUE_ID_WASH_SOFTENER_AUTODOSE,
    UNIQUE_ID_WASH_STEAM_SWITCH,
)
from custom_components.candy.coordinator import CandyDataUpdateCoordinator
from custom_components.candy.switch import (
    NfcSpecialProgramsSwitch,
    WashDetergentAutoDoseSwitch,
    WashExtraDoseSwitch,
    WashOptionSwitch,
    WashSoftenerAutoDoseSwitch,
    WashSteamSwitch,
    _WashSwitchBase,
    async_setup_entry,
)

_SAMPLE_PROGRAM = {
    "program": {
        "position": 1,
        "name": "COTTON",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "pr_code", "validation": "100"}},
            {"command_parameter": {"name": "steam", "validation": "1"}},
            {
                "command_parameter": {"name": "available_options", "validation": "1"}
            },  # bit 1
        ],
    }
}

_NO_STEAM_PROGRAM = {
    "program": {
        "position": 2,
        "name": "ECO",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "2"}},
            {"command_parameter": {"name": "pr_code", "validation": "101"}},
            {"command_parameter": {"name": "steam", "validation": "0"}},
            {"command_parameter": {"name": "options", "validation": "0"}},
        ],
    }
}

_BASE_WM_STATUS = WashingMachineStatus(
    machine_state=MachineState.IDLE,
    program_state=WashProgramState.STOPPED,
    program=1,
    program_code=100,
    temp=40,
    spin_speed=1000,
    remaining_minutes=60,
    remote_control=True,
    fill_percent=None,
    error=None,
    delay_value=None,
    ntc_water=None,
    ntc_drum=None,
    motor_speed_freq=None,
    motor_state=None,
    unbalance_fault=None,
    unbalance_count=None,
    fault_count=None,
    dis_test_res=None,
    checkup_state=None,
    soil_level=None,
    recipe_id=None,
    dry_target=None,
    detergent_on=0,
    softener_on=0,
    detergent_empty=None,
    softener_empty=None,
    detergent_reserve=None,
    softener_reserve=None,
    detergent_cycles_remaining=None,
    softener_cycles_remaining=None,
    water_hardness=None,
    extra_dose_active=None,
)

_BASE_TD_STATUS = TumbleDryerStatus(
    machine_state=MachineState.IDLE,
    program_state=DryerProgramState.STOPPED,
    cycle_state=DryerCycleState.LEVEL_NONE,
    program=0,
    remaining_minutes=0,
    remote_control=False,
    dry_level=0,
    dry_level_selected=0,
    refresh=False,
    need_clean_filter=False,
    water_tank_full=False,
    door_closed=True,
    error=None,
    delay_value=None,
    checkup_state=None,
    recipe_id=None,
    time=None,
    rapido=None,
)


@pytest.fixture
def mock_client() -> CandyClient:
    client = MagicMock(spec=CandyClient)
    client.set_autodose = AsyncMock()
    return client


async def test_async_setup_entry_not_full_control(hass: HomeAssistant) -> None:
    """Setup returns early when mode is not MODE_FULL_CONTROL."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_entry_ro",
        data={CONF_KEY_MODE: MODE_READ_ONLY},
    )
    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_not_called()


async def test_async_setup_entry_not_washing_machine(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Setup returns early when coordinator data is not WashingMachineStatus."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_entry_dryer",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.data = _BASE_TD_STATUS
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_KEY_COORDINATOR: coord,
        DATA_KEY_CLIENT: mock_client,
    }
    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_not_called()


async def test_async_setup_entry_without_steam_and_no_options(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Setup omits WashSteamSwitch and WashOptionSwitch when no programs support them."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_entry_no_steam",
        data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: [_NO_STEAM_PROGRAM],
            CONF_KEY_INTERFACE_TYPE: "STANDALONE",
        },
    )
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.data = _BASE_WM_STATUS
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_KEY_COORDINATOR: coord,
        DATA_KEY_CLIENT: mock_client,
    }

    added_entities: list = []

    def _add(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, _add)

    assert len(added_entities) == 1
    assert isinstance(added_entities[0], NfcSpecialProgramsSwitch)


async def test_wash_switch_base_event_listener_and_program_resolution(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test _WashSwitchBase state change listener branches and _active_program resolution."""
    programs = parse_wash_programs([_SAMPLE_PROGRAM, _NO_STEAM_PROGRAM])
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="test_switch_base",
        data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    entry.add_to_hass(hass)
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(_BASE_WM_STATUS, program=1, program_code=100)

    switch = _WashSwitchBase(coord, entry, mock_client, programs)
    switch.hass = hass
    switch.entity_id = "switch.candy_test"

    await switch.async_added_to_hass()

    registry = er.async_get(hass)

    # 1. Event on an entity that does not start with 'select.' (line 126)
    hass.bus.async_fire(
        EVENT_STATE_CHANGED,
        {"entity_id": "sensor.washer_status", "old_state": None, "new_state": None},
    )
    await hass.async_block_till_done()

    # 2. Event on a select entity not in the registry (line 128)
    hass.bus.async_fire(
        EVENT_STATE_CHANGED,
        {"entity_id": "select.unknown_entity", "old_state": None, "new_state": None},
    )
    await hass.async_block_till_done()

    # 3. Event on a select entity belonging to a different config entry (line 128)
    other_mock_entry = MockConfigEntry(domain="other", entry_id="other_id")
    other_mock_entry.add_to_hass(hass)
    other_entry = registry.async_get_or_create(
        "select",
        "other_domain",
        "other_uid",
        config_entry=other_mock_entry,
    )
    hass.bus.async_fire(
        EVENT_STATE_CHANGED,
        {"entity_id": other_entry.entity_id, "old_state": None, "new_state": None},
    )
    await hass.async_block_till_done()

    # 4. Event on a select entity belonging to this entry but different unique ID (line 129)
    diff_uid_entry = registry.async_get_or_create(
        "select", DOMAIN, f"{entry.entry_id}_diff", config_entry=entry
    )
    hass.bus.async_fire(
        EVENT_STATE_CHANGED,
        {"entity_id": diff_uid_entry.entity_id, "old_state": None, "new_state": None},
    )
    await hass.async_block_till_done()

    # 5. Event matching target UNIQUE_ID_WASH_PROGRAM_SELECT (line 130)
    prog_entry = registry.async_get_or_create(
        "select",
        DOMAIN,
        UNIQUE_ID_WASH_PROGRAM_SELECT.format(entry.entry_id),
        config_entry=entry,
    )

    with patch.object(switch, "async_write_ha_state") as mock_write:
        hass.bus.async_fire(
            EVENT_STATE_CHANGED,
            {"entity_id": prog_entry.entity_id, "old_state": None, "new_state": None},
        )
        await hass.async_block_till_done()
        mock_write.assert_called_once()

    # Test _active_program when HA select state is unavailable/unknown -> fallback to coordinator
    hass.states.async_set(prog_entry.entity_id, "unavailable")
    assert switch._active_program() == programs[0]

    hass.states.async_set(prog_entry.entity_id, "unknown")
    assert switch._active_program() == programs[0]

    # When HA select state is a valid program name
    hass.states.async_set(prog_entry.entity_id, "Cotton")
    assert switch._active_program() == programs[0]

    # When HA select state is a string not matching any program -> returns None
    hass.states.async_set(prog_entry.entity_id, "NonExistentProgram")
    assert switch._active_program() is None

    # Remove prog_entry from registry to test coordinator fallback when entity_id is None
    registry.async_remove(prog_entry.entity_id)

    # Coordinator matching selector_position and program_code
    coord.data = replace(_BASE_WM_STATUS, program=1, program_code=100)
    assert switch._active_program() == programs[0]

    # Coordinator matching selector_position only (program_code is None)
    coord.data = replace(_BASE_WM_STATUS, program=2, program_code=None)
    assert switch._active_program() == programs[1]

    # Coordinator program not matching any selector_position (line 180: return None)
    coord.data = replace(_BASE_WM_STATUS, program=99, program_code=None)
    assert switch._active_program() is None


async def test_wash_steam_switch_lifecycle(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test WashSteamSwitch turn on, turn off, reset on program change, and availability."""
    programs = parse_wash_programs([_SAMPLE_PROGRAM, _NO_STEAM_PROGRAM])
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="steam_test_entry",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(
        _BASE_WM_STATUS, program=1, machine_state=MachineState.IDLE, remote_control=True
    )

    steam_switch = WashSteamSwitch(coord, entry, mock_client, programs)
    steam_switch.hass = hass
    steam_switch.entity_id = "switch.wash_steam"

    assert steam_switch.unique_id == UNIQUE_ID_WASH_STEAM_SWITCH.format(entry.entry_id)
    assert steam_switch.available is True
    assert steam_switch.is_on is False

    await steam_switch.async_turn_on()
    assert steam_switch.is_on is True

    await steam_switch.async_turn_off()
    assert steam_switch.is_on is False

    # Program change resets steam switch
    await steam_switch.async_turn_on()
    steam_switch._on_program_changed(None)
    assert steam_switch.is_on is False

    # Availability when running
    coord.data = replace(coord.data, machine_state=MachineState.RUNNING)
    assert steam_switch.available is False

    # Availability when remote control is disabled
    coord.data = replace(
        coord.data, machine_state=MachineState.IDLE, remote_control=False
    )
    assert steam_switch.available is False

    # Availability when active program does not support steam
    coord.data = replace(coord.data, remote_control=True, program=2, program_code=101)
    assert steam_switch.available is False

    # Availability when active program is None
    coord.data = replace(coord.data, program=99, program_code=None)
    assert steam_switch.available is False


async def test_nfc_special_programs_switch_lifecycle(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test NfcSpecialProgramsSwitch turn on, turn off, and listener notification."""
    programs = parse_wash_programs([_SAMPLE_PROGRAM])
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="nfc_test_entry",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(_BASE_WM_STATUS, remote_control=True)
    coord.async_update_listeners = MagicMock()

    nfc_switch = NfcSpecialProgramsSwitch(coord, entry, mock_client, programs)
    nfc_switch.hass = hass
    nfc_switch.entity_id = "switch.nfc_special_programs"

    assert nfc_switch.unique_id == UNIQUE_ID_WASH_NFC_SWITCH.format(entry.entry_id)
    assert nfc_switch.available is True
    assert nfc_switch.is_on is False

    await nfc_switch.async_turn_on()
    assert nfc_switch.is_on is True
    coord.async_update_listeners.assert_called_once()

    coord.async_update_listeners.reset_mock()
    await nfc_switch.async_turn_off()
    assert nfc_switch.is_on is False
    coord.async_update_listeners.assert_called_once()


async def test_wash_option_switch_lifecycle(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test WashOptionSwitch turn on, turn off, availability, and reset on program change."""
    programs = parse_wash_programs([_SAMPLE_PROGRAM, _NO_STEAM_PROGRAM])
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="opt_test_entry",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(
        _BASE_WM_STATUS, program=1, machine_state=MachineState.IDLE, remote_control=True
    )

    opt_switch = WashOptionSwitch(
        coord,
        entry,
        mock_client,
        programs,
        bitmask=1,
        translation_key="wash_option_prewash",
        uid_suffix=UNIQUE_ID_WASH_OPTION_PREWASH,
        name="Prewash",
    )
    opt_switch.hass = hass
    opt_switch.entity_id = "switch.wash_option_prewash"

    assert opt_switch.unique_id == f"{entry.entry_id}-{UNIQUE_ID_WASH_OPTION_PREWASH}"
    assert opt_switch.available is True
    assert opt_switch.is_on is False

    await opt_switch.async_turn_on()
    assert opt_switch.is_on is True

    await opt_switch.async_turn_off()
    assert opt_switch.is_on is False

    # Program change resets option switch
    await opt_switch.async_turn_on()
    opt_switch._on_program_changed(None)
    assert opt_switch.is_on is False

    # Availability when remote control is disabled
    coord.data = replace(coord.data, remote_control=False)
    assert opt_switch.available is False
    coord.data = replace(coord.data, remote_control=True)

    # Availability when running
    coord.data = replace(coord.data, machine_state=MachineState.RUNNING)
    assert opt_switch.available is False
    coord.data = replace(coord.data, machine_state=MachineState.IDLE)

    # Availability when program does not support the bitmask
    coord.data = replace(coord.data, program=2, program_code=101)
    assert opt_switch.available is False

    # Availability when program is None
    coord.data = replace(coord.data, program=99, program_code=None)
    assert opt_switch.available is False


async def test_wash_extra_dose_switch_lifecycle(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test WashExtraDoseSwitch turn on, turn off, reset, and availability branches."""
    programs = parse_wash_programs([_SAMPLE_PROGRAM, _NO_STEAM_PROGRAM])
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="extra_dose_entry",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(
        _BASE_WM_STATUS, program=1, machine_state=MachineState.IDLE, remote_control=True
    )

    extra_dose = WashExtraDoseSwitch(coord, entry, mock_client, programs)
    extra_dose.hass = hass
    extra_dose.platform = MagicMock(platform_name=DOMAIN)
    extra_dose.entity_id = "switch.wash_extra_dose"

    assert extra_dose.unique_id == UNIQUE_ID_WASH_EXTRA_DOSE_SWITCH.format(
        entry.entry_id
    )
    assert extra_dose.available is True
    assert extra_dose.is_on is False

    await extra_dose.async_turn_on()
    assert extra_dose.is_on is True

    await extra_dose.async_turn_off()
    assert extra_dose.is_on is False

    # Program change resets switch
    await extra_dose.async_turn_on()
    extra_dose._on_program_changed(None)
    assert extra_dose.is_on is False

    # Availability when remote control disabled (line 438)
    coord.data = replace(coord.data, remote_control=False)
    assert extra_dose.available is False
    coord.data = replace(coord.data, remote_control=True)

    # Availability when machine is running
    coord.data = replace(coord.data, machine_state=MachineState.RUNNING)
    assert extra_dose.available is False
    coord.data = replace(coord.data, machine_state=MachineState.IDLE)

    # Availability when active program is None (line 441)
    coord.data = replace(coord.data, program=99, program_code=None)
    assert extra_dose.available is False

    # Availability when program options do not include bit 1
    coord.data = replace(coord.data, program=2, program_code=101)
    assert extra_dose.available is False


async def test_autodose_switches_detergent_and_softener(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test WashDetergentAutoDoseSwitch and WashSoftenerAutoDoseSwitch complete behavior."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="autodose_entry",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coord = CandyDataUpdateCoordinator(
        hass,
        logging.getLogger(__name__),
        name=DOMAIN,
        update_interval=timedelta(seconds=1),
        update_method=AsyncMock(),
        client=mock_client,
    )
    coord.last_update_success = True
    coord.data = replace(
        _BASE_WM_STATUS, detergent_on=1, softener_on=0, remote_control=True
    )
    coord.sync_autodose_state(coord.data)
    coord.async_request_refresh = AsyncMock()

    det_switch = WashDetergentAutoDoseSwitch(coord, entry, mock_client)
    soft_switch = WashSoftenerAutoDoseSwitch(coord, entry, mock_client)

    assert det_switch.unique_id == UNIQUE_ID_WASH_DETERGENT_AUTODOSE.format(
        entry.entry_id
    )
    assert soft_switch.unique_id == UNIQUE_ID_WASH_SOFTENER_AUTODOSE.format(
        entry.entry_id
    )
    assert det_switch.is_on is True
    assert soft_switch.is_on is False

    # When coordinator data is None (lines 349, 394)
    coord.data = None
    assert det_switch.is_on is False
    assert soft_switch.is_on is False

    # Restore data and test turn off detergent (lines 360-363)
    coord.data = replace(
        _BASE_WM_STATUS, detergent_on=1, softener_on=1, remote_control=True
    )
    coord.sync_autodose_state(coord.data)
    await det_switch.async_turn_off()
    mock_client.set_autodose.assert_called_with(False, True)
    coord.async_request_refresh.assert_called_once()

    # Test turn on detergent
    mock_client.set_autodose.reset_mock()
    coord.async_request_refresh.reset_mock()
    coord.data = replace(coord.data, detergent_on=0, softener_on=1)
    coord.sync_autodose_state(coord.data)
    await det_switch.async_turn_on()
    mock_client.set_autodose.assert_called_with(True, True)

    # Test turn on softener (lines 399-402)
    mock_client.set_autodose.reset_mock()
    coord.data = replace(coord.data, detergent_on=1, softener_on=0)
    coord.sync_autodose_state(coord.data)
    await soft_switch.async_turn_on()
    mock_client.set_autodose.assert_called_with(True, True)

    # Test turn off softener
    mock_client.set_autodose.reset_mock()
    coord.data = replace(coord.data, detergent_on=1, softener_on=1)
    coord.sync_autodose_state(coord.data)
    await soft_switch.async_turn_off()
    mock_client.set_autodose.assert_called_with(True, False)

    # Edge cases: status is None during turn_on / turn_off
    coord.data = None
    coord._desired_detergent = None
    coord._desired_softener = None
    mock_client.set_autodose.reset_mock()
    await det_switch.async_turn_on()
    mock_client.set_autodose.assert_called_with(True, False)

    coord._desired_softener = None
    mock_client.set_autodose.reset_mock()
    await det_switch.async_turn_off()
    mock_client.set_autodose.assert_called_with(False, False)

    coord._desired_detergent = None
    mock_client.set_autodose.reset_mock()
    await soft_switch.async_turn_on()
    mock_client.set_autodose.assert_called_with(False, True)

    coord._desired_detergent = None
    mock_client.set_autodose.reset_mock()
    await soft_switch.async_turn_off()
    mock_client.set_autodose.assert_called_with(False, False)
