"""Tests for the user-facing config and options flows."""
from __future__ import annotations

import httpx
import pytest
import respx
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neon_billing.const import (
    CONF_API_KEY,
    CONF_CURRENCY,
    CONF_FX_RATE,
    CONF_LABEL,
    CONF_SCOPES,
    CONF_SPLIT_BRANCHES,
    CONF_THRESHOLD_PCTS,
    CONF_UPDATE_INTERVAL_MIN,
    DOMAIN,
    NEON_API_BASE,
)
from tests.conftest import load_fixture


@respx.mock
async def test_full_happy_path(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me.json"))
    )
    respx.get(f"{NEON_API_BASE}/users/me/organizations").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me_orgs.json"))
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "key-xyz", CONF_LABEL: "neon"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "scopes"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"scope_ids": ["personal", "org-alpha"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry_data = result["data"]
    assert entry_data[CONF_API_KEY] == "key-xyz"
    assert {s["scope_id"] for s in entry_data[CONF_SCOPES]} == {"personal", "org-alpha"}


@respx.mock
async def test_invalid_auth_shows_error(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(return_value=httpx.Response(401, json={}))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "bad", CONF_LABEL: "neon"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


@respx.mock
async def test_duplicate_key_aborts(hass: HomeAssistant, enable_custom_integrations: None, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN, unique_id="dup", data={CONF_API_KEY: "key-xyz"}, options={}
    )
    existing.add_to_hass(hass)
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me.json"))
    )

    monkeypatch.setattr(
        "custom_components.neon_billing.config_flow._unique_id_for_key",
        lambda _: "dup",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "key-xyz", CONF_LABEL: "neon"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_persists_values(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="abc",
        data={CONF_API_KEY: "key-xyz", CONF_LABEL: "neon", CONF_SCOPES: [], "plan_overrides": {}},
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_UPDATE_INTERVAL_MIN: 30,
            CONF_SPLIT_BRANCHES: True,
            CONF_CURRENCY: "NZD",
            CONF_FX_RATE: 1.65,
            CONF_THRESHOLD_PCTS: "80,90",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_UPDATE_INTERVAL_MIN] == 30
    assert entry.options[CONF_THRESHOLD_PCTS] == [80, 90]


async def test_options_flow_rejects_currency_without_fx(hass: HomeAssistant, enable_custom_integrations: None) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="abc",
        data={CONF_API_KEY: "k", CONF_LABEL: "neon", CONF_SCOPES: [], "plan_overrides": {}},
        options={},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UPDATE_INTERVAL_MIN: 15, CONF_CURRENCY: "NZD", CONF_FX_RATE: 0.0,
         CONF_THRESHOLD_PCTS: "", CONF_SPLIT_BRANCHES: False},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_FX_RATE: "fx_required_when_currency_set"}
