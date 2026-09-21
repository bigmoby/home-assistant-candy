"""Tests for the device trigger platform."""

from unittest.mock import MagicMock, patch

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.candy.client.model import (
    MachineState,
    WashingMachineStatistics,
    WashingMachineStatus,
    WashProgramState,
)
from custom_components.candy.const import (
    CONF_KEY_MAINTENANCE_ENABLED,
    CONF_KEY_MAINTENANCE_FILTER_ENABLED,
    CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP,
    CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED,
    CONF_KEY_WATER_HARDNESS,
    DATA_KEY_COORDINATOR,
    DATA_KEY_STATS_COORDINATOR,
    DOMAIN,
)
from custom_components.candy.device_trigger import (
    TRIGGER_TYPES,
    async_attach_trigger,
    async_get_triggers,
)


def _make_wm_status(state: MachineState) -> WashingMachineStatus:
    return WashingMachineStatus(
        machine_state=state,
        program_state=WashProgramState.STOPPED,
        program=0,
        program_code=None,
        temp=0,
        spin_speed=0,
        remaining_minutes=0,
        remote_control=False,
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
        soil_level=None,
        recipe_id=None,
        dry_type=None,
    )


def _trigger_config(trigger_type: str, device_id: str = "dev-1") -> dict:
    return {
        CONF_TYPE: trigger_type,
        CONF_DEVICE_ID: device_id,
        CONF_DOMAIN: DOMAIN,
        CONF_PLATFORM: "device",
    }


def _mock_device(entry_id: str) -> MagicMock:
    device = MagicMock()
    device.config_entries = {entry_id}
    return device


# ---------------------------------------------------------------------------
# async_get_triggers
# ---------------------------------------------------------------------------


async def test_get_triggers_no_device_id(hass):
    """device_id=None returns empty list."""
    result = await async_get_triggers(hass)
    assert result == []


async def test_get_triggers_device_not_found(hass):
    """Unknown device_id returns empty list."""
    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = None
        result = await async_get_triggers(hass, device_id="unknown")
    assert result == []


async def test_get_triggers_no_domain_entry(hass):
    """Device has no config entries → empty list."""
    device = MagicMock()
    device.config_entries = set()
    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = device
        result = await async_get_triggers(hass, device_id="dev-1")
    assert result == []


async def test_get_triggers_no_coordinator(hass):
    """Coordinator absent in hass.data → empty list."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="gt-no-coord", data={})
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: {}}

    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = _mock_device(entry.entry_id)
        result = await async_get_triggers(hass, device_id="dev-1")
    assert result == []


async def test_get_triggers_state_only(hass):
    """State-change triggers returned when maintenance is disabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="gt-state-only",
        data={CONF_KEY_MAINTENANCE_ENABLED: False},
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.data = _make_wm_status(MachineState.IDLE)
    hass.data[DOMAIN] = {entry.entry_id: {DATA_KEY_COORDINATOR: coordinator}}

    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = _mock_device(entry.entry_id)
        result = await async_get_triggers(hass, device_id="dev-1")

    types = {t[CONF_TYPE] for t in result}
    assert types == {"washing_started", "washing_completed", "error_reported"}
    assert all(t[CONF_DEVICE_ID] == "dev-1" for t in result)


async def test_get_triggers_all_six_with_maintenance(hass):
    """All 6 triggers returned when maintenance + both sub-types enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="gt-all-six",
        data={
            CONF_KEY_MAINTENANCE_ENABLED: True,
            CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED: True,
            CONF_KEY_MAINTENANCE_FILTER_ENABLED: True,
        },
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.data = _make_wm_status(MachineState.IDLE)
    hass.data[DOMAIN] = {entry.entry_id: {DATA_KEY_COORDINATOR: coordinator}}

    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = _mock_device(entry.entry_id)
        result = await async_get_triggers(hass, device_id="dev-1")

    assert len(result) == 6
    assert {t[CONF_TYPE] for t in result} == TRIGGER_TYPES


# ---------------------------------------------------------------------------
# async_attach_trigger — guard paths returning lambda: None
# ---------------------------------------------------------------------------


async def test_attach_trigger_no_config_entry(hass):
    """Unknown device → unsubscribe callable returned without error."""
    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = None
        unsub = await async_attach_trigger(
            hass, _trigger_config("washing_started"), MagicMock(), {}
        )
    unsub()  # must not raise


async def test_attach_trigger_no_coordinator(hass):
    """Coordinator absent → unsubscribe callable returned without error."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="at-no-coord", data={})
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: {}}

    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = _mock_device(entry.entry_id)
        unsub = await async_attach_trigger(
            hass, _trigger_config("washing_started"), MagicMock(), {}
        )
    unsub()


async def test_attach_trigger_maintenance_no_stats_coordinator(hass):
    """Maintenance trigger with no stats coordinator returns lambda: None."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="at-no-stats",
        data={CONF_KEY_WATER_HARDNESS: 2, CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0},
    )
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.data = _make_wm_status(MachineState.IDLE)
    hass.data[DOMAIN] = {entry.entry_id: {DATA_KEY_COORDINATOR: coordinator}}

    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = _mock_device(entry.entry_id)
        unsub = await async_attach_trigger(
            hass, _trigger_config("maintenance_selfclean_due"), MagicMock(), {}
        )
    unsub()


# ---------------------------------------------------------------------------
# State trigger callback behaviour
# ---------------------------------------------------------------------------


async def _attach_state_cb(hass, trigger_type, initial_state):
    """Set up a state trigger and return (coordinator, on_update callback)."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"scb-{trigger_type}", data={})
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = _make_wm_status(initial_state)
    captured = []
    coordinator.async_add_listener = lambda cb: captured.append(cb) or (lambda: None)

    hass.data[DOMAIN] = {entry.entry_id: {DATA_KEY_COORDINATOR: coordinator}}

    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = _mock_device(entry.entry_id)
        await async_attach_trigger(
            hass, _trigger_config(trigger_type), MagicMock(), {"trigger_data": {}}
        )

    assert len(captured) == 1
    return coordinator, captured[0]


async def test_state_trigger_status_none_does_not_fire(hass):
    """Callback with None coordinator data does not fire the job."""
    coordinator, on_update = await _attach_state_cb(
        hass, "washing_started", MachineState.IDLE
    )
    coordinator.data = None
    with patch.object(hass, "async_run_hass_job") as mock_job:
        on_update()
        assert mock_job.call_count == 0


async def test_state_trigger_washing_started(hass):
    """washing_started fires on IDLE→RUNNING but not RUNNING→RUNNING or PAUSED→RUNNING."""
    coordinator, on_update = await _attach_state_cb(
        hass, "washing_started", MachineState.IDLE
    )

    with patch.object(hass, "async_run_hass_job") as mock_job:
        # IDLE → RUNNING: fires
        coordinator.data = _make_wm_status(MachineState.RUNNING)
        on_update()
        assert mock_job.call_count == 1

        # RUNNING → RUNNING: does not fire
        on_update()
        assert mock_job.call_count == 1

        # RUNNING → PAUSED → RUNNING: PAUSED→RUNNING must NOT fire
        coordinator.data = _make_wm_status(MachineState.PAUSED)
        on_update()
        coordinator.data = _make_wm_status(MachineState.RUNNING)
        on_update()
        assert mock_job.call_count == 1


async def test_state_trigger_washing_completed(hass):
    """washing_completed fires when entering FINISHED1 from non-finished state."""
    coordinator, on_update = await _attach_state_cb(
        hass, "washing_completed", MachineState.RUNNING
    )

    with patch.object(hass, "async_run_hass_job") as mock_job:
        # RUNNING → FINISHED1: fires
        coordinator.data = _make_wm_status(MachineState.FINISHED1)
        on_update()
        assert mock_job.call_count == 1

        # FINISHED1 → FINISHED1: does not fire again
        on_update()
        assert mock_job.call_count == 1


async def test_state_trigger_error_reported(hass):
    """error_reported fires on transition into ERROR state."""
    coordinator, on_update = await _attach_state_cb(
        hass, "error_reported", MachineState.RUNNING
    )

    with patch.object(hass, "async_run_hass_job") as mock_job:
        # RUNNING → ERROR: fires
        coordinator.data = _make_wm_status(MachineState.ERROR)
        on_update()
        assert mock_job.call_count == 1

        # ERROR → ERROR: does not fire again
        on_update()
        assert mock_job.call_count == 1

        # ERROR → IDLE → ERROR: fires again (new transition)
        coordinator.data = _make_wm_status(MachineState.IDLE)
        on_update()
        coordinator.data = _make_wm_status(MachineState.ERROR)
        on_update()
        assert mock_job.call_count == 2


# ---------------------------------------------------------------------------
# Maintenance trigger callback behaviour
# ---------------------------------------------------------------------------


async def _attach_maintenance_cb(hass, initial_total_cycles):
    """Set up a full_checkup maintenance trigger and return (stats_coordinator, callback)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="maint-cb",
        data={CONF_KEY_WATER_HARDNESS: 2, CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP: 0},
    )
    entry.add_to_hass(hass)

    coordinator = MagicMock()
    coordinator.data = _make_wm_status(MachineState.IDLE)

    stats_coordinator = MagicMock()
    if initial_total_cycles is not None:
        stats_coordinator.data = WashingMachineStatistics(
            total_cycles=initial_total_cycles
        )
    else:
        stats_coordinator.data = None

    captured = []
    stats_coordinator.async_add_listener = lambda cb: (
        captured.append(cb) or (lambda: None)
    )

    hass.data[DOMAIN] = {
        entry.entry_id: {
            DATA_KEY_COORDINATOR: coordinator,
            DATA_KEY_STATS_COORDINATOR: stats_coordinator,
        }
    }

    with patch("custom_components.candy.device_trigger.dr.async_get") as mock_reg:
        mock_reg.return_value.async_get.return_value = _mock_device(entry.entry_id)
        await async_attach_trigger(
            hass,
            _trigger_config("maintenance_full_checkup_due"),
            MagicMock(),
            {"trigger_data": {}},
        )

    assert len(captured) == 1
    return stats_coordinator, captured[0]


async def test_maintenance_trigger_fires_on_transition_to_zero(hass):
    """Fires when remaining cycles drop from non-zero to zero."""
    # total=50, last_reset=0, threshold=100 → remaining=50 initially
    stats_coordinator, on_update = await _attach_maintenance_cb(hass, 50)

    with patch.object(hass, "async_run_hass_job") as mock_job:
        # total=100 → elapsed=100 >= threshold → remaining=0; prev was 50 → fires
        stats_coordinator.data = WashingMachineStatistics(total_cycles=100)
        on_update()
        assert mock_job.call_count == 1

        # Still total=100 → remaining=0; prev is now 0 → does NOT fire again
        on_update()
        assert mock_job.call_count == 1


async def test_maintenance_trigger_no_fire_when_remaining_positive(hass):
    """Does not fire when remaining cycles stay above zero."""
    stats_coordinator, on_update = await _attach_maintenance_cb(hass, 50)

    with patch.object(hass, "async_run_hass_job") as mock_job:
        # total=51 → remaining=49 (non-zero); prev was 50 → no fire
        stats_coordinator.data = WashingMachineStatistics(total_cycles=51)
        on_update()
        assert mock_job.call_count == 0


async def test_maintenance_trigger_initial_none_stats(hass):
    """When initial stats are None, prev is seeded as None and no spurious fire occurs."""
    # initial_total_cycles=None → stats_coordinator.data=None → prev_remaining=[None]
    stats_coordinator, on_update = await _attach_maintenance_cb(hass, None)

    with patch.object(hass, "async_run_hass_job") as mock_job:
        # First update: stats still None → curr=None, prev=None; None==0 is False → no fire
        on_update()
        assert mock_job.call_count == 0

        # Stats appear with remaining > 0 → no fire
        stats_coordinator.data = WashingMachineStatistics(total_cycles=10)
        on_update()
        assert mock_job.call_count == 0
