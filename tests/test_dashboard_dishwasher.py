"""Tests for the Dishwasher dashboard cards (dashboard/dishwasher.yaml and dashboard/dishwasher-maintenance.yaml)."""

from pathlib import Path
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
import pytest
import yaml

from custom_components.candy.const import DOMAIN

DASHBOARD_FILE = Path(__file__).parent.parent / "dashboard" / "dishwasher.yaml"
MAINTENANCE_DASHBOARD_FILE = (
    Path(__file__).parent.parent / "dashboard" / "dishwasher-maintenance.yaml"
)

# Suffixes of all entities referenced in the dishwasher dashboard cards
EXPECTED_ENTITY_SUFFIXES = {
    "sensor": {
        "",  # main sensor: sensor.<machine_name>
        "_program",
        "_program_description",
        "_remaining_time",
        "_cycle_status",
        "_error_code",
        "_water_hardness",
        "_dishwasher_water_hardness",  # tolerated backward-compatible fallback
        "_buzzer_volume",
        "_dishwasher_buzzer",  # tolerated backward-compatible fallback
        "_completed_cycles",
        "_total_cycles",
        "_check_up_maintenance_remaining_cycles",
        "_limescale_maintenance_remaining_cycles",
        "_filter_maintenance_remaining_cycles",
    },
    "binary_sensor": {
        "_salt_empty",
        "_rinse_aid_empty",
        "_door",
        "_remote_control",
        "_maintenance_clean_warning",
        "_remember_last_cycle",
        "_dishwasher_remember_last_cycle",  # tolerated backward-compatible fallback
    },
    "select": {
        "_program",
    },
    "number": {
        "_delay",
    },
    "switch": {
        "_eco_option",
        "_3in1_tablets",
        "_half_load",
        "_extra_dry",
        "_auto_open_door",
    },
    "button": {
        "_start",
        "_stop",
        "_pause",
        "_resume",
        "_open_door",
        "_check_up",
        "_check_up_maintenance_reset",
        "_limescale_maintenance_reset",
        "_filter_maintenance_reset",
    },
}


def _collect_templates(data: Any, path: str = "") -> list[tuple[str, str]]:
    """Recursively collect all Jinja template strings from parsed YAML."""
    templates: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            current_path = f"{path}.{key}" if path else key
            if isinstance(value, str) and ("{{" in value or "{%" in value):
                templates.append((current_path, value))
            else:
                templates.extend(_collect_templates(value, current_path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            current_path = f"{path}[{idx}]"
            if isinstance(item, str) and ("{{" in item or "{%" in item):
                templates.append((current_path, item))
            else:
                templates.extend(_collect_templates(item, current_path))
    return templates


def _collect_entities(data: Any) -> list[str]:
    """Recursively collect all entity strings referenced in dashboard cards."""
    entities: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in ("entity", "entity_id") and isinstance(value, str):
                entities.append(value)
            elif isinstance(value, (dict, list)):
                entities.extend(_collect_entities(value))
    elif isinstance(data, list):
        for item in data:
            entities.extend(_collect_entities(item))
    return entities


def test_dishwasher_card_yaml_syntax() -> None:
    """Test that dashboard/dishwasher.yaml is valid YAML and well-structured."""
    assert DOMAIN == "candy"
    assert DASHBOARD_FILE.is_file(), f"{DASHBOARD_FILE} does not exist"
    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    assert isinstance(parsed, dict)
    assert parsed.get("type") == "vertical-stack"
    cards = parsed.get("cards", [])
    assert len(cards) >= 5, "Expected at least 5 top-level sections in the card"


def test_dishwasher_maintenance_card_yaml_syntax() -> None:
    """Test that dashboard/dishwasher-maintenance.yaml is valid YAML and well-structured."""
    assert MAINTENANCE_DASHBOARD_FILE.is_file(), (
        f"{MAINTENANCE_DASHBOARD_FILE} does not exist"
    )
    content = MAINTENANCE_DASHBOARD_FILE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    assert isinstance(parsed, dict)
    assert parsed.get("type") == "vertical-stack"
    cards = parsed.get("cards", [])
    assert len(cards) >= 5, (
        "Expected at least 5 top-level sections in the maintenance card"
    )


def test_dishwasher_card_entity_naming_consistency() -> None:
    """Verify that all entities in the main dishwasher card use <machine_name> and match known suffixes."""
    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    declared_entities = _collect_entities(parsed)
    template_entities = re.findall(
        r"(?:states|is_state)\(\s*['\"]([a-z_]+(?:\.<machine_name>[a-z0-9_]*)?)['\"]\s*\)",
        content,
    )

    all_entities = set(declared_entities) | set(template_entities)
    assert len(all_entities) > 0

    for ent in all_entities:
        assert ent.count(".") == 1, f"Malformed entity format: {ent}"
        domain, object_id = ent.split(".", 1)
        assert domain in EXPECTED_ENTITY_SUFFIXES, f"Unexpected domain: {domain}"
        assert object_id.startswith("<machine_name>"), (
            f"Entity {ent} must start with <machine_name>"
        )
        suffix = object_id[len("<machine_name>") :]
        assert suffix in EXPECTED_ENTITY_SUFFIXES[domain], (
            f"Unexpected suffix '{suffix}' for domain '{domain}' in entity '{ent}'"
        )


def test_dishwasher_maintenance_card_entity_naming_consistency() -> None:
    """Verify that all entities in the maintenance card use <machine_name> and match known suffixes."""
    content = MAINTENANCE_DASHBOARD_FILE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    declared_entities = _collect_entities(parsed)
    template_entities = re.findall(
        r"(?:states|is_state)\(\s*['\"]([a-z_]+(?:\.<machine_name>[a-z0-9_]*)?)['\"]\s*\)",
        content,
    )

    all_entities = set(declared_entities) | set(template_entities)
    assert len(all_entities) > 0

    for ent in all_entities:
        assert ent.count(".") == 1, f"Malformed entity format: {ent}"
        domain, object_id = ent.split(".", 1)
        assert domain in EXPECTED_ENTITY_SUFFIXES, f"Unexpected domain: {domain}"
        assert object_id.startswith("<machine_name>"), (
            f"Entity {ent} must start with <machine_name>"
        )
        suffix = object_id[len("<machine_name>") :]
        assert suffix in EXPECTED_ENTITY_SUFFIXES[domain], (
            f"Unexpected suffix '{suffix}' for domain '{domain}' in entity '{ent}'"
        )


@pytest.mark.asyncio
async def test_dishwasher_template_rendering_lifecycle(hass: HomeAssistant) -> None:
    """Test that all Jinja templates render cleanly across all dishwasher lifecycle states."""
    for dash_file in (DASHBOARD_FILE, MAINTENANCE_DASHBOARD_FILE):
        content = dash_file.read_text(encoding="utf-8")
        prefix = "test_dishwasher"
        concrete_yaml = content.replace("<machine_name>", prefix)
        parsed = yaml.safe_load(concrete_yaml)

        templates = _collect_templates(parsed)
        assert len(templates) > 0, f"No Jinja templates found in {dash_file.name}"

        states_to_test = [
            # 1. Idle / Ready
            {
                f"sensor.{prefix}": ("Idle", {}),
                f"sensor.{prefix}_cycle_status": ("Stopped", {}),
                f"sensor.{prefix}_program": ("Eco 45°C", {}),
                f"sensor.{prefix}_program_description": ("Standard eco cycle", {}),
                f"sensor.{prefix}_remaining_time": ("0", {}),
                f"sensor.{prefix}_error_code": ("0", {}),
                f"sensor.{prefix}_water_hardness": ("3", {}),
                f"sensor.{prefix}_buzzer_volume": ("2", {}),
                f"sensor.{prefix}_total_cycles": ("45", {}),
                f"sensor.{prefix}_filter_maintenance_remaining_cycles": ("18", {}),
                f"sensor.{prefix}_limescale_maintenance_remaining_cycles": ("65", {}),
                f"sensor.{prefix}_check_up_maintenance_remaining_cycles": ("80", {}),
                f"binary_sensor.{prefix}_salt_empty": ("off", {}),
                f"binary_sensor.{prefix}_rinse_aid_empty": ("off", {}),
                f"binary_sensor.{prefix}_door": ("off", {}),
                f"binary_sensor.{prefix}_remote_control": ("on", {}),
                f"binary_sensor.{prefix}_maintenance_clean_warning": ("off", {}),
                f"binary_sensor.{prefix}_remember_last_cycle": ("on", {}),
                f"number.{prefix}_delay": ("0", {}),
                f"switch.{prefix}_eco_option": ("off", {}),
                f"switch.{prefix}_half_load": ("off", {}),
                f"switch.{prefix}_extra_dry": ("off", {}),
                f"switch.{prefix}_3in1_tablets": ("off", {}),
                f"switch.{prefix}_auto_open_door": ("off", {}),
            },
            # 2. Running Wash
            {
                f"sensor.{prefix}": ("Running", {}),
                f"sensor.{prefix}_cycle_status": ("Wash", {}),
                f"sensor.{prefix}_program": ("Intensive 75°C", {}),
                f"sensor.{prefix}_remaining_time": ("95", {}),
                f"binary_sensor.{prefix}_remote_control": ("on", {}),
                f"switch.{prefix}_extra_dry": ("on", {}),
                f"switch.{prefix}_3in1_tablets": ("on", {}),
            },
            # 3. Running Rinse
            {
                f"sensor.{prefix}": ("Running", {}),
                f"sensor.{prefix}_cycle_status": ("Rinse", {}),
                f"sensor.{prefix}_remaining_time": ("35", {}),
            },
            # 4. Running Drying
            {
                f"sensor.{prefix}": ("Running", {}),
                f"sensor.{prefix}_cycle_status": ("Drying", {}),
                f"sensor.{prefix}_remaining_time": ("15", {}),
            },
            # 5. Paused
            {
                f"sensor.{prefix}": ("Paused", {}),
                f"sensor.{prefix}_cycle_status": ("Wash", {}),
                f"sensor.{prefix}_remaining_time": ("75", {}),
            },
            # 6. Delayed start programmed
            {
                f"sensor.{prefix}": ("Delayed start programmed", {}),
                f"number.{prefix}_delay": ("180", {}),
            },
            # 7. Cycle Finished
            {
                f"sensor.{prefix}": ("Finished", {}),
                f"sensor.{prefix}_cycle_status": ("Finished", {}),
                f"sensor.{prefix}_remaining_time": ("0", {}),
                f"number.{prefix}_delay": ("0", {}),
            },
            # 8. Check-up running
            {
                f"sensor.{prefix}": ("checkup", {}),
            },
            # 9. Error Mode
            {
                f"sensor.{prefix}": ("Error", {}),
                f"sensor.{prefix}_error_code": ("E03", {}),
            },
            # 10. Consumables Empty & Filter Due
            {
                f"sensor.{prefix}": ("Idle", {}),
                f"sensor.{prefix}_error_code": ("0", {}),
                f"binary_sensor.{prefix}_salt_empty": ("on", {}),
                f"binary_sensor.{prefix}_rinse_aid_empty": ("on", {}),
                f"binary_sensor.{prefix}_maintenance_clean_warning": ("on", {}),
                f"sensor.{prefix}_filter_maintenance_remaining_cycles": ("0", {}),
                f"sensor.{prefix}_limescale_maintenance_remaining_cycles": ("0", {}),
                f"sensor.{prefix}_check_up_maintenance_remaining_cycles": ("0", {}),
            },
            # 11. Door Open & Manual Dial Mode (Remote Off)
            {
                f"sensor.{prefix}": ("Idle", {}),
                f"binary_sensor.{prefix}_door": ("on", {}),
                f"binary_sensor.{prefix}_remote_control": ("off", {}),
            },
            # 12. Appliance Off
            {
                f"sensor.{prefix}": ("Off", {}),
                f"sensor.{prefix}_cycle_status": ("unavailable", {}),
                f"sensor.{prefix}_program": ("unavailable", {}),
                f"sensor.{prefix}_remaining_time": ("unavailable", {}),
            },
        ]

        for state_dict in states_to_test:
            for entity_id, (state_val, attrs) in state_dict.items():
                hass.states.async_set(entity_id, state_val, attrs)
            await hass.async_block_till_done()

            for path, tmpl_str in templates:
                tmpl = Template(tmpl_str, hass)
                result = tmpl.async_render()
                assert result is not None, f"Template at {path} returned None"
                assert "{{" not in str(result), (
                    f"Unrendered template tag in {dash_file.name} at {path}: {result}"
                )
                assert "{%" not in str(result), (
                    f"Unrendered template tag in {dash_file.name} at {path}: {result}"
                )


@pytest.mark.asyncio
async def test_dishwasher_hero_card_template_outputs(hass: HomeAssistant) -> None:
    """Verify that specific lifecycle states produce the expected text, icons, and colors."""
    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    prefix = "dw"
    concrete_yaml = content.replace("<machine_name>", prefix)
    parsed = yaml.safe_load(concrete_yaml)

    hero_card = parsed["cards"][0]
    tmpl_primary = Template(hero_card["primary"], hass)
    tmpl_secondary = Template(hero_card["secondary"], hass)
    tmpl_badge_icon = Template(hero_card["badge_icon"], hass)
    tmpl_badge_color = Template(hero_card["badge_color"], hass)

    # 1. Idle
    hass.states.async_set(f"sensor.{prefix}", "Idle")
    hass.states.async_set(f"sensor.{prefix}_program", "Universal 60°C")
    hass.states.async_set(f"sensor.{prefix}_cycle_status", "Stopped")
    assert tmpl_primary.async_render().strip() == "Ready"
    assert tmpl_secondary.async_render().strip() == "Universal 60°C"
    assert tmpl_badge_color.async_render().strip() == "grey"

    # 2. Running Wash
    hass.states.async_set(f"sensor.{prefix}", "Running")
    hass.states.async_set(f"sensor.{prefix}_cycle_status", "Wash")
    assert tmpl_primary.async_render().strip() == "Running"
    assert tmpl_secondary.async_render().strip() == "Wash"
    assert tmpl_badge_icon.async_render().strip() == "mdi:play-circle"
    assert tmpl_badge_color.async_render().strip() == "blue"

    # 3. Running Drying
    hass.states.async_set(f"sensor.{prefix}", "Running")
    hass.states.async_set(f"sensor.{prefix}_cycle_status", "Drying")
    assert tmpl_primary.async_render().strip() == "Running"
    assert tmpl_secondary.async_render().strip() == "Drying"
    assert tmpl_badge_icon.async_render().strip() == "mdi:weather-dust"
    assert tmpl_badge_color.async_render().strip() == "blue"

    # 4. Paused
    hass.states.async_set(f"sensor.{prefix}", "Paused")
    assert tmpl_primary.async_render().strip() == "Paused"
    assert tmpl_badge_icon.async_render().strip() == "mdi:pause-circle"
    assert tmpl_badge_color.async_render().strip() == "orange"

    # 5. Finished
    hass.states.async_set(f"sensor.{prefix}", "Finished")
    assert tmpl_primary.async_render().strip() == "Cycle finished"
    assert "Unload dishwasher" in tmpl_secondary.async_render()
    assert tmpl_badge_icon.async_render().strip() == "mdi:check-circle"
    assert tmpl_badge_color.async_render().strip() == "green"

    # 6. Error
    hass.states.async_set(f"sensor.{prefix}", "Error")
    hass.states.async_set(f"sensor.{prefix}_error_code", "E02")
    assert tmpl_primary.async_render().strip() == "Error"
    assert tmpl_secondary.async_render().strip() == "Fault code: E02"
    assert tmpl_badge_icon.async_render().strip() == "mdi:alert-circle"
    assert tmpl_badge_color.async_render().strip() == "red"


@pytest.mark.asyncio
async def test_dishwasher_maintenance_card_outputs(hass: HomeAssistant) -> None:
    """Verify that maintenance card outputs correct alerts when consumables and filters are due."""
    content = MAINTENANCE_DASHBOARD_FILE.read_text(encoding="utf-8")
    prefix = "dw_maint"
    concrete_yaml = content.replace("<machine_name>", prefix)
    parsed = yaml.safe_load(concrete_yaml)

    header_card = parsed["cards"][0]
    tmpl_secondary = Template(header_card["secondary"], hass)
    tmpl_badge_icon = Template(header_card["badge_icon"], hass)
    tmpl_badge_color = Template(header_card["badge_color"], hass)

    # 1. Healthy state
    hass.states.async_set(f"sensor.{prefix}", "Idle")
    hass.states.async_set(f"sensor.{prefix}_error_code", "0")
    hass.states.async_set(f"binary_sensor.{prefix}_salt_empty", "off")
    hass.states.async_set(f"binary_sensor.{prefix}_rinse_aid_empty", "off")
    hass.states.async_set(f"binary_sensor.{prefix}_maintenance_clean_warning", "off")
    hass.states.async_set(f"sensor.{prefix}_filter_maintenance_remaining_cycles", "15")
    hass.states.async_set(
        f"sensor.{prefix}_limescale_maintenance_remaining_cycles", "40"
    )
    hass.states.async_set(
        f"sensor.{prefix}_check_up_maintenance_remaining_cycles", "70"
    )
    assert "All systems healthy" in tmpl_secondary.async_render()
    assert tmpl_badge_icon.async_render().strip() == "mdi:check-circle"
    assert tmpl_badge_color.async_render().strip() == "green"

    # 2. Refill salt & filter clean due
    hass.states.async_set(f"binary_sensor.{prefix}_salt_empty", "on")
    hass.states.async_set(f"sensor.{prefix}_filter_maintenance_remaining_cycles", "0")
    rendered = tmpl_secondary.async_render()
    assert "Refill Salt" in rendered
    assert "Filter Due" in rendered
    assert tmpl_badge_icon.async_render().strip() == "mdi:alert-circle"
    assert tmpl_badge_color.async_render().strip() == "red"


def test_dishwasher_dashboard_start_stop_check_button_availability() -> None:
    """Verify Start and Stop conditional cards check button availability."""
    parsed = yaml.safe_load(DASHBOARD_FILE.read_text(encoding="utf-8"))
    controls_card = parsed["cards"][5]
    cards = controls_card["card"]["cards"]
    start_conds = cards[0]["conditions"]
    stop_conds = cards[3]["conditions"]
    assert {
        "condition": "state",
        "entity": "button.<machine_name>_start",
        "state_not": "unavailable",
    } in start_conds
    assert {
        "condition": "state",
        "entity": "button.<machine_name>_stop",
        "state_not": "unavailable",
    } in stop_conds
