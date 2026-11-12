"""Tests for the Tumble Dryer dashboard card (dashboard/tumble-dryer.yaml)."""

from pathlib import Path
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
import pytest
import yaml

from custom_components.candy.const import DOMAIN

DASHBOARD_FILE = Path(__file__).parent.parent / "dashboard" / "tumble-dryer.yaml"

# Suffixes of all entities referenced in the tumble dryer dashboard card
EXPECTED_ENTITY_SUFFIXES = {
    "sensor": {
        "",  # main sensor: sensor.<machine_name>
        "_dryer_program",
        "_dryer_cycle_status",
        "_dryer_cycle_remaining_time",
        "_dry_level",
        "_dryer_error",
        "_check_up_state",
    },
    "binary_sensor": {
        "_water_tank_full",
        "_clean_filter",
        "_door",
        "_remote_control",
    },
    "select": {
        "_dryer_program",
        "_dry_level",
        "_timed_drying",
    },
    "number": {
        "_delay",
    },
    "button": {
        "_start_drying",
        "_pause_drying",
        "_resume_drying",
        "_stop_drying",
        "_cancel_anti_crease",
        "_check_up",
        "_reset_warnings",
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
    """Recursively collect all entity strings referenced in the dashboard card."""
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


def test_tumble_dryer_card_yaml_syntax() -> None:
    """Test that dashboard/tumble-dryer.yaml is valid YAML and well-structured."""
    assert DOMAIN == "candy"
    assert DASHBOARD_FILE.is_file(), f"{DASHBOARD_FILE} does not exist"
    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    assert isinstance(parsed, dict)
    assert parsed.get("type") == "vertical-stack"
    cards = parsed.get("cards", [])
    assert len(cards) >= 5, "Expected at least 5 top-level sections in the card"


def test_tumble_dryer_card_entity_naming_consistency() -> None:
    """Verify that all entities in the card use <machine_name> and match known suffixes."""
    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    # All direct entity declarations
    declared_entities = _collect_entities(parsed)
    # Also find entities mentioned inside Jinja template strings
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
async def test_tumble_dryer_template_rendering_lifecycle(hass: HomeAssistant) -> None:
    """Test that all Jinja templates render cleanly across all dryer lifecycle states."""
    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    prefix = "test_dryer"
    concrete_yaml = content.replace("<machine_name>", prefix)
    parsed = yaml.safe_load(concrete_yaml)

    templates = _collect_templates(parsed)
    assert len(templates) > 0, "No Jinja templates found in card"

    states_to_test = [
        # 1. Idle / Ready
        {
            f"sensor.{prefix}": ("idle", {}),
            f"sensor.{prefix}_dryer_cycle_status": ("Stopped", {}),
            f"sensor.{prefix}_dryer_program": ("1", {"program_name": "Eco Cotton"}),
            f"sensor.{prefix}_dry_level": ("store_dry", {}),
            f"sensor.{prefix}_dryer_cycle_remaining_time": ("0", {}),
            f"sensor.{prefix}_dryer_error": ("0", {}),
            f"sensor.{prefix}_check_up_state": ("0", {}),
            f"binary_sensor.{prefix}_water_tank_full": ("off", {}),
            f"binary_sensor.{prefix}_clean_filter": ("off", {}),
            f"binary_sensor.{prefix}_door": ("off", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
        },
        # 2. Running - Drying active
        {
            f"sensor.{prefix}": ("running", {}),
            f"sensor.{prefix}_dryer_cycle_status": ("Drying active", {}),
            f"sensor.{prefix}_dryer_program": ("2", {"program_name": "Synthetics"}),
            f"sensor.{prefix}_dry_level": ("hang_dry", {}),
            f"sensor.{prefix}_dryer_cycle_remaining_time": ("85", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
        },
        # 3. Running - Cooling down
        {
            f"sensor.{prefix}": ("running", {}),
            f"sensor.{prefix}_dryer_cycle_status": ("Cooling down", {}),
            f"sensor.{prefix}_dryer_program": ("3", {"program_name": "Rapid 45'"}),
            f"sensor.{prefix}_dry_level": ("iron_dry", {}),
            f"sensor.{prefix}_dryer_cycle_remaining_time": ("10", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
        },
        # 4. Paused
        {
            f"sensor.{prefix}": ("paused", {}),
            f"sensor.{prefix}_dryer_cycle_status": ("Drying active", {}),
            f"sensor.{prefix}_dryer_program": ("4", {"program_name": "Cotton"}),
            f"sensor.{prefix}_dry_level": ("bone_dry", {}),
            f"sensor.{prefix}_dryer_cycle_remaining_time": ("40", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
        },
        # 5. Delayed start programmed
        {
            f"sensor.{prefix}": ("delayed_start", {}),
            f"sensor.{prefix}_dryer_cycle_status": ("Stopped", {}),
            f"sensor.{prefix}_dryer_program": ("5", {"program_name": "Mix & Dry"}),
            f"sensor.{prefix}_dry_level": ("store_dry", {}),
            f"sensor.{prefix}_dryer_cycle_remaining_time": ("0", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("120", {}),
        },
        # 6. Cycle Finished
        {
            f"sensor.{prefix}": ("finished", {}),
            f"sensor.{prefix}_dryer_cycle_status": ("Completed", {}),
            f"sensor.{prefix}_dryer_program": ("4", {"program_name": "Cotton"}),
            f"sensor.{prefix}_dry_level": ("store_dry", {}),
            f"sensor.{prefix}_dryer_cycle_remaining_time": ("0", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
        },
        # 7. Check-up running & complete
        {
            f"sensor.{prefix}": ("checkup", {}),
            f"sensor.{prefix}_check_up_state": ("1", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
        },
        # 8. Error mode
        {
            f"sensor.{prefix}": ("error", {}),
            f"sensor.{prefix}_dryer_error": ("E03", {}),
            f"binary_sensor.{prefix}_remote_control": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
        },
        # 9. Appliance Off & Local Dial Mode
        {
            f"sensor.{prefix}": ("off", {}),
            f"binary_sensor.{prefix}_remote_control": ("off", {}),
            f"binary_sensor.{prefix}_water_tank_full": ("on", {}),
            f"binary_sensor.{prefix}_clean_filter": ("on", {}),
            f"binary_sensor.{prefix}_door": ("on", {}),
            f"number.{prefix}_delay": ("0", {}),
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
                f"Unrendered template tag in {path}: {result}"
            )
            assert "{%" not in str(result), (
                f"Unrendered template tag in {path}: {result}"
            )


@pytest.mark.asyncio
async def test_hero_card_template_outputs(hass: HomeAssistant) -> None:
    """Verify that specific lifecycle states produce the expected text, icons, and colors."""
    content = DASHBOARD_FILE.read_text(encoding="utf-8")
    prefix = "dryer"
    concrete_yaml = content.replace("<machine_name>", prefix)
    parsed = yaml.safe_load(concrete_yaml)

    hero_card = parsed["cards"][0]
    tmpl_primary = Template(hero_card["primary"], hass)
    tmpl_secondary = Template(hero_card["secondary"], hass)
    tmpl_badge_icon = Template(hero_card["badge_icon"], hass)
    tmpl_badge_color = Template(hero_card["badge_color"], hass)

    # 1. Idle
    hass.states.async_set(f"sensor.{prefix}", "Idle")
    hass.states.async_set(
        f"sensor.{prefix}_dryer_program", "1", {"program_name": "Eco Cotton"}
    )
    hass.states.async_set(f"sensor.{prefix}_dryer_cycle_status", "Stopped")
    assert tmpl_primary.async_render().strip() == "Ready"
    assert tmpl_secondary.async_render().strip() == "Eco Cotton"
    assert tmpl_badge_color.async_render().strip() == "grey"

    # 2. Running Drying
    hass.states.async_set(f"sensor.{prefix}", "Running")
    hass.states.async_set(f"sensor.{prefix}_dryer_cycle_status", "Drying active")
    assert tmpl_primary.async_render().strip() == "Running"
    assert tmpl_secondary.async_render().strip() == "Drying active"
    assert tmpl_badge_icon.async_render().strip() == "mdi:play-circle"
    assert tmpl_badge_color.async_render().strip() == "blue"

    # 3. Running Cooling Phase
    hass.states.async_set(f"sensor.{prefix}", "Running")
    hass.states.async_set(f"sensor.{prefix}_dryer_cycle_status", "Cooling down")
    assert tmpl_primary.async_render().strip() == "Running"
    assert tmpl_secondary.async_render().strip() == "Cooling down"
    assert tmpl_badge_icon.async_render().strip() == "mdi:snowflake"
    assert tmpl_badge_color.async_render().strip() == "cyan"

    # 4. Paused
    hass.states.async_set(f"sensor.{prefix}", "Paused")
    assert tmpl_primary.async_render().strip() == "Paused"
    assert tmpl_badge_icon.async_render().strip() == "mdi:pause-circle"
    assert tmpl_badge_color.async_render().strip() == "orange"

    # 5. Finished
    hass.states.async_set(f"sensor.{prefix}", "Finished")
    assert tmpl_primary.async_render().strip() == "Cycle finished"
    assert "Empty drum" in tmpl_secondary.async_render()
    assert tmpl_badge_icon.async_render().strip() == "mdi:check-circle"
    assert tmpl_badge_color.async_render().strip() == "green"

    # 6. Error
    hass.states.async_set(f"sensor.{prefix}", "Error")
    hass.states.async_set(f"sensor.{prefix}_dryer_error", "E03")
    assert tmpl_primary.async_render().strip() == "Error"
    assert tmpl_secondary.async_render().strip() == "Fault code: E03"
    assert tmpl_badge_icon.async_render().strip() == "mdi:alert-circle"
    assert tmpl_badge_color.async_render().strip() == "red"
