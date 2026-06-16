"""Config flow + options flow for Neon Billing."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import NeonAPIError, NeonAuthError, NeonClient
from .const import (
    CONF_ALLOWANCES,
    CONF_API_KEY,
    CONF_CURRENCY,
    CONF_FX_RATE,
    CONF_LABEL,
    CONF_PLAN_OVERRIDES,
    CONF_RATES,
    CONF_SCOPES,
    CONF_SPLIT_BRANCHES,
    CONF_THRESHOLD_PCTS,
    CONF_UPDATE_INTERVAL_MIN,
    DEFAULT_ALLOWANCES,
    DEFAULT_NAME,
    DEFAULT_RATES,
    DEFAULT_UPDATE_INTERVAL_MIN,
    DOMAIN,
    MAX_UPDATE_INTERVAL_MIN,
    MIN_UPDATE_INTERVAL_MIN,
    SCOPE_PERSONAL,
    SUPPORTED_PLANS,
)

_LOGGER = logging.getLogger(__name__)


def _unique_id_for_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _parse_thresholds(raw: str | list[int]) -> list[int]:
    items = raw if isinstance(raw, list) else [int(x.strip()) for x in raw.split(",") if x.strip()]
    return sorted({i for i in items if 1 <= i <= 500})


def _normalize_plan(plan: str | None) -> str:
    if plan is None:
        return "free"
    plan = plan.lower()
    return plan if plan in SUPPORTED_PLANS else "custom"


class NeonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._label: str = DEFAULT_NAME
        self._user_payload: dict[str, Any] = {}
        self._orgs: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            label = user_input[CONF_LABEL].strip() or DEFAULT_NAME
            unique = _unique_id_for_key(api_key)
            await self.async_set_unique_id(unique)
            self._abort_if_unique_id_configured()

            async with httpx.AsyncClient() as http:
                client = NeonClient(http=http, api_key=api_key)
                try:
                    self._user_payload = await client.get_user()
                    self._orgs = await client.list_organizations()
                except NeonAuthError:
                    errors["base"] = "invalid_auth"
                except NeonAPIError:
                    errors["base"] = "cannot_connect"
            if not errors:
                self._api_key = api_key
                self._label = label
                return await self.async_step_scopes()

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Required(CONF_LABEL, default=DEFAULT_NAME): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_scopes(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        scope_choices = {SCOPE_PERSONAL: f"Personal ({self._user_payload.get('email', '')})"}
        for org in self._orgs:
            scope_choices[org["id"]] = f"{org.get('name', org['id'])} (org)"

        if user_input is not None:
            selected = user_input["scope_ids"]
            scopes: list[dict[str, Any]] = []
            for sid in selected:
                if sid == SCOPE_PERSONAL:
                    plan = (
                        self._user_payload.get("billing_account", {})
                        .get("plan_details", {})
                        .get("name", "free")
                    )
                    scopes.append({"scope_id": SCOPE_PERSONAL, "org_id": None, "plan": _normalize_plan(plan)})
                else:
                    org = next((o for o in self._orgs if o["id"] == sid), None)
                    plan = (org or {}).get("plan", "free")
                    scopes.append({"scope_id": sid, "org_id": sid, "plan": _normalize_plan(plan)})
            assert self._api_key is not None
            return self.async_create_entry(
                title=f"Neon ({self._label})",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_LABEL: self._label,
                    CONF_SCOPES: scopes,
                    CONF_PLAN_OVERRIDES: {},
                },
            )

        options = [
            SelectOptionDict(value=sid, label=label) for sid, label in scope_choices.items()
        ]
        schema = vol.Schema(
            {
                vol.Required("scope_ids", default=list(scope_choices.keys())): SelectSelector(
                    SelectSelectorConfig(
                        options=options, multiple=True, mode=SelectSelectorMode.LIST
                    )
                )
            }
        )
        return self.async_show_form(step_id="scopes", data_schema=schema)

    async def async_step_reauth(self, _entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            async with httpx.AsyncClient() as http:
                client = NeonClient(http=http, api_key=api_key)
                try:
                    await client.get_user()
                except NeonAuthError:
                    errors["base"] = "invalid_auth"
                except NeonAPIError:
                    errors["base"] = "cannot_connect"
            if not errors:
                entry = self._get_reauth_entry()
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_API_KEY: api_key}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return NeonOptionsFlow(entry)


class NeonOptionsFlow(OptionsFlow):
    """User-editable options."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        current = self._entry.options
        if user_input is not None:
            currency = (user_input.get(CONF_CURRENCY) or "").strip().upper()
            fx = float(user_input.get(CONF_FX_RATE) or 0.0)
            if currency and fx <= 0:
                errors[CONF_FX_RATE] = "fx_required_when_currency_set"
            else:
                thresholds = _parse_thresholds(user_input.get(CONF_THRESHOLD_PCTS, ""))
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_UPDATE_INTERVAL_MIN: int(user_input[CONF_UPDATE_INTERVAL_MIN]),
                        CONF_SPLIT_BRANCHES: bool(user_input.get(CONF_SPLIT_BRANCHES, False)),
                        CONF_CURRENCY: currency,
                        CONF_FX_RATE: fx,
                        CONF_THRESHOLD_PCTS: thresholds,
                        CONF_RATES: current.get(CONF_RATES, dict(DEFAULT_RATES)),
                        CONF_ALLOWANCES: current.get(CONF_ALLOWANCES, dict(DEFAULT_ALLOWANCES)),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL_MIN,
                    default=current.get(CONF_UPDATE_INTERVAL_MIN, DEFAULT_UPDATE_INTERVAL_MIN),
                ): vol.All(int, vol.Range(min=MIN_UPDATE_INTERVAL_MIN, max=MAX_UPDATE_INTERVAL_MIN)),
                vol.Required(
                    CONF_SPLIT_BRANCHES, default=current.get(CONF_SPLIT_BRANCHES, False)
                ): bool,
                vol.Optional(CONF_CURRENCY, default=current.get(CONF_CURRENCY, "")): str,
                vol.Optional(CONF_FX_RATE, default=current.get(CONF_FX_RATE, 0.0)): vol.Coerce(float),
                vol.Optional(
                    CONF_THRESHOLD_PCTS,
                    default=",".join(str(i) for i in current.get(CONF_THRESHOLD_PCTS, [])),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
