"""Neon Billing integration for Home Assistant."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

import httpx
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NeonAPIError, NeonAuthError, NeonClient, NeonRateLimitError
from .const import (
    CONF_ALLOWANCES,
    CONF_API_KEY,
    CONF_LABEL,
    CONF_PLAN_OVERRIDES,
    CONF_RATES,
    CONF_SCOPES,
    CONF_SPLIT_BRANCHES,
    CONF_UPDATE_INTERVAL_MIN,
    DEFAULT_ALLOWANCES,
    DEFAULT_RATES,
    DEFAULT_UPDATE_INTERVAL_MIN,
    DOMAIN,
)
from .coordinator import NeonCoordinator, NeonScope, ScopeState

_LOGGER = logging.getLogger(__name__)

# PLATFORMS empty until Tasks 8 & 9 land sensor/binary_sensor modules.
PLATFORMS: list[Platform] = []


@dataclass
class NeonRuntimeData:
    coordinator: DataUpdateCoordinator[dict[str, ScopeState]]
    client: NeonClient
    http: httpx.AsyncClient
    label: str


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Neon Billing from a config entry."""
    http = httpx.AsyncClient()
    client = NeonClient(http=http, api_key=entry.data[CONF_API_KEY])

    scopes = [
        NeonScope(
            scope_id=s["scope_id"],
            label=f"{entry.data[CONF_LABEL]}_{s['scope_id']}",
            plan=entry.data.get(CONF_PLAN_OVERRIDES, {}).get(s["scope_id"], s["plan"]),
            org_id=s.get("org_id"),
        )
        for s in entry.data[CONF_SCOPES]
    ]
    rates = entry.options.get(CONF_RATES, dict(DEFAULT_RATES))
    allowances = entry.options.get(CONF_ALLOWANCES, dict(DEFAULT_ALLOWANCES))
    split = entry.options.get(CONF_SPLIT_BRANCHES, False)
    interval = entry.options.get(CONF_UPDATE_INTERVAL_MIN, DEFAULT_UPDATE_INTERVAL_MIN)

    inner = NeonCoordinator(
        client=client, scopes=scopes, rates=rates, allowances=allowances, split_branches=split
    )

    async def _async_update() -> dict[str, ScopeState]:
        try:
            return await inner.fetch()
        except NeonAuthError as exc:
            raise ConfigEntryAuthFailed from exc
        except NeonRateLimitError as exc:
            raise UpdateFailed(f"Neon rate limited: {exc}") from exc
        except NeonAPIError as exc:
            raise UpdateFailed(f"Neon API error: {exc}") from exc

    coordinator: DataUpdateCoordinator[dict[str, ScopeState]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"neon_billing_{entry.entry_id}",
        update_interval=timedelta(minutes=interval),
        update_method=_async_update,
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await http.aclose()
        raise
    except Exception:
        await http.aclose()
        raise ConfigEntryNotReady("first refresh failed")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = NeonRuntimeData(
        coordinator=coordinator, client=client, http=http, label=entry.data[CONF_LABEL]
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    runtime: NeonRuntimeData = hass.data[DOMAIN].pop(entry.entry_id)
    await runtime.http.aclose()
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
