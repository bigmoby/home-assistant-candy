"""Tests for Candy repair flows (<= 1.7.0 dishwasher migration)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy.client.cloud import CloudApplianceData, SimplyFiCloudError
from custom_components.candy.const import (
    CONF_KEY_INTERFACE_TYPE,
    CONF_KEY_IS_DISHWASHER,
    CONF_KEY_MODE,
    CONF_KEY_PROGRAM_LANGUAGE,
    CONF_KEY_PROGRAMS,
    CONF_KEY_USE_ENCRYPTION,
    DOMAIN,
    ISSUE_ID_DISHWASHER_FULL_CONTROL,
    LEGACY_DISHWASHER_CONTROL_ENTITIES,
    MODE_FULL_CONTROL,
    MODE_READ_ONLY,
    UNIQUE_ID_DISHWASHER_START_BUTTON,
)
from custom_components.candy.repairs import (
    DishwasherFullControlRepairFlow,
    async_create_fix_flow,
)
from tests.common import TEST_IP

_DISHWASHER_IDLE_JSON = json.dumps(
    {
        "statusDWash": {
            "StatoWiFi": "1",
            "CodiceErrore": "E0",
            "StatoDWash": "1",
            "Program": "P1",
            "RemTime": "0",
            "DelayStart": "0",
            "Eco": "0",
            "TreInUno": "0",
            "MetaCarico": "0",
            "MissSalt": "0",
            "NoRinseAid": "0",
            "OpenDoor": "0",
        }
    }
)


def _mock_dishwasher_endpoints(aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=_DISHWASHER_IDLE_JSON,
    )


def _register_legacy_controls(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entity_reg = er.async_get(hass)
    for platform, uid_template in LEGACY_DISHWASHER_CONTROL_ENTITIES:
        entity_reg.async_get_or_create(
            platform,
            DOMAIN,
            uid_template.format(entry.entry_id),
            config_entry=entry,
        )


async def test_legacy_dishwasher_creates_repair_issue(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A <= 1.7.0 dishwasher (read_only + legacy controls) raises a fixable repair."""
    _mock_dishwasher_endpoints(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dw-legacy-1",
        title="Candy Dishwasher",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    entry.add_to_hass(hass)
    _register_legacy_controls(hass, entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_id = ISSUE_ID_DISHWASHER_FULL_CONTROL.format(entry.entry_id)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "dishwasher_full_control_required"
    assert issue.data == {"entry_id": entry.entry_id}


async def test_fresh_read_only_dishwasher_does_not_create_repair(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A fresh read_only dishwasher without legacy controls raises no repair."""
    _mock_dishwasher_endpoints(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dw-fresh-ro",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
            CONF_KEY_IS_DISHWASHER: True,
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_id = ISSUE_ID_DISHWASHER_FULL_CONTROL.format(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_full_control_clears_existing_repair_issue(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Upgrading to Full Control (e.g. via Configure) deletes any active repair issue."""
    _mock_dishwasher_endpoints(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dw-upgraded",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_FULL_CONTROL,
            CONF_KEY_IS_DISHWASHER: True,
            CONF_KEY_INTERFACE_TYPE: "DW_DIGIT",
        },
    )
    entry.add_to_hass(hass)
    _register_legacy_controls(hass, entry)

    issue_id = ISSUE_ID_DISHWASHER_FULL_CONTROL.format(entry.entry_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="dishwasher_full_control_required",
        data={"entry_id": entry.entry_id},
    )
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repair_flow_switch_to_full_control(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Choosing Switch to Full Control fetches cloud data, sets language, and reloads."""
    _mock_dishwasher_endpoints(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dw-fix-full",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    entry.add_to_hass(hass)
    _register_legacy_controls(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_id = ISSUE_ID_DISHWASHER_FULL_CONTROL.format(entry.entry_id)
    flow = await async_create_fix_flow(hass, issue_id, {"entry_id": entry.entry_id})
    assert isinstance(flow, DishwasherFullControlRepairFlow)
    flow.hass = hass

    menu = await flow.async_step_init()
    assert menu["type"] == data_entry_flow.FlowResultType.MENU
    assert menu["description_placeholders"] == {"entry_title": entry.title}

    form = await flow.async_step_switch_to_full_control()
    assert form["type"] == data_entry_flow.FlowResultType.FORM

    # Cloud auth error surfaces cleanly without aborting
    with patch(
        "custom_components.candy.repairs.fetch_appliance_data",
        new=AsyncMock(side_effect=SimplyFiCloudError("bad creds")),
    ):
        err_result = await flow.async_step_switch_to_full_control(
            {"email": "a@b.com", "password": "wrong"}
        )
    assert err_result["type"] == data_entry_flow.FlowResultType.FORM
    assert err_result["errors"] == {"base": "cloud_auth"}

    cloud_data = CloudApplianceData(
        mac_address="AA:BB:CC:DD:EE:FF",
        encryption_key="",
        appliance_model="CDPN 4D620PW",
        serial_number="12345678",
        purchase_date=None,
        programs=[{"program": {"name": "ECO_45", "position": 1}}],
        downloadable_programs=[],
        interface_type="DW_DIGIT",
        brand="candy",
        appliance_type="dishwasher",
    )
    with patch(
        "custom_components.candy.repairs.fetch_appliance_data",
        new=AsyncMock(return_value=cloud_data),
    ):
        lang_form = await flow.async_step_switch_to_full_control(
            {"email": "a@b.com", "password": "secret"}
        )
    assert lang_form["type"] == data_entry_flow.FlowResultType.FORM
    assert lang_form["step_id"] == "language"

    done = await flow.async_step_language({CONF_KEY_PROGRAM_LANGUAGE: "it"})
    assert done["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.data[CONF_KEY_MODE] == MODE_FULL_CONTROL
    assert entry.data[CONF_KEY_INTERFACE_TYPE] == "DW_DIGIT"
    assert entry.data[CONF_KEY_PROGRAM_LANGUAGE] == "it"
    assert entry.data[CONF_KEY_PROGRAMS] == cloud_data.programs
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repair_flow_keep_read_only_removes_legacy_entities(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Choosing Keep Read-Only removes orphaned legacy controls and keeps read_only."""
    _mock_dishwasher_endpoints(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dw-fix-ro",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    entry.add_to_hass(hass)
    _register_legacy_controls(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_id = ISSUE_ID_DISHWASHER_FULL_CONTROL.format(entry.entry_id)
    flow = await async_create_fix_flow(hass, issue_id, {"entry_id": entry.entry_id})
    assert isinstance(flow, DishwasherFullControlRepairFlow)
    flow.hass = hass

    confirm = await flow.async_step_keep_read_only()
    assert confirm["type"] == data_entry_flow.FlowResultType.FORM

    done = await flow.async_step_keep_read_only({})
    assert done["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY

    entity_reg = er.async_get(hass)
    for platform, uid_template in LEGACY_DISHWASHER_CONTROL_ENTITIES:
        assert (
            entity_reg.async_get_entity_id(
                platform, DOMAIN, uid_template.format(entry.entry_id)
            )
            is None
        )
    assert entry.data[CONF_KEY_MODE] == MODE_READ_ONLY

    # Reloading does not recreate the issue once orphaned entities are gone
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_create_fix_flow_falls_back_when_entry_missing(
    hass: HomeAssistant,
) -> None:
    """If the config entry was deleted, async_create_fix_flow returns ConfirmRepairFlow."""
    flow = await async_create_fix_flow(
        hass,
        ISSUE_ID_DISHWASHER_FULL_CONTROL.format("missing-entry"),
        {"entry_id": "missing-entry"},
    )
    assert isinstance(flow, ConfirmRepairFlow)
    assert (
        er.async_get(hass).async_get_entity_id(
            "button", DOMAIN, UNIQUE_ID_DISHWASHER_START_BUTTON.format("missing-entry")
        )
        is None
    )


async def test_removing_entry_deletes_repair_issue(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Deleting a config entry cleans up its pending dishwasher repair issue."""
    _mock_dishwasher_endpoints(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dw-remove",
        title="Candy Dishwasher",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    entry.add_to_hass(hass)
    _register_legacy_controls(hass, entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue_id = ISSUE_ID_DISHWASHER_FULL_CONTROL.format(entry.entry_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_repair_flow_aborts_when_entry_missing(hass: HomeAssistant) -> None:
    """Every step aborts with entry_not_found if the config entry disappears."""
    flow = DishwasherFullControlRepairFlow("missing-entry")
    flow.hass = hass

    for step in (
        flow.async_step_init(),
        flow.async_step_switch_to_full_control(),
        flow.async_step_language(),
        flow.async_step_keep_read_only(),
    ):
        result = await step
        assert result["type"] == data_entry_flow.FlowResultType.ABORT
        assert result["reason"] == "entry_not_found"


async def test_repair_flow_unexpected_cloud_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unexpected exceptions during cloud fetch surface cloud_auth error on the form."""
    _mock_dishwasher_endpoints(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="dw-unexpected-err",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
            CONF_KEY_MODE: MODE_READ_ONLY,
        },
    )
    entry.add_to_hass(hass)

    flow = DishwasherFullControlRepairFlow(entry.entry_id)
    flow.hass = hass

    with patch(
        "custom_components.candy.repairs.fetch_appliance_data",
        new=AsyncMock(side_effect=RuntimeError("unexpected")),
    ):
        result = await flow.async_step_switch_to_full_control(
            {"email": "a@b.com", "password": "secret"}
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "switch_to_full_control"
    assert result["errors"] == {"base": "cloud_auth"}
