"""Unit tests for the dishwasher number platform (delay start)."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import DOMAIN
from custom_components.candy.const import UNIQUE_ID_DISHWASHER_DELAY_NUMBER

from .common import init_integration

_READY = "dishwasher/remote_ready.json"
_RUNNING = "dishwasher/remote_running.json"


def _entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_id: str
) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, unique_id.format(entry.entry_id)
    )
    assert entity_id is not None
    return entity_id


async def test_delay_number_set_value_and_bounds(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test setting delay start minutes and verifying state."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_READY))
    delay_id = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)

    state = hass.states.get(delay_id)
    assert state is not None
    assert float(state.state) == 0.0
    assert state.attributes["min"] == 0
    assert state.attributes["max"] == 1440
    assert state.attributes["step"] == 30
    assert state.attributes["unit_of_measurement"] == "min"

    # Set delay value to 120 minutes
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": delay_id, "value": 120},
        blocking=True,
    )
    assert float(hass.states.get(delay_id).state) == 120.0


async def test_delay_number_unavailable_when_running(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Delay number is unavailable when cycle is running."""
    entry = await init_integration(hass, aioclient_mock, load_fixture(_RUNNING))
    delay_id = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)

    state = hass.states.get(delay_id)
    assert state is not None
    assert state.state == "unavailable"


async def test_delay_number_step_adapts_to_r15_zero(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When r15 == 0, delay is in hours so step is 60."""
    raw = json.loads(load_fixture(_READY))
    raw["statusDWash"]["r15"] = "0"
    entry = await init_integration(hass, aioclient_mock, json.dumps(raw))
    delay_id = _entity_id(hass, entry, "number", UNIQUE_ID_DISHWASHER_DELAY_NUMBER)
    assert hass.states.get(delay_id).attributes["step"] == 60
