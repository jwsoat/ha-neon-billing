"""Smoke tests for entry setup / unload."""
from __future__ import annotations

import httpx
import pytest
import respx
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neon_billing.const import (
    CONF_API_KEY,
    CONF_LABEL,
    CONF_PLAN_OVERRIDES,
    CONF_SCOPES,
    DOMAIN,
    NEON_API_BASE,
)
from tests.conftest import load_fixture


def _make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Neon (test)",
        data={
            CONF_API_KEY: "key-xyz",
            CONF_LABEL: "neon",
            CONF_SCOPES: [{"scope_id": "org-alpha", "org_id": "org-alpha", "plan": "launch"}],
            CONF_PLAN_OVERRIDES: {},
        },
        options={},
        unique_id="abc123",
    )


@respx.mock
@freeze_time("2026-06-16T12:00:00Z")
async def test_setup_and_unload(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me.json"))
    )
    respx.get(f"{NEON_API_BASE}/consumption_history/account").mock(
        return_value=httpx.Response(200, json=load_fixture("consumption_history_account.json"))
    )
    respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
        return_value=httpx.Response(200, json=load_fixture("spending_limit.json"))
    )
    respx.get(f"{NEON_API_BASE}/projects").mock(
        return_value=httpx.Response(200, json={"projects": []})
    )

    entry = _make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_sensors_created_for_each_scope(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    """Verify consumption/cost/spending_limit sensors materialize after setup."""
    import respx, httpx
    from freezegun import freeze_time
    from homeassistant.helpers import entity_registry as er
    from custom_components.neon_billing.const import NEON_API_BASE
    with respx.mock, freeze_time("2026-06-16T12:00:00Z"):
        respx.get(f"{NEON_API_BASE}/users/me").mock(
            return_value=httpx.Response(200, json=load_fixture("users_me.json"))
        )
        respx.get(f"{NEON_API_BASE}/consumption_history/account").mock(
            return_value=httpx.Response(200, json=load_fixture("consumption_history_account.json"))
        )
        respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
            return_value=httpx.Response(200, json=load_fixture("spending_limit.json"))
        )
        respx.get(f"{NEON_API_BASE}/projects").mock(
            return_value=httpx.Response(200, json={"projects": []})
        )
        entry = _make_entry()
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        # Translation files aren't loaded yet (Task 10) so entity_ids fall back
        # to anonymous slugs. Assert against unique_ids in the entity registry,
        # which always include the description.key by construction.
        registry = er.async_get(hass)
        unique_ids = [
            e.unique_id for e in registry.entities.values() if e.config_entry_id == entry.entry_id
        ]
        assert any("compute_hours" in uid for uid in unique_ids)
        assert any("total_cost_est" in uid for uid in unique_ids)
        assert any("spending_limit" in uid for uid in unique_ids)


async def test_threshold_binary_sensor_created(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    """Verify over_limit + a configured threshold binary sensor materialize."""
    import respx, httpx
    from freezegun import freeze_time
    from homeassistant.helpers import entity_registry as er
    from custom_components.neon_billing.const import CONF_THRESHOLD_PCTS, NEON_API_BASE
    with respx.mock, freeze_time("2026-06-16T12:00:00Z"):
        respx.get(f"{NEON_API_BASE}/users/me").mock(
            return_value=httpx.Response(200, json=load_fixture("users_me.json"))
        )
        respx.get(f"{NEON_API_BASE}/consumption_history/account").mock(
            return_value=httpx.Response(200, json=load_fixture("consumption_history_account.json"))
        )
        respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
            return_value=httpx.Response(200, json=load_fixture("spending_limit.json"))
        )
        respx.get(f"{NEON_API_BASE}/projects").mock(
            return_value=httpx.Response(200, json={"projects": []})
        )
        entry = _make_entry()
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(entry, options={CONF_THRESHOLD_PCTS: [80]})
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        uids = {entity.unique_id for entity in registry.entities.values() if entity.platform == "neon_billing" and entity.domain == "binary_sensor"}
        assert any("over_limit" in u for u in uids)
        assert any("threshold_80pct" in u for u in uids)
