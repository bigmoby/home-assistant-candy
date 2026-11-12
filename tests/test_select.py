"""Unit tests for custom_components.candy.select to achieve 100% coverage."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy.client import (
    CandyClient,
    WasherDryerDryTarget,
    WashingMachineStatus,
    parse_dryer_programs,
    parse_wash_programs,
)
from custom_components.candy.client.model import (
    DishwasherStatus,
    DryerCycleState,
    DryerProgramState,
    MachineState,
    TumbleDryerStatus,
    WashProgramState,
)
from custom_components.candy.const import (
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_CLIENT,
    DATA_KEY_COORDINATOR,
    DOMAIN,
    DRY_LEVEL_TO_VALUE,
    DRY_TARGET_CUPBOARD_DRY,
    DRY_TARGET_NO_DRY,
    DRY_TARGET_OPTIONS_ONLY_DRY,
    MODE_FULL_CONTROL,
    PROGRAM_TYPE_DRYING,
    PROGRAM_TYPE_WASH_AND_DRY,
    PROGRAM_TYPE_WASHING,
    RAPID_LEVEL_TO_VALUE,
    WATER_HARDNESS_MEDIUM,
)
from custom_components.candy.select import (
    CandyDryerLevelSelect,
    CandyDryerProgramSelect,
    CandyDryerRapidSelect,
    CandyDryerTimeSelect,
    CandyWashDrySelect,
    CandyWashProgramDescriptionSensor,
    CandyWashProgramTypeSelect,
    CandyWashWaterHardnessSelect,
    WashProgramSelect,
    WashSoilSelect,
    WashSpinSelect,
    WashTempSelect,
    async_setup_entry,
)

_SAMPLE_WASH_PROGRAM = {
    "program": {
        "position": 1,
        "name": "COTTON",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "selector_position_dry", "validation": "1"}},
            {"command_parameter": {"name": "pr_code", "validation": "100"}},
            {"command_parameter": {"name": "program_type", "validation": "W"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "90"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1400"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "1000"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "available_options", "validation": "1"}},
            {"command_parameter": {"name": "dry", "validation": "0"}},
        ],
    }
}

_SAMPLE_WD_PROGRAM = {
    "program": {
        "position": 2,
        "name": "WASH_AND_DRY",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "2"}},
            {"command_parameter": {"name": "selector_position_dry", "validation": "2"}},
            {"command_parameter": {"name": "pr_code", "validation": "101"}},
            {"command_parameter": {"name": "program_type", "validation": "WD"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "60"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1200"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "dry", "validation": "0"}},
        ],
    }
}

_SAMPLE_DRY_ONLY_PROGRAM = {
    "program": {
        "position": 3,
        "name": "DRY_COTTON",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "3"}},
            {"command_parameter": {"name": "pr_code", "validation": "102"}},
            {"command_parameter": {"name": "program_type", "validation": "D"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "255"}},
            {"command_parameter": {"name": "default_temperature", "validation": "0"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "255"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "0"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "dry_supported", "validation": "1"}},
            {"command_parameter": {"name": "dry", "validation": "1"}},
        ],
    }
}

_SAMPLE_NO_DRY_SUPPORT_PROGRAM = {
    "program": {
        "position": 4,
        "name": "SILK",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "4"}},
            {"command_parameter": {"name": "pr_code", "validation": "103"}},
            {"command_parameter": {"name": "program_type", "validation": "W"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "30"}},
            {"command_parameter": {"name": "default_temperature", "validation": "30"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "400"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "400"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "0"}},
            {"command_parameter": {"name": "dry_supported", "validation": "0"}},
            {"command_parameter": {"name": "dry", "validation": "0"}},
        ],
    }
}

_SAMPLE_DRYER_PROGRAM = {
    "program": {
        "position": 1,
        "name": "ECO_COTTON",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "set_dry_level", "validation": "1"}},
            {"command_parameter": {"name": "default_drying_level", "validation": "2"}},
            {"command_parameter": {"name": "set_time_level", "validation": "1"}},
            {"command_parameter": {"name": "default_time_level", "validation": "30"}},
            {"command_parameter": {"name": "set_rapido", "validation": "1"}},
        ],
    }
}

_SAMPLE_TIMED_ONLY_DRYER_PROGRAM = {
    "program": {
        "position": 2,
        "name": "REFRESH_TIMED",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "2"}},
            {"command_parameter": {"name": "set_dry_level", "validation": "0"}},
            {"command_parameter": {"name": "default_drying_level", "validation": "0"}},
            {"command_parameter": {"name": "set_time_level", "validation": "1"}},
            {"command_parameter": {"name": "default_time_level", "validation": "45"}},
            {"command_parameter": {"name": "set_rapido", "validation": "0"}},
        ],
    }
}

_SAMPLE_NO_TIME_DRYER_PROGRAM = {
    "program": {
        "position": 3,
        "name": "WOOL_FIXED",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "3"}},
            {"command_parameter": {"name": "set_dry_level", "validation": "0"}},
            {"command_parameter": {"name": "default_drying_level", "validation": "0"}},
            {"command_parameter": {"name": "set_time_level", "validation": "0"}},
            {"command_parameter": {"name": "default_time_level", "validation": "0"}},
            {"command_parameter": {"name": "set_rapido", "validation": "0"}},
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
    soil_level=2,
    recipe_id=None,
    dry_target=WasherDryerDryTarget.NO_DRY,
    detergent_on=0,
    softener_on=0,
    detergent_empty=None,
    softener_empty=None,
    detergent_reserve=None,
    softener_reserve=None,
    detergent_cycles_remaining=None,
    softener_cycles_remaining=None,
    water_hardness=2,
    extra_dose_active=None,
)

_BASE_TD_STATUS = TumbleDryerStatus(
    machine_state=MachineState.IDLE,
    program_state=DryerProgramState.STOPPED,
    cycle_state=DryerCycleState.LEVEL_NONE,
    program=1,
    remaining_minutes=0,
    remote_control=True,
    dry_level=2,
    dry_level_selected=2,
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
    client.set_water_hardness = AsyncMock()
    return client


async def test_async_setup_entry_dryer_empty_programs(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Setup returns early when dryer has no programs (line 117)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dryer_empty_programs",
        data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAMS: [],
        },
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


async def test_async_setup_entry_non_washer_non_dryer(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Setup returns early when coordinator data is not WashingMachineStatus (line 143)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dishwasher_entry",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.data = MagicMock(spec=DishwasherStatus)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_KEY_COORDINATOR: coord,
        DATA_KEY_CLIENT: mock_client,
    }
    async_add_entities = MagicMock()
    await async_setup_entry(hass, entry, async_add_entities)
    async_add_entities.assert_not_called()


async def test_program_type_select_branches(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test CandyWashProgramTypeSelect edge cases (lines 296, 303, 313, 324, 329-330)."""
    programs = parse_wash_programs(
        [_SAMPLE_WASH_PROGRAM, _SAMPLE_WD_PROGRAM, _SAMPLE_DRY_ONLY_PROGRAM]
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="type_select_test",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    entry.add_to_hass(hass)
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(
        _BASE_WM_STATUS,
        machine_state=MachineState.RUNNING,
        program=2,
        program_code=101,
    )

    type_select = CandyWashProgramTypeSelect(coord, entry, mock_client, programs)
    type_select.hass = hass
    type_select.platform = MagicMock(platform_name=DOMAIN)
    type_select.entity_id = "select.wash_program_type"

    # 1. Non-idle with WD program (line 296)
    assert type_select.current_option == PROGRAM_TYPE_WASH_AND_DRY

    # 2. Non-idle with program not matching anything -> fallback to WASHING (line 303)
    coord.data = replace(coord.data, program=99, program_code=None)
    assert type_select.current_option == PROGRAM_TYPE_WASHING

    # 3. Idle with WD program (line 313)
    coord.data = replace(
        _BASE_WM_STATUS,
        machine_state=MachineState.IDLE,
        program=2,
        program_code=101,
    )
    assert type_select.current_option == PROGRAM_TYPE_WASH_AND_DRY

    # 4. Invalid option raises ValueError (line 324)
    with pytest.raises(ValueError, match="Invalid program type: INVALID"):
        await type_select.async_select_option("INVALID")

    # 5. Program select is None, but dry_select is present (lines 329-330)
    dry_select = MagicMock()
    type_select.set_dry_select(dry_select)
    await type_select.async_select_option(PROGRAM_TYPE_DRYING)
    dry_select.update_for_program_type.assert_called_with(PROGRAM_TYPE_DRYING)


async def test_wash_dry_select_branches(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test CandyWashDrySelect edge cases (lines 374, 379-385, 396, 403-410, 433, 437, 449-452, 459-471)."""
    programs = parse_wash_programs(
        [
            _SAMPLE_WASH_PROGRAM,
            _SAMPLE_WD_PROGRAM,
            _SAMPLE_DRY_ONLY_PROGRAM,
            _SAMPLE_NO_DRY_SUPPORT_PROGRAM,
        ]
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dry_select_test",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    entry.add_to_hass(hass)
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(
        _BASE_WM_STATUS,
        program=2,
        program_code=101,
        dry_target=WasherDryerDryTarget.CUPBOARD_DRY,
    )

    # Dry select without type_select (lines 379-385)
    dry_select = CandyWashDrySelect(
        coord, entry, mock_client, programs, type_select=None
    )
    dry_select.hass = hass
    dry_select.platform = MagicMock(platform_name=DOMAIN)
    dry_select.entity_id = "select.wash_dry"

    # Standalone _active_program_type fallback without type_select
    # When active program is WD program (line 384)
    assert dry_select._active_program_type() == PROGRAM_TYPE_WASH_AND_DRY

    # When active program is dry only program (line 382)
    dry_select.update_for_program(programs[2])
    assert dry_select._active_program_type() == PROGRAM_TYPE_DRYING

    # When active program is wash only program without dry support (line 385)
    dry_select.update_for_program(programs[3])
    assert dry_select._active_program_type() == PROGRAM_TYPE_WASHING

    # Dry not supported program options (line 396)
    type_mock = MagicMock()
    type_mock.current_option = PROGRAM_TYPE_WASH_AND_DRY
    dry_select._type_select = type_mock
    dry_select.update_for_program(programs[3])  # SILK, dry_supported=False
    assert dry_select.options == [DRY_TARGET_NO_DRY]

    # Non-idle current_option with valid dry_target (lines 403-410)
    coord.data = replace(
        _BASE_WM_STATUS,
        machine_state=MachineState.RUNNING,
        program=2,
        program_code=101,
        dry_target=WasherDryerDryTarget.CUPBOARD_DRY,
    )
    dry_select.update_for_program(programs[1])
    assert dry_select.current_option == DRY_TARGET_CUPBOARD_DRY

    # Non-idle current_option with COOLDOWN (line 406)
    coord.data = replace(coord.data, dry_target=WasherDryerDryTarget.COOLDOWN)
    assert dry_select.current_option == dry_select.options[0]

    # Invalid dry target raises ValueError (line 437)
    with pytest.raises(ValueError, match="Invalid dry target: INVALID"):
        await dry_select.async_select_option("INVALID")

    # update_for_program fallback when DRY_TARGET_CUPBOARD_DRY is in opts
    coord.data = replace(coord.data, machine_state=MachineState.IDLE, dry_target=None)
    dry_select._current_option = "NonExistent"
    dry_select.update_for_program(programs[1])
    assert dry_select.current_option == DRY_TARGET_CUPBOARD_DRY

    # Lines 449-452: update_for_program when opts has custom target or is empty
    with patch.object(CandyWashDrySelect, "options", ["custom_target"]):
        dry_select._current_option = "NonExistent"
        dry_select.update_for_program(programs[1])
        assert dry_select._current_option == "custom_target"

    with patch.object(CandyWashDrySelect, "options", []):
        dry_select._current_option = "NonExistent"
        dry_select.update_for_program(programs[1])
        assert dry_select._current_option is None

    # Line 433: current_option fallback when opts has no standard targets
    with (
        patch.object(CandyWashDrySelect, "options", ["only_option"]),
        patch.object(CandyWashDrySelect, "_active_program_type", return_value="OTHER"),
    ):
        dry_select._current_option = None
        assert dry_select.current_option == "only_option"

    # update_for_program_type transitions (lines 459-471)
    type_mock.current_option = PROGRAM_TYPE_WASHING
    dry_select.update_for_program_type(PROGRAM_TYPE_WASHING)
    assert dry_select.current_option == DRY_TARGET_NO_DRY

    type_mock.current_option = PROGRAM_TYPE_DRYING
    dry_select.update_for_program_type(PROGRAM_TYPE_DRYING)
    assert dry_select.current_option == DRY_TARGET_CUPBOARD_DRY

    # Lines 470-471: update_for_program_type fallback
    dry_select._current_option = "INVALID_TARGET"
    dry_select.update_for_program_type("CUSTOM_TYPE")
    assert dry_select._current_option == dry_select.options[0]

    with patch.object(CandyWashDrySelect, "options", []):
        dry_select._current_option = "INVALID_TARGET"
        dry_select.update_for_program_type("CUSTOM_TYPE")
        assert dry_select._current_option is None


async def test_wash_program_select_and_description_sensor_branches(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test WashProgramSelect & CandyWashProgramDescriptionSensor edge branches."""
    programs = parse_wash_programs([_SAMPLE_WASH_PROGRAM, _SAMPLE_WD_PROGRAM])
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="prog_select_branches",
        data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    entry.add_to_hass(hass)
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(_BASE_WM_STATUS, program=1, program_code=100)

    temp_select = WashTempSelect(coord, entry, mock_client, programs)
    spin_select = WashSpinSelect(coord, entry, mock_client, programs)
    soil_select = WashSoilSelect(coord, entry, mock_client, programs)
    desc_sensor = CandyWashProgramDescriptionSensor(coord, entry)

    for idx, entity in enumerate((temp_select, spin_select, soil_select, desc_sensor)):
        entity.hass = hass
        domain_prefix = (
            "sensor"
            if isinstance(entity, CandyWashProgramDescriptionSensor)
            else "select"
        )
        entity.entity_id = f"{domain_prefix}.test_sub_{idx}"
        entity.platform = MagicMock(platform_name=DOMAIN)

    mock_dry = MagicMock()
    mock_nfc = MagicMock()
    mock_nfc.category_prefixed.return_value = "NFC Program"

    prog_select = WashProgramSelect(
        coord,
        entry,
        mock_client,
        programs,
        temp_select,
        spin_select,
        soil_select,
        desc_sensor,
        nfc_entries=[(mock_nfc, programs[0])],
        type_select=None,
        dry_select=mock_dry,
    )
    prog_select.hass = hass
    prog_select.platform = MagicMock(platform_name=DOMAIN)
    prog_select.entity_id = "select.wash_program"

    # 1. Stale current option resets to None (line 576)
    prog_select._current_option = "OldDeletedProgram"
    assert prog_select.current_option == "Cotton"
    assert prog_select._current_option is None

    # 2. extra_state_attributes when option is None or standard program (line 598)
    assert prog_select.extra_state_attributes is None
    with patch.object(WashProgramSelect, "current_option", None):
        assert prog_select.extra_state_attributes is None

    # 3. async_select_option with NFC program updates dry_select (line 636)
    await prog_select.async_select_option("NFC Program")
    mock_dry.update_for_program.assert_called_with(None)

    # 4. async_select_option with option not in programs and not in nfc (lines 649-651)
    mock_dry.update_for_program.reset_mock()
    await prog_select.async_select_option("UnknownProgram")
    mock_dry.update_for_program.assert_called_with(None)
    assert desc_sensor.native_value is None

    # 4. reset_for_standard_program with None (lines 746-747)
    desc_sensor.reset_for_standard_program(None)
    assert desc_sensor.native_value is None

    # 5. Fixed max temp and spin speed options and current_option (lines 803, 871)
    fixed_prog = parse_wash_programs([_SAMPLE_DRY_ONLY_PROGRAM])[0]
    temp_select.reset_for_standard_program(fixed_prog)
    assert temp_select.options == []
    temp_select._current_option = None
    assert temp_select.current_option is None

    spin_select.update_for_program(fixed_prog)
    assert spin_select.options == []
    spin_select._current_option = None
    assert spin_select.current_option is None

    # 6. WashSoilSelect when min_soil >= max_soil (line 937)
    soil_select.update_for_program(fixed_prog)
    assert soil_select.options == []
    soil_select._current_option = None
    assert soil_select.current_option is None

    # 7. WashTempSelect early return when _nfc_active (line 826)
    temp_select._nfc_active = True
    temp_select._current_option = "40"
    await temp_select.async_select_option("60")
    assert temp_select._current_option == "40"


async def test_wash_and_dry_transition_updates_dry_select(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test switching program type to Wash and Dry updates dry select and excludes no_dry."""
    programs = parse_wash_programs([_SAMPLE_WASH_PROGRAM, _SAMPLE_WD_PROGRAM])
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="wd_transition_test",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL, CONF_KEY_PROGRAM_LANGUAGE: "en"},
    )
    entry.add_to_hass(hass)
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = replace(
        _BASE_WM_STATUS,
        machine_state=MachineState.IDLE,
        program=1,
        program_code=100,
        dry_target=WasherDryerDryTarget.NO_DRY,
    )

    type_select = CandyWashProgramTypeSelect(coord, entry, mock_client, programs)
    dry_select = CandyWashDrySelect(coord, entry, mock_client, programs, type_select)
    temp_select = WashTempSelect(coord, entry, mock_client, programs)
    spin_select = WashSpinSelect(coord, entry, mock_client, programs)
    soil_select = WashSoilSelect(coord, entry, mock_client, programs)
    desc_sensor = CandyWashProgramDescriptionSensor(coord, entry)

    prog_select = WashProgramSelect(
        coord,
        entry,
        mock_client,
        programs,
        temp_select,
        spin_select,
        soil_select,
        desc_sensor,
        nfc_entries=[],
        type_select=type_select,
        dry_select=dry_select,
    )
    type_select.set_program_select(prog_select)
    type_select.set_dry_select(dry_select)
    dry_select.set_program_select(prog_select)

    for idx, entity in enumerate(
        (
            type_select,
            dry_select,
            prog_select,
            temp_select,
            spin_select,
            soil_select,
            desc_sensor,
        )
    ):
        entity.hass = hass
        entity.entity_id = f"select.test_entity_{idx}"
        entity.platform = MagicMock(platform_name=DOMAIN)

    # Initially in washing mode: options is only [no_dry]
    type_select._current_option = PROGRAM_TYPE_WASHING
    dry_select.update_for_program_type(PROGRAM_TYPE_WASHING)
    assert dry_select.options == [DRY_TARGET_NO_DRY]
    assert dry_select.current_option == DRY_TARGET_NO_DRY

    # When switching to wash_and_dry, even when current program changes:
    prog_select._current_option = "Cotton"  # Wash-only program, not in wash_and_dry
    await type_select.async_select_option(PROGRAM_TYPE_WASH_AND_DRY)

    # Dry select options must exclude no_dry and default to cupboard_dry
    assert dry_select.options == list(DRY_TARGET_OPTIONS_ONLY_DRY)
    assert dry_select.current_option == DRY_TARGET_CUPBOARD_DRY
    assert dry_select._current_option == DRY_TARGET_CUPBOARD_DRY


async def test_tumble_dryer_select_entities_edge_branches(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test CandyDryerLevelSelect, CandyDryerTimeSelect, CandyDryerRapidSelect, CandyDryerProgramSelect."""
    programs = parse_dryer_programs(
        [
            _SAMPLE_DRYER_PROGRAM,
            _SAMPLE_TIMED_ONLY_DRYER_PROGRAM,
            _SAMPLE_NO_TIME_DRYER_PROGRAM,
        ]
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dryer_select_branches",
        data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_PROGRAM_LANGUAGE: "en",
        },
    )
    entry.add_to_hass(hass)
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = _BASE_TD_STATUS

    level_select = CandyDryerLevelSelect(coord, entry, mock_client, programs)
    time_select = CandyDryerTimeSelect(coord, entry, mock_client, programs)
    rapid_select = CandyDryerRapidSelect(coord, entry, mock_client, programs)
    prog_select = CandyDryerProgramSelect(
        coord,
        entry,
        mock_client,
        programs,
        level_select,
        time_select,
        rapid_select,
    )

    for sel in (level_select, time_select, rapid_select, prog_select):
        sel.hass = hass
        sel.platform = MagicMock(platform_name=DOMAIN)
        sel.entity_id = f"select.test_{sel.__class__.__name__.lower()}"

    # 1. Non-dryer status returns False for _machine_is_idle (lines 993, 1091, 1191, 1282)
    coord.data = _BASE_WM_STATUS
    assert level_select._machine_is_idle() is False
    assert time_select._machine_is_idle() is False
    assert rapid_select._machine_is_idle() is False
    assert prog_select._machine_is_idle() is False
    coord.data = _BASE_TD_STATUS

    # 2. Invalid options raise ValueError (lines 1038, 1142, 1240, 1344)
    with pytest.raises(ValueError, match="Invalid dry level: INVALID"):
        await level_select.async_select_option("INVALID")

    with pytest.raises(ValueError, match="Invalid drying time: INVALID"):
        await time_select.async_select_option("INVALID")

    with pytest.raises(ValueError, match="Invalid rapid dry option: INVALID"):
        await rapid_select.async_select_option("INVALID")

    with pytest.raises(ValueError, match="Invalid dryer program: INVALID"):
        await prog_select.async_select_option("INVALID")

    # 3. CandyDryerLevelSelect:
    # Lines 1026-1027: current_option fallback when _current_option not in options
    level_select._current_option = "INVALID_CURRENT"
    assert level_select.current_option == level_select.options[0]
    with patch.object(CandyDryerLevelSelect, "options", []):
        assert level_select.current_option is None

    # Lines 1031-1032: selected_level property
    level_select._current_option = level_select.options[0]
    assert level_select.selected_level == DRY_LEVEL_TO_VALUE[level_select.options[0]]

    # Lines 1039-1040: async_select_option success path
    await level_select.async_select_option(level_select.options[1])
    assert level_select.current_option == level_select.options[1]

    # Line 1052: update_for_program with program whose default_drying_level is unlisted
    dummy_prog = replace(programs[0], default_drying_level=999)
    level_select.update_for_program(dummy_prog)
    assert level_select.current_option == level_select.options[0]

    # 4. CandyDryerTimeSelect:
    # Lines 1135-1138: non-numeric / off returns 0, valid digits returns int
    time_select._current_option = "off"
    assert time_select.selected_time_minutes == 0
    time_select._current_option = None
    assert time_select.selected_time_minutes == 0
    time_select._current_option = "45"
    assert time_select.selected_time_minutes == 45
    await time_select.async_select_option("45")
    assert time_select.current_option == "45"

    # Line 1077: __init__ with program having no time level
    time_sel_no_time = CandyDryerTimeSelect(coord, entry, mock_client, [programs[2]])
    assert time_sel_no_time._current_option is None

    # Lines 1079-1080: __init__ with program timed-only
    time_sel_timed = CandyDryerTimeSelect(coord, entry, mock_client, [programs[1]])
    assert time_sel_timed._current_option == "45"

    # Line 1158: update_for_program with timed-only program and empty options
    with patch.object(CandyDryerTimeSelect, "options", []):
        time_select.update_for_program(programs[1])
        assert time_select._current_option is None

    # 5. CandyDryerRapidSelect:
    # Lines 1233-1236: off returns 0, valid option returns mapped value
    rapid_select._current_option = "off"
    assert rapid_select.selected_rapid_level == 0
    rapid_select._current_option = None
    assert rapid_select.selected_rapid_level == 0
    rapid_select._current_option = "30"
    assert rapid_select.selected_rapid_level == RAPID_LEVEL_TO_VALUE["30"]
    await rapid_select.async_select_option("30")
    assert rapid_select.current_option == "30"

    # 6. CandyDryerProgramSelect: non-idle program matching (lines 1318-1324)
    coord.data = replace(
        _BASE_TD_STATUS,
        machine_state=MachineState.RUNNING,
        program=2,
    )
    assert prog_select.current_option == programs[1].localized_name("en")

    # Non-idle program not matching selector position (line 1328)
    coord.data = replace(coord.data, program=99)
    assert prog_select.current_option == prog_select.options[0]

    # selected_program fallback to programs[0] (line 1340)
    prog_select._current_option = "UnmatchedName"
    assert prog_select.selected_program == programs[0]


async def test_water_hardness_select_branches(
    hass: HomeAssistant, mock_client: CandyClient
) -> None:
    """Test CandyWashWaterHardnessSelect edge cases (lines 1390, 1394, 1398)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="hardness_select_test",
        data={CONF_KEY_MODE: MODE_FULL_CONTROL},
    )
    entry.add_to_hass(hass)
    coord = MagicMock(spec=DataUpdateCoordinator)
    coord.last_update_success = True
    coord.data = _BASE_WM_STATUS

    hardness_select = CandyWashWaterHardnessSelect(coord, entry, mock_client)
    hardness_select.hass = hass
    hardness_select.platform = MagicMock(platform_name=DOMAIN)
    hardness_select.entity_id = "select.water_hardness"

    # Current option when data is present
    assert hardness_select.current_option == WATER_HARDNESS_MEDIUM

    # When coordinator data is None (line 1390)
    coord.data = None
    assert hardness_select.current_option is None

    # When status.water_hardness is None (line 1394)
    coord.data = replace(_BASE_WM_STATUS, water_hardness=None)
    assert hardness_select.current_option is None

    # Invalid option raises ValueError (line 1398)
    with pytest.raises(ValueError, match="Invalid water hardness option: INVALID"):
        await hardness_select.async_select_option("INVALID")
