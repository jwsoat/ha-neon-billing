# Neon Billing — Home Assistant Custom Integration

**Date:** 2026-06-16
**Status:** Design approved, ready for implementation planning
**Owner:** info@jwsoat.com

## 1. Purpose

A Home Assistant custom integration that monitors Neon (serverless Postgres) billing exposure for one or more Neon API keys. It surfaces consumption (units), estimated charges (USD, computed client-side), spending-limit configuration, and over-limit alerts so the operator can build HA dashboards and automations against runaway Neon spend.

## 2. Goals & Non-Goals

### Goals
- One HA device per monitored Neon scope (personal account or organisation).
- Numeric sensors for current-period consumption by category: compute, storage, public network transfer, branch counts (total / root / child / extra).
- Estimated dollar charges per category and total, computed from consumption × configurable rates.
- Spending-limit sensor + percent-used sensor (can exceed 100%).
- `binary_sensor.<label>_over_limit` (fixed 100% threshold) plus 0–N user-configured threshold binary sensors.
- Optional local-currency mirror sensors for every cost sensor when an FX rate is configured.
- Multi-key support: each Neon API key becomes its own HA config entry.

### Non-Goals
- Exact reproduction of Neon's invoice figures (the public v2 API does not expose dashboard dollar values; estimates are explicitly approximate).
- Historic billing (past invoices, period-over-period trend graphs) — out of scope for v1.
- Mutating Neon resources from HA (read-only).
- Per-project drill-down sensors (one device per scope; project-level data is rolled up).

## 3. Critical API Constraint

Neon's public v2 API (verified 2026-06-16 against `https://neon.com/api_spec/release/v2.json`) **does not return dollar charges per category**. It returns:

- `GET /consumption_history/account` — unit metrics: `active_time_seconds`, `compute_time_seconds`, `written_data_bytes`, `synthetic_storage_size_bytes`, `data_storage_bytes_hour`.
- `GET /organizations/{org_id}/billing/spending_limit` → `spending_limit_cents` (Launch / Scale plans only; Free plan returns no limit).
- `GET /users/me` → `billing_account.plan_details.name` (plan name only, no $ totals).

Therefore the integration computes dollar estimates client-side from consumption × a published Neon rate table. Estimates are labelled with attribute `is_estimate: true` and a `rate_table_version` date, and the README warns users that values will drift from Neon's actual invoice when Neon changes pricing.

## 4. Architecture

### 4.1 Repository Layout

```
ha-neon-billing/
  custom_components/neon_billing/
    __init__.py            # ConfigEntry setup, coordinator wiring, unload
    manifest.json          # domain, version, codeowners, iot_class, dependencies
    config_flow.py         # UI flow + options flow
    coordinator.py         # DataUpdateCoordinator per entry
    api.py                 # httpx-based async wrapper for Neon v2 endpoints
    pricing.py             # rate table + Decimal-based estimator
    const.py               # DOMAIN, defaults, rate constants, plan allowances
    sensor.py              # numeric SensorEntity subclasses
    binary_sensor.py       # over_limit + dynamic threshold BinarySensorEntity
    strings.json
    translations/en.json
  tests/
    conftest.py            # pytest-homeassistant-custom-component fixtures
    test_pricing.py
    test_api.py
    test_config_flow.py
    test_coordinator.py
    fixtures/              # canned Neon API responses
  docs/
    INSTALL.md
    superpowers/specs/2026-06-16-neon-billing-integration-design.md  # this file
  hacs.json
  README.md
  LICENSE                  # MIT
  pyproject.toml           # ruff + mypy config
  .github/workflows/ci.yml # lint, type, test, hassfest, HACS validation
```

### 4.2 Runtime Topology

- One HA config entry = one Neon API key.
- Each config entry can monitor 1–N "scopes" (personal account + selected organisations) chosen at setup.
- Each scope = one HA `Device`. Devices under the same config entry share API quota but otherwise act independently.
- One `DataUpdateCoordinator` per config entry; each refresh fans out per-scope requests in parallel via `asyncio.gather`.
- Coordinator publishes a `dict[scope_id, ScopeState]`; sensors read their slice via the entry-level coordinator.

### 4.3 Data Flow (single refresh)

1. `GET /users/me` once per entry → identify principal + list orgs.
2. For each enabled scope, in parallel:
   1. `GET /consumption_history/account` for the current billing period (period bounds derived from `billing_account.quota_reset_at_last` + 1 month).
   2. `GET /organizations/{org_id}/billing/spending_limit` — skip on personal scope or 403/404; treat as `None`.
   3. If `split_branches_root_child` is enabled: `GET /projects?org_id=...` then `GET /projects/{id}/branches` per project, plus `GET /consumption_history/v2/branches` for per-branch consumption.
3. `pricing.estimate(...)` converts consumption to per-category Decimal USD.
4. Coordinator returns the assembled state; HA dispatches state updates to all entities.

## 5. Sensor Inventory

All entity_ids prefixed with `sensor.<scope_label>_...`. Scope label = user-supplied label + scope name (e.g. `neon_personal_compute_hours`).

### 5.1 Consumption (units, sourced directly from API)

| Sensor | Unit | State class | Notes |
|---|---|---|---|
| `compute_hours` | h | total | CU-hours this period. From `compute_time_seconds / 3600`. |
| `storage_gb` | GB | measurement | Latest sample of `synthetic_storage_size_bytes / 1e9`. |
| `data_transfer_gb` | GB | total | From `data_transfer_bytes / 1e9`. |
| `branch_count_root` | — | measurement | `parent_id is null` count across enabled scope's projects. |
| `branch_count_child` | — | measurement | `parent_id is not null` count. |
| `branch_count_extra` | — | measurement | `max(0, total_branches − plan_allowance.branches)`. |

### 5.2 Estimated Charges (USD)

| Sensor | Unit | Notes |
|---|---|---|
| `compute_cost_est` | USD | overage CU-hours × `rates.compute_per_cuh`. When `split_branches_root_child=true`, this becomes 0 and the compute spend is reported via `branches_root_cost_est` + `branches_child_cost_est` instead (see §6.4). |
| `storage_cost_est` | USD | overage GB-hours × `rates.storage_per_gb_h`. Same split-mode behaviour as `compute_cost_est`. |
| `branches_root_cost_est` | USD | Compute + storage cost attributed to root branches (`parent_id is null`). Always 0 when `split_branches_root_child=false`. |
| `branches_child_cost_est` | USD | Compute + storage cost attributed to child branches (`parent_id is not null`). Always 0 when `split_branches_root_child=false`. |
| `data_transfer_cost_est` | USD | overage GB × `rates.transfer_per_gb`. |
| `extra_branches_cost_est` | USD | `branch_count_extra × rates.branch_per_unit`. |
| `total_cost_est` | USD | Sum of the six above. Stays consistent regardless of split-mode setting (split mode only redistributes compute + storage into the root/child buckets; it does not add or remove dollars). |

Every `*_cost_est` carries attributes `is_estimate: true`, `rate_table_version: <YYYY-MM-DD>`, `source: "client-side computation"`.

### 5.3 Spending Limit

| Sensor | Unit | Notes |
|---|---|---|
| `spending_limit` | USD | `spending_limit_cents / 100`; `unknown` when API returns null / 403. |
| `spending_limit_used_pct` | % | `total_cost_est / spending_limit × 100`; can exceed 100. `unknown` if no limit set. |

### 5.4 Local-Currency Mirrors

When `currency` and `fx_rate_usd_to_local` are set in options, mirror every `*_cost_est` and `spending_limit` sensor as `<name>_<ccy>` (e.g. `total_cost_est_nzd`). Conversion applied at sensor read time; not stored in coordinator state.

### 5.5 Metadata Entity

A single `sensor.<scope_label>_status` entity exposes textual state (`ok`, `degraded`, `auth_error`) and rich attributes: `period_start`, `period_end`, `plan`, `last_updated`, `currency`, `rate_table_version`. Provides one entity for dashboards to read meta from.

### 5.6 Binary Sensors

| Entity | Trigger | Notes |
|---|---|---|
| `binary_sensor.<scope>_over_limit` | `spending_limit_used_pct > 100` | Fixed. `off` (not `unknown`) when no limit set, so automations stay safe. |
| `binary_sensor.<scope>_threshold_<n>pct` | `used_pct > n` | Dynamic; one per integer threshold in `options.threshold_pcts`. |

## 6. Pricing Model (`pricing.py`)

### 6.1 Rate Table

`RATE_TABLE_VERSION = "2026-06-16"`. Defaults sourced from neon.com/pricing on that date.

| Component | Default | Unit |
|---|---|---|
| `compute_per_cuh` | 0.16 | USD per CU-hour |
| `storage_per_gb_h` | 0.000164 | USD per GB-hour (≈ $0.12/GB-month) |
| `transfer_per_gb` | 0.09 | USD per GB |
| `branch_per_unit` | 0.20 | USD per extra branch (period-prorated) |

### 6.2 Plan Allowances

| Plan | Compute-h | Storage-GB | Branches | Transfer-GB |
|---|---|---|---|---|
| Free | 191.9 | 0.5 | 10 | 5 |
| Launch | 300 | 10 | 500 | 50 |
| Scale | 750 | 50 | 5000 | 1000 |

Custom plans (Business / Enterprise / contract): user supplies allowances in options or accepts that estimates will overstate cost (no included usage). `total_cost_est` still produces a value.

### 6.3 Estimator Contract

```python
def estimate(
    consumption: ScopeConsumption,
    plan: str,
    rates: Rates,
    allowances: Allowances,
    period_hours: float,
) -> dict[str, Decimal]
```

Returns a dict with keys: `compute`, `storage`, `branches_root`, `branches_child`, `data_transfer`, `extra_branches`, `total`. All values are `Decimal` rounded to four decimal places. Sensors expose as `float(value)` with `suggested_display_precision=2`.

All arithmetic uses `Decimal` (via `decimal.Decimal` + `ROUND_HALF_UP`) to avoid float drift on accumulated $ values.

### 6.4 Split-Mode Aggregation

When `split_branches_root_child=true`:
- Fetch per-branch consumption via `/consumption_history/v2/branches`.
- For each branch, look up `parent_id` from the projects/branches endpoint.
- Partition by `parent_id is null` and accumulate compute + storage cost into `branches_root` / `branches_child`. These then **replace** the rolled-up `compute`/`storage` figures in the per-category sensors (which become 0 to avoid double-counting), while `total` stays consistent.

When `split_branches_root_child=false`: `branches_root` and `branches_child` are always 0 and the integration omits per-branch API calls entirely.

### 6.5 FX Conversion

```python
def to_local(usd: Decimal, fx_rate: Decimal) -> Decimal
```

Applied at sensor `native_value` read time, not stored in coordinator state. If `fx_rate` is 0 or `currency` is empty, no mirror sensors are created.

## 7. Configuration Flow

### 7.1 Initial Setup

1. **API key step:** `api_key` (masked), `label` (default `"Neon"`).
2. **Validation:** `GET /users/me` to verify auth. 401 → `errors[base] = invalid_auth`; network error → `cannot_connect`.
3. **Scope selection:** multi-select of `[Personal account, org1, org2, ...]`. Default: all checked.
4. **Plan override:** auto-detect per scope; prompt only if plan ∉ {free, launch, scale}.
5. **Unique ID:** `sha256(api_key)[:16]` to block duplicate entries.

### 7.2 Options Flow

Single re-entrant form persisted on `entry.options`:

| Field | Default | Validation |
|---|---|---|
| `update_interval_min` | 15 | int in [5, 1440] |
| `split_branches_root_child` | `false` | bool |
| `currency` | `""` | ISO 4217 alpha-3, uppercase, or empty |
| `fx_rate_usd_to_local` | `0.0` | float ≥ 0; required if `currency` is set |
| `threshold_pcts` | `[]` | list[int] in [1, 500], deduped, sorted |
| `rates.*` | per §6.1 | float > 0 |
| `allowances.<plan>.*` | per §6.2 | float ≥ 0; only shown for plans in use |

Changing options triggers `async_reload_entry`. If only the threshold list changed, entity registry adds/removes the affected binary sensors without unloading the coordinator.

## 8. Error Handling & Edge Cases

| Condition | Behaviour |
|---|---|
| `401 Unauthorized` | Raise `ConfigEntryAuthFailed` → HA reauth flow preserves the entry. |
| `403` on `/billing/spending_limit` | Log debug once per session; set `spending_limit = None`; over_limit binary_sensor stays `off`. |
| `429 Too Many Requests` | Exponential backoff with jitter; raise `UpdateFailed`. Sensors go `unavailable` until next interval. |
| `5xx` / network timeout | `UpdateFailed`. |
| Partial fetch | Return available data; affected sensors → `unknown`; log warning; status entity = `degraded`. |
| Plan downgrade mid-period | Re-detect plan every refresh; allowances follow the *current* plan. |
| Billing period rollover | Recompute period bounds on every refresh. Consumption endpoint returns cumulative for current period, so HA restart mid-period is safe. |
| Custom / unknown plan | Allowances default to 0 (no included usage). User can override. |
| `fx_rate=0` with `currency` set | Options-flow validation error. |
| `split_branches_root_child` toggled | Entity registry adds/removes the four affected sensors; no full reload. |
| Duplicate API key | Config flow blocked by `unique_id` collision. |

## 9. Testing Strategy

- `pytest-homeassistant-custom-component` for HA fixtures.
- `aioresponses` for HTTP mocking (HA-standard, async-safe).
- `tests/test_pricing.py` — table-driven: each plan × {under allowance, at allowance, 50% over, 100% over, no limit, custom plan}. Property test: `total == sum(categories)` for all inputs.
- `tests/test_api.py` — auth header build, period param construction, 401 / 403 / 429 / 5xx handling, partial-fetch behaviour.
- `tests/test_config_flow.py` — happy path, invalid auth, network error, duplicate key, multi-scope selection, plan override prompt.
- `tests/test_coordinator.py` — full refresh, partial failure, period rollover detection, scope addition/removal.
- Snapshot test on a canned fixture: Launch plan, 1 org, 3 projects, ~50% spending-limit utilisation → assert the full sensor state dict. Guards against silent estimation regressions.
- CI: GitHub Actions matrix on Python 3.12 and 3.13. Steps: `ruff check`, `mypy --strict` on `pricing.py` and `api.py`, full pytest, `hassfest` validator, HACS validation action.
- Manual smoke checklist in `docs/INSTALL.md`: install via HACS, add key, verify all sensors render, trigger over_limit by lowering limit, screenshot of dashboard card.

## 10. Open Assumptions

- Neon's `compute_time_seconds` already accounts for autoscaling Compute Units (the official metric). If a future Neon change splits CU-seconds into a separate field, `pricing.estimate` needs updating.
- The `quota_reset_at_last + 1 month` heuristic for period bounds matches Neon's billing-cycle definition (monthly, anchored on first paid signup). If Neon ever introduces non-monthly cycles, period detection breaks.
- Free-plan accounts have no `spending_limit` endpoint; the absence of the limit is treated as "unlimited" semantically (over_limit always `off`).
- Org API keys with read-only role can call all required endpoints. To be verified during implementation; if not, README will require admin-level keys.
- The Neon API counts data transfer in bytes regardless of source/destination. The "Public network transfer" billing line maps to the `data_transfer_bytes` metric (assumption pending implementation-time verification against a live account).

## 11. Success Criteria

1. After installing the integration and entering a valid Neon API key, the user sees one HA device per selected scope and all numeric sensors populate within one update interval.
2. `total_cost_est` is within ±15% of the Neon dashboard's "Charges to date" figure for the same period on a Launch-plan account with mixed compute, storage, and branch usage.
3. `binary_sensor.<scope>_over_limit` flips to `on` within one update interval after `total_cost_est` exceeds `spending_limit`.
4. Adding a second Neon API key creates a second config entry with fully independent sensors and devices.
5. CI (lint, type, tests, hassfest, HACS validation) passes on the first push of the repository.
6. README documents the estimate caveat prominently (top of the file, not buried).
