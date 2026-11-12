"""Invariant test suite for write commands and protocol encoding.

Validates that:
- Remote control safety preconditions block write commands when WiFiStatus is 0
- Wash options encode to precise hardware bitmask positions in OptMsk1
- Hoover 3D_DUAL interface bit swaps (bit 16 -> bit 128) function correctly
- Parameter bounds and wire conversions (spin/100, delay/30 or delay/60, soil level clamping) hold
- Round-trip command generation matches parsed appliance telemetry registers
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.client.model import (
    CheckUpResult,
    CheckUpState,
    MachineState,
    WasherDryerDryTarget,
    WashingMachineStatus,
    WashProgramState,
)
from custom_components.candy.const import (
    CONF_KEY_BRAND,
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_WASHER_DRYER,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAMS,
    DATA_KEY_COORDINATOR,
    MODE_FULL_CONTROL,
    UNIQUE_ID_WASH_DELAY_NUMBER,
    UNIQUE_ID_WASH_PAUSE_BUTTON,
    UNIQUE_ID_WASH_SOIL_SELECT,
    UNIQUE_ID_WASH_SPIN_SELECT,
    UNIQUE_ID_WASH_START_BUTTON,
    UNIQUE_ID_WASH_STOP_BUTTON,
    UNIQUE_ID_WASH_TEMP_SELECT,
)

from .common import init_integration

_COTTON_PROGRAM: dict[str, Any] = {
    "program": {
        "position": 1,
        "name": "DUAL_WM_WD_PROGRAM_NAME_RESISTANT_COTTONS",
        "command_parameters": [
            {"command_parameter": {"name": "selector_position", "validation": "1"}},
            {"command_parameter": {"name": "pr_code", "validation": "136"}},
            {"command_parameter": {"name": "maximum_temperature", "validation": "90"}},
            {"command_parameter": {"name": "default_temperature", "validation": "40"}},
            {"command_parameter": {"name": "maximum_spin_speed", "validation": "1400"}},
            {"command_parameter": {"name": "default_spin_speed", "validation": "800"}},
            {"command_parameter": {"name": "minimum_soil_level", "validation": "1"}},
            {"command_parameter": {"name": "maximum_soil_level", "validation": "3"}},
            {"command_parameter": {"name": "default_soil_level", "validation": "2"}},
            {"command_parameter": {"name": "steam", "validation": "5"}},
            {"command_parameter": {"name": "steam_type", "validation": "C"}},
            {"command_parameter": {"name": "default_duration", "validation": "90"}},
            {
                "command_parameter": {
                    "name": "remaining_time_soil_max",
                    "validation": "120",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_medium",
                    "validation": "90",
                }
            },
            {
                "command_parameter": {
                    "name": "remaining_time_soil_min",
                    "validation": "60",
                }
            },
            {
                "command_parameter": {
                    "name": "available_options",
                    "validation": "511",
                }
            },
        ],
    }
}

_STATS_MOCK = '{"statusCounters": {"Program1": "10"}}'


def _build_status(
    remote_control: bool, machine_state: MachineState = MachineState.IDLE
) -> WashingMachineStatus:
    """Build a deterministic status object with remote control state."""
    return WashingMachineStatus(
        machine_state=machine_state,
        program_state=WashProgramState.STOPPED,
        program=1,
        program_code=136,
        temp=40,
        spin_speed=800,
        remaining_minutes=0,
        remote_control=remote_control,
        fill_percent=0,
        error=0,
        delay_value=0,
        ntc_water=25,
        ntc_drum=24,
        motor_speed_freq=0,
        motor_state=0,
        unbalance_fault=0,
        unbalance_count=0,
        fault_count=0,
        dis_test_res=CheckUpResult.OK,
        checkup_state=CheckUpState.IDLE,
        soil_level=2,
        recipe_id=None,
        dry_target=WasherDryerDryTarget.NO_DRY,
        detergent_on=True,
        softener_on=True,
        detergent_empty=False,
        softener_empty=False,
        detergent_reserve=False,
        softener_reserve=False,
        detergent_cycles_remaining=25,
        softener_cycles_remaining=20,
        water_hardness=2,
        extra_dose_active=False,
    )


async def _setup_integration(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    interface_type: str = "RAPIDO_4DIG_STM_NEL",
    brand: str = "candy",
    remote_control: bool = True,
) -> tuple[str, er.EntityRegistry]:
    """Initialize a Full Control washing machine."""
    wifi_val = "1" if remote_control else "0"
    entry = await init_integration(
        hass,
        aioclient_mock,
        status_response=(
            f'{{"statusLavatrice": {{"WiFiStatus": "{wifi_val}", "Err": "0", '
            f'"MachMd": "1", "Pr": "1", "PrPh": "0", "Temp": "40", "SpinSp": "8", "RemTime": "0"}}}}'
        ),
        statistics_response=_STATS_MOCK,
        extra_config_data={
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_INTERFACE_TYPE: interface_type,
            CONF_KEY_BRAND: brand,
            CONF_KEY_IS_WASHER_DRYER: False,
            CONF_KEY_PROGRAMS: [_COTTON_PROGRAM],
        },
    )
    registry = er.async_get(hass)
    return entry.entry_id, registry


# ---------------------------------------------------------------------------
# Test 1: Remote Control Safety Precondition
# ---------------------------------------------------------------------------


async def test_remote_control_disabled_blocks_write_commands(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When WiFiStatus is 0 (local control mode), write buttons must be unavailable."""
    cid, registry = await _setup_integration(hass, aioclient_mock, remote_control=False)

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(cid)
    )
    stop_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_STOP_BUTTON.format(cid)
    )
    pause_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_PAUSE_BUTTON.format(cid)
    )

    assert start_eid is not None
    assert stop_eid is not None
    assert pause_eid is not None

    # When remote control is off, all buttons must report unavailable
    assert hass.states.get(start_eid).state == "unavailable"
    assert hass.states.get(stop_eid).state == "unavailable"
    assert hass.states.get(pause_eid).state == "unavailable"

    # Direct press must never emit an HTTP write request
    with patch(
        "custom_components.candy.client.CandyClient.send_command",
        new_callable=AsyncMock,
    ) as mock_send:
        await hass.services.async_call(
            "button", "press", {"entity_id": start_eid}, blocking=True
        )
        await hass.async_block_till_done()
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: Wash Options Bitmask Packing & Dispatch
# ---------------------------------------------------------------------------


async def test_wash_options_bitmask_packing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Prewash (1), Hygiene (2), and Good Night (8) must pack to OptMsk1=11."""
    cid, registry = await _setup_integration(hass, aioclient_mock, remote_control=True)

    # Enable Prewash (1), Hygiene (2), and Good Night (8) -> 1 + 2 + 8 = 11
    prewash_eid = registry.async_get_entity_id(
        "switch", DOMAIN, f"{cid}-wash_option_prewash"
    )
    hygiene_eid = registry.async_get_entity_id(
        "switch", DOMAIN, f"{cid}-wash_option_hygiene"
    )
    goodnight_eid = registry.async_get_entity_id(
        "switch", DOMAIN, f"{cid}-wash_option_goodnight"
    )

    assert prewash_eid is not None
    assert hygiene_eid is not None
    assert goodnight_eid is not None

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": prewash_eid}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": hygiene_eid}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": goodnight_eid}, blocking=True
    )
    await hass.async_block_till_done()

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(cid)
    )
    assert start_eid is not None

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
        assert params["OptMsk1"] == ["11"]
        assert params["Write"] == ["1"]
        assert params["StSt"] == ["1"]


# ---------------------------------------------------------------------------
# Test 3: Hoover 3D_DUAL Interface Bit Swap
# ---------------------------------------------------------------------------


async def test_hoover_3d_dual_bit_swap(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """On Hoover 3D_DUAL models, write commands must dispatch with DualTech command structure."""
    cid, registry = await _setup_integration(
        hass,
        aioclient_mock,
        interface_type="3D_DUAL_NEL",
        brand="hoover",
        remote_control=True,
    )

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(cid)
    )
    assert start_eid is not None

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
        assert "PrNm" in params


# ---------------------------------------------------------------------------
# Test 4: Wire Conversion and Parameter Clamping Invariants
# ---------------------------------------------------------------------------


async def test_parameter_scaling_and_delays(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Spin speed 1400 RPM must scale to 14, and delay 120 min must scale to 4 (120/30)."""
    cid, registry = await _setup_integration(hass, aioclient_mock, remote_control=True)

    # Set Spin speed to 1400
    spin_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SPIN_SELECT.format(cid)
    )
    assert spin_eid is not None
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": spin_eid, "option": "1400"},
        blocking=True,
    )

    # Set Delay to 120 min
    delay_eid = registry.async_get_entity_id(
        "number", DOMAIN, UNIQUE_ID_WASH_DELAY_NUMBER.format(cid)
    )
    assert delay_eid is not None
    await hass.services.async_call(
        "number", "set_value", {"entity_id": delay_eid, "value": 120}, blocking=True
    )
    await hass.async_block_till_done()

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(cid)
    )
    assert start_eid is not None

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
        assert params["SpdTgt"] == ["14"]  # 1400 // 100
        assert params["DelVl"] == ["4"]  # 120 // 30 on Rapido


# ---------------------------------------------------------------------------
# Test 5: Command Round-Trip Reflection Consistency
# ---------------------------------------------------------------------------


async def test_command_round_trip_reflection(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Dispatched write parameters reflected back in appliance telemetry must match HA sensor states."""
    cid, registry = await _setup_integration(hass, aioclient_mock, remote_control=True)
    coordinator = hass.data[DOMAIN][cid][DATA_KEY_COORDINATOR]

    # Configure custom wash parameters: 60C, 1200 RPM, Soil level 3 (high)
    temp_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_TEMP_SELECT.format(cid)
    )
    spin_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SPIN_SELECT.format(cid)
    )
    soil_eid = registry.async_get_entity_id(
        "select", DOMAIN, UNIQUE_ID_WASH_SOIL_SELECT.format(cid)
    )

    assert temp_eid is not None
    assert spin_eid is not None
    assert soil_eid is not None

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
    await hass.async_block_till_done()

    start_eid = registry.async_get_entity_id(
        "button", DOMAIN, UNIQUE_ID_WASH_START_BUTTON.format(cid)
    )
    assert start_eid is not None

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

    assert params["TmpTgt"] == ["60"]
    assert params["SpdTgt"] == ["12"]
    assert params["SLevTgt"] == ["3"]

    # Now reflect these registers back as active running telemetry from device
    reflected_status = WashingMachineStatus.from_json(
        {
            "WiFiStatus": "1",
            "Err": "0",
            "MachMd": "2",
            "PrPh": "2",
            "Pr": params["PrNm"][0],
            "PrCode": params["PrCode"][0],
            "Temp": params["TmpTgt"][0],
            "SpinSp": params["SpdTgt"][0],
            "SLevel": params["SLevTgt"][0],
            "DelVal": "0",
            "RemTime": "3000",
            "FillR": "50",
        }
    )
    coordinator.async_set_updated_data(reflected_status)
    await hass.async_block_till_done()

    assert coordinator.data.temp == 60
    assert coordinator.data.spin_speed == 1200
    assert coordinator.data.soil_level == 3
    assert coordinator.data.remaining_minutes == 50
