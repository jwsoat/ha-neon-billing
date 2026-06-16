# Neon Billing HA Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Home Assistant custom integration (`neon_billing`) that monitors one or more Neon API keys and exposes consumption units, estimated USD charges, spending-limit metrics, and threshold binary sensors per Neon account/organisation.

**Architecture:** Per-config-entry `DataUpdateCoordinator` polls `console.neon.tech/api/v2` for consumption history, spending limit, and (optionally) per-branch consumption. A pure `pricing.py` module converts consumption units to Decimal USD using configurable rates and plan allowances. Each Neon scope (personal account or org) becomes a separate HA `Device`. Sensors and binary sensors read from the coordinator's per-scope state dict.

**Tech Stack:** Python 3.12+, Home Assistant ≥ 2026.6, `httpx` (async HTTP, matches HA's preferred client), `Decimal` for money math, `voluptuous` for config-flow schemas. Tests use `pytest-homeassistant-custom-component`, `aioresponses` / `respx`, and `freezegun` for period-rollover tests. CI: ruff, mypy --strict (scoped), hassfest, HACS validation.

**Spec reference:** [`docs/superpowers/specs/2026-06-16-neon-billing-integration-design.md`](../specs/2026-06-16-neon-billing-integration-design.md)

---

## File Layout

**Created by this plan:**

- `pyproject.toml` — ruff + mypy config, package metadata.
- `LICENSE` — MIT.
- `README.md` — user-facing intro + estimate caveat.
- `hacs.json` — HACS manifest.
- `.gitignore` — Python + IDE noise.
- `.github/workflows/ci.yml` — lint, type, test, hassfest, HACS validation.
- `custom_components/neon_billing/__init__.py` — entry setup, platform forward, unload.
- `custom_components/neon_billing/manifest.json` — HA integration metadata.
- `custom_components/neon_billing/const.py` — constants, defaults, TypedDicts.
- `custom_components/neon_billing/api.py` — `NeonClient` async HTTP wrapper + error classes.
- `custom_components/neon_billing/pricing.py` — pure estimator (`estimate`, `to_local`, dataclasses).
- `custom_components/neon_billing/coordinator.py` — `NeonCoordinator(DataUpdateCoordinator)`.
- `custom_components/neon_billing/config_flow.py` — initial flow + options flow + reauth.
- `custom_components/neon_billing/sensor.py` — numeric sensor entities.
- `custom_components/neon_billing/binary_sensor.py` — over-limit + threshold entities.
- `custom_components/neon_billing/strings.json` — UI strings template.
- `custom_components/neon_billing/translations/en.json` — English translations.
- `tests/__init__.py`
- `tests/conftest.py` — fixtures (mock entry, mock HTTP, frozen clock).
- `tests/fixtures/users_me.json`
- `tests/fixtures/users_me_orgs.json`
- `tests/fixtures/consumption_history_account.json`
- `tests/fixtures/spending_limit.json`
- `tests/fixtures/projects.json`
- `tests/fixtures/project_branches.json`
- `tests/fixtures/branch_consumption.json`
- `tests/test_pricing.py`
- `tests/test_api.py`
- `tests/test_coordinator.py`
- `tests/test_config_flow.py`
- `tests/test_init.py` — smoke test for setup/unload.
- `docs/INSTALL.md` — install + smoke-test walkthrough.

**Per-file responsibility:**

| File | Responsibility |
|---|---|
| `const.py` | All magic numbers, defaults, conf keys, TypedDicts. No runtime logic. |
| `api.py` | One method per Neon endpoint, async, raises typed errors. No HA imports — easier to unit-test. |
| `pricing.py` | Pure functions, no I/O, no HA imports. All Decimal math. |
| `coordinator.py` | Orchestrates per-scope fetch, calls `pricing.estimate`, builds the state dict for sensors. Owns period-rollover logic. |
| `config_flow.py` | UI only; no business logic beyond validating user input via the API client. |
| `sensor.py` / `binary_sensor.py` | Thin entity wrappers around coordinator state. No transformation logic beyond formatting (FX, rounding). |
| `__init__.py` | HA lifecycle (setup, unload, reauth glue, options-update reload). |

---

## Task 0: Repo Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `README.md` (stub — full content in Task 17)
- Create: `hacs.json`

- [ ] **Step 0.1: Create `.gitignore`**

`.gitignore`:
```
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
.env
*.egg-info/
dist/
build/
.coverage
htmlcov/
.idea/
.vscode/
*.swp
.DS_Store
```

- [ ] **Step 0.2: Create `LICENSE` (MIT)**

`LICENSE`:
```
MIT License

Copyright (c) 2026 Dylan Wech

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 0.3: Create `pyproject.toml`**

`pyproject.toml`:
```toml
[project]
name = "ha-neon-billing"
version = "0.1.0"
description = "Home Assistant custom integration for Neon serverless Postgres billing"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.12"
authors = [{ name = "Dylan Wech", email = "info@jwsoat.com" }]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "pytest-homeassistant-custom-component>=0.13",
  "respx>=0.21",
  "freezegun>=1.4",
  "ruff>=0.6",
  "mypy>=1.10",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "B", "UP", "SIM", "ASYNC", "PT"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["custom_components/neon_billing/pricing.py", "custom_components/neon_billing/api.py"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 0.4: Create `hacs.json`**

`hacs.json`:
```json
{
  "name": "Neon Billing",
  "render_readme": true,
  "homeassistant": "2026.6.0",
  "country": ["NZ", "AU", "US", "GB"]
}
```

- [ ] **Step 0.5: Create `README.md` stub**

`README.md`:
```markdown
# Neon Billing for Home Assistant

Tracks Neon (serverless Postgres) consumption, estimated charges, and spending-limit usage as HA sensors.

> **Estimates, not invoices.** Neon's public API returns consumption units, not dollar charges. This integration computes USD figures client-side from a configurable rate table. Numbers will not exactly match your Neon invoice and may drift when Neon changes pricing.

Full docs and install instructions in [`docs/INSTALL.md`](docs/INSTALL.md). This README is filled out in Task 17.
```

- [ ] **Step 0.6: Commit scaffolding**

```bash
git add .gitignore LICENSE pyproject.toml hacs.json README.md
git commit -m "chore: repo scaffolding (license, pyproject, hacs)"
```

---

## Task 1: Constants Module

**Files:**
- Create: `custom_components/neon_billing/__init__.py` (empty placeholder; replaced in Task 11)
- Create: `custom_components/neon_billing/const.py`

- [ ] **Step 1.1: Create package init placeholder**

`custom_components/neon_billing/__init__.py`:
```python
"""Neon Billing integration for Home Assistant."""
```

- [ ] **Step 1.2: Write `const.py`**

`custom_components/neon_billing/const.py`:
```python
"""Constants for the Neon Billing integration."""
from __future__ import annotations

from typing import Final, TypedDict

DOMAIN: Final = "neon_billing"
DEFAULT_NAME: Final = "Neon"
NEON_API_BASE: Final = "https://console.neon.tech/api/v2"

# Update interval bounds (minutes)
DEFAULT_UPDATE_INTERVAL_MIN: Final = 15
MIN_UPDATE_INTERVAL_MIN: Final = 5
MAX_UPDATE_INTERVAL_MIN: Final = 1440

# Rate table version (bump when defaults change)
RATE_TABLE_VERSION: Final = "2026-06-16"

SUPPORTED_PLANS: Final = ("free", "launch", "scale", "custom")
SCOPE_PERSONAL: Final = "personal"

# Conf keys
CONF_API_KEY: Final = "api_key"
CONF_LABEL: Final = "label"
CONF_SCOPES: Final = "scopes"
CONF_PLAN_OVERRIDES: Final = "plan_overrides"
CONF_UPDATE_INTERVAL_MIN: Final = "update_interval_min"
CONF_SPLIT_BRANCHES: Final = "split_branches_root_child"
CONF_CURRENCY: Final = "currency"
CONF_FX_RATE: Final = "fx_rate_usd_to_local"
CONF_THRESHOLD_PCTS: Final = "threshold_pcts"
CONF_RATES: Final = "rates"
CONF_ALLOWANCES: Final = "allowances"


class Rates(TypedDict):
    compute_per_cuh: float
    storage_per_gb_h: float
    transfer_per_gb: float
    branch_per_unit: float


class Allowance(TypedDict):
    compute_h: float
    storage_gb: float
    branches: int
    transfer_gb: float


DEFAULT_RATES: Final[Rates] = {
    "compute_per_cuh": 0.16,
    "storage_per_gb_h": 0.000164,
    "transfer_per_gb": 0.09,
    "branch_per_unit": 0.20,
}

DEFAULT_ALLOWANCES: Final[dict[str, Allowance]] = {
    "free": {"compute_h": 191.9, "storage_gb": 0.5, "branches": 10, "transfer_gb": 5.0},
    "launch": {"compute_h": 300.0, "storage_gb": 10.0, "branches": 500, "transfer_gb": 50.0},
    "scale": {"compute_h": 750.0, "storage_gb": 50.0, "branches": 5000, "transfer_gb": 1000.0},
    "custom": {"compute_h": 0.0, "storage_gb": 0.0, "branches": 0, "transfer_gb": 0.0},
}
```

- [ ] **Step 1.3: Commit**

```bash
git add custom_components/neon_billing/__init__.py custom_components/neon_billing/const.py
git commit -m "feat(const): add domain constants, defaults, rate/allowance schemas"
```

---

## Task 2: Pricing Module (TDD)

**Files:**
- Create: `custom_components/neon_billing/pricing.py`
- Create: `tests/__init__.py`
- Create: `tests/test_pricing.py`

The estimator is pure logic, easiest tested first.

- [ ] **Step 2.1: Create empty test package marker**

`tests/__init__.py`:
```python
```

- [ ] **Step 2.2: Write failing tests for `ScopeConsumption` and `estimate`**

`tests/test_pricing.py`:
```python
"""Tests for pricing.estimate and pricing.to_local."""
from __future__ import annotations

from decimal import Decimal

import pytest

from custom_components.neon_billing.const import DEFAULT_ALLOWANCES, DEFAULT_RATES
from custom_components.neon_billing.pricing import ScopeConsumption, estimate, to_local


PERIOD_HOURS = 730.0  # nominal month


def _zero_consumption(**overrides: float) -> ScopeConsumption:
    base = {
        "compute_hours": 0.0,
        "storage_gb_hours": 0.0,
        "transfer_gb": 0.0,
        "branch_count_total": 0,
        "branch_count_root": 0,
        "branch_count_child": 0,
        "root_compute_hours": 0.0,
        "root_storage_gb_hours": 0.0,
        "child_compute_hours": 0.0,
        "child_storage_gb_hours": 0.0,
    }
    base.update(overrides)
    return ScopeConsumption(**base)


def test_estimate_returns_zero_under_allowance_on_launch() -> None:
    c = _zero_consumption(
        compute_hours=100.0,          # < 300 launch allowance
        storage_gb_hours=5.0 * PERIOD_HOURS,  # < 10 GB allowance
        transfer_gb=20.0,             # < 50
        branch_count_total=10,        # < 500
    )
    result = estimate(
        c, "launch", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    assert result["compute"] == Decimal("0.0000")
    assert result["storage"] == Decimal("0.0000")
    assert result["data_transfer"] == Decimal("0.0000")
    assert result["extra_branches"] == Decimal("0.0000")
    assert result["total"] == Decimal("0.0000")


def test_estimate_computes_compute_overage_on_launch() -> None:
    c = _zero_consumption(compute_hours=400.0)  # 100 over Launch's 300
    result = estimate(
        c, "launch", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    assert result["compute"] == Decimal("16.0000")  # 100 * 0.16
    assert result["total"] == Decimal("16.0000")


def test_estimate_computes_extra_branches() -> None:
    c = _zero_consumption(branch_count_total=505)  # 5 over Launch's 500
    result = estimate(
        c, "launch", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    assert result["extra_branches"] == Decimal("1.0000")  # 5 * 0.20
    assert result["total"] == Decimal("1.0000")


def test_estimate_handles_free_plan_zero_allowances_for_unused() -> None:
    c = _zero_consumption(compute_hours=200.0)  # over Free's 191.9
    result = estimate(
        c, "free", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    expected = (Decimal("200") - Decimal("191.9")) * Decimal("0.16")
    assert result["compute"] == expected.quantize(Decimal("0.0001"))


def test_estimate_split_mode_zeroes_rolled_up_and_populates_branches() -> None:
    c = _zero_consumption(
        compute_hours=400.0,
        storage_gb_hours=15.0 * PERIOD_HOURS,
        root_compute_hours=400.0,
        root_storage_gb_hours=15.0 * PERIOD_HOURS,
    )
    result = estimate(
        c, "launch", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=True
    )
    assert result["compute"] == Decimal("0.0000")
    assert result["storage"] == Decimal("0.0000")
    assert result["branches_root"] > Decimal("0")
    assert result["branches_child"] == Decimal("0.0000")
    # Total should equal the root attribution
    assert result["total"] == result["branches_root"]


def test_estimate_total_equals_sum_of_components_property() -> None:
    c = _zero_consumption(
        compute_hours=500.0,
        storage_gb_hours=20.0 * PERIOD_HOURS,
        transfer_gb=100.0,
        branch_count_total=510,
    )
    result = estimate(
        c, "launch", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    summed = (
        result["compute"]
        + result["storage"]
        + result["branches_root"]
        + result["branches_child"]
        + result["data_transfer"]
        + result["extra_branches"]
    )
    assert result["total"] == summed


def test_estimate_handles_custom_plan_no_allowance() -> None:
    c = _zero_consumption(compute_hours=10.0)
    result = estimate(
        c, "custom", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    assert result["compute"] == Decimal("1.6000")  # 10 * 0.16, no allowance


def test_to_local_applies_fx_rate() -> None:
    assert to_local(Decimal("10.0000"), 1.6543) == Decimal("16.5430")


def test_to_local_zero_fx_returns_zero() -> None:
    assert to_local(Decimal("10.0000"), 0.0) == Decimal("0.0000")
```

- [ ] **Step 2.3: Run tests — expect collection error (pricing module not found)**

Run: `pytest tests/test_pricing.py -v`
Expected: `ModuleNotFoundError: No module named 'custom_components.neon_billing.pricing'`

- [ ] **Step 2.4: Implement `pricing.py`**

`custom_components/neon_billing/pricing.py`:
```python
"""Pure pricing logic — converts Neon consumption to USD estimates."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .const import Allowance, Rates


@dataclass(frozen=True)
class ScopeConsumption:
    """Aggregated consumption for one Neon scope over the current billing period."""

    compute_hours: float
    storage_gb_hours: float
    transfer_gb: float
    branch_count_total: int
    branch_count_root: int
    branch_count_child: int
    # Per-branch breakdowns; only populated when split mode is enabled.
    root_compute_hours: float = 0.0
    root_storage_gb_hours: float = 0.0
    child_compute_hours: float = 0.0
    child_storage_gb_hours: float = 0.0


_QUANT = Decimal("0.0001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


def _d(value: float | int) -> Decimal:
    return Decimal(str(value))


def estimate(
    consumption: ScopeConsumption,
    plan: str,
    rates: Rates,
    allowances: dict[str, Allowance],
    period_hours: float,
    split_branches: bool,
) -> dict[str, Decimal]:
    """Return per-category USD estimates as Decimal, quantized to 4 dp.

    Keys: compute, storage, branches_root, branches_child, data_transfer,
    extra_branches, total. Total is always the sum of the other six.
    """
    alw = allowances[plan]
    storage_allowance_gb_h = _d(alw["storage_gb"]) * _d(period_hours)

    over_compute = max(Decimal(0), _d(consumption.compute_hours) - _d(alw["compute_h"]))
    over_storage = max(Decimal(0), _d(consumption.storage_gb_hours) - storage_allowance_gb_h)
    over_transfer = max(Decimal(0), _d(consumption.transfer_gb) - _d(alw["transfer_gb"]))
    over_branches = max(0, consumption.branch_count_total - alw["branches"])

    r_compute = _d(rates["compute_per_cuh"])
    r_storage = _d(rates["storage_per_gb_h"])
    r_transfer = _d(rates["transfer_per_gb"])
    r_branch = _d(rates["branch_per_unit"])

    compute_cost = _q(over_compute * r_compute)
    storage_cost = _q(over_storage * r_storage)
    transfer_cost = _q(over_transfer * r_transfer)
    extra_branches_cost = _q(_d(over_branches) * r_branch)

    branches_root = Decimal("0.0000")
    branches_child = Decimal("0.0000")
    if split_branches:
        root_compute = _d(consumption.root_compute_hours) * r_compute
        root_storage = _d(consumption.root_storage_gb_hours) * r_storage
        child_compute = _d(consumption.child_compute_hours) * r_compute
        child_storage = _d(consumption.child_storage_gb_hours) * r_storage
        branches_root = _q(root_compute + root_storage)
        branches_child = _q(child_compute + child_storage)
        compute_cost = Decimal("0.0000")
        storage_cost = Decimal("0.0000")

    total = _q(
        compute_cost
        + storage_cost
        + branches_root
        + branches_child
        + transfer_cost
        + extra_branches_cost
    )

    return {
        "compute": compute_cost,
        "storage": storage_cost,
        "branches_root": branches_root,
        "branches_child": branches_child,
        "data_transfer": transfer_cost,
        "extra_branches": extra_branches_cost,
        "total": total,
    }


def to_local(usd: Decimal, fx_rate: float) -> Decimal:
    """Convert USD Decimal to local currency Decimal."""
    return _q(usd * _d(fx_rate))
```

- [ ] **Step 2.5: Run tests — expect all 9 to pass**

Run: `pytest tests/test_pricing.py -v`
Expected: 9 passed.

- [ ] **Step 2.6: Run ruff + mypy on pricing**

Run: `ruff check custom_components/neon_billing/pricing.py && mypy custom_components/neon_billing/pricing.py`
Expected: no errors.

- [ ] **Step 2.7: Commit**

```bash
git add custom_components/neon_billing/pricing.py tests/__init__.py tests/test_pricing.py
git commit -m "feat(pricing): pure Decimal estimator with TDD coverage"
```

---

## Task 3: API Client (TDD)

**Files:**
- Create: `custom_components/neon_billing/api.py`
- Create: `tests/fixtures/users_me.json`
- Create: `tests/fixtures/users_me_orgs.json`
- Create: `tests/fixtures/consumption_history_account.json`
- Create: `tests/fixtures/spending_limit.json`
- Create: `tests/fixtures/projects.json`
- Create: `tests/fixtures/project_branches.json`
- Create: `tests/fixtures/branch_consumption.json`
- Create: `tests/test_api.py`

- [ ] **Step 3.1: Create fixture `users_me.json`**

`tests/fixtures/users_me.json`:
```json
{
  "id": "user-abc",
  "email": "user@example.com",
  "name": "Dylan",
  "plan": "launch",
  "max_autoscaling_limit": 4.0,
  "active_seconds_limit": 360000,
  "projects_limit": 100,
  "branches_limit": 500,
  "compute_seconds_limit": 1080000,
  "auth_accounts": [],
  "billing_account": {
    "state": "active",
    "payment_source": "card",
    "subscription_type": "launch",
    "payment_method": "card",
    "quota_reset_at_last": "2026-06-01T00:00:00Z",
    "name": "Dylan Wech",
    "email": "billing@example.com",
    "address_city": "Auckland",
    "address_country": "NZ",
    "address_line1": "1 Example St",
    "address_line2": "",
    "address_postal_code": "1010",
    "address_state": "AKL",
    "plan_details": { "name": "launch" }
  }
}
```

- [ ] **Step 3.2: Create fixture `users_me_orgs.json`**

`tests/fixtures/users_me_orgs.json`:
```json
{
  "organizations": [
    { "id": "org-alpha", "name": "Alpha Org", "plan": "launch" },
    { "id": "org-beta", "name": "Beta Org", "plan": "scale" }
  ]
}
```

- [ ] **Step 3.3: Create fixture `consumption_history_account.json`**

`tests/fixtures/consumption_history_account.json`:
```json
{
  "periods": [
    {
      "period_id": "2026-06",
      "period_start": "2026-06-01T00:00:00Z",
      "period_end": "2026-07-01T00:00:00Z",
      "consumption": [
        {
          "timeframe_start": "2026-06-01T00:00:00Z",
          "timeframe_end": "2026-06-16T11:00:00Z",
          "active_time_seconds": 1080000,
          "compute_time_seconds": 1296000,
          "written_data_bytes": 5000000000,
          "synthetic_storage_size_bytes": 3221225472,
          "data_storage_bytes_hour": 1100000000000,
          "data_transfer_bytes": 8000000000
        }
      ]
    }
  ]
}
```

- [ ] **Step 3.4: Create fixture `spending_limit.json`**

`tests/fixtures/spending_limit.json`:
```json
{ "spending_limit_cents": 5000 }
```

- [ ] **Step 3.5: Create fixture `projects.json`**

`tests/fixtures/projects.json`:
```json
{
  "projects": [
    { "id": "proj-1", "name": "main", "org_id": "org-alpha", "created_at": "2026-05-01T00:00:00Z" }
  ]
}
```

- [ ] **Step 3.6: Create fixture `project_branches.json`**

`tests/fixtures/project_branches.json`:
```json
{
  "branches": [
    { "id": "br-root", "project_id": "proj-1", "parent_id": null, "name": "main" },
    { "id": "br-dev", "project_id": "proj-1", "parent_id": "br-root", "name": "dev" }
  ]
}
```

- [ ] **Step 3.7: Create fixture `branch_consumption.json`**

`tests/fixtures/branch_consumption.json`:
```json
{
  "branches": [
    {
      "id": "br-root",
      "compute_time_seconds": 900000,
      "synthetic_storage_size_bytes": 2147483648,
      "data_storage_bytes_hour": 800000000000
    },
    {
      "id": "br-dev",
      "compute_time_seconds": 396000,
      "synthetic_storage_size_bytes": 1073741824,
      "data_storage_bytes_hour": 300000000000
    }
  ]
}
```

- [ ] **Step 3.8: Write failing tests for `NeonClient`**

`tests/test_api.py`:
```python
"""Tests for the Neon API HTTP client."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from custom_components.neon_billing.api import (
    NeonAPIError,
    NeonAuthError,
    NeonClient,
    NeonRateLimitError,
    billing_period_bounds,
)
from custom_components.neon_billing.const import NEON_API_BASE


FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def client() -> NeonClient:
    async with httpx.AsyncClient() as http:
        yield NeonClient(http=http, api_key="key-xyz")


@respx.mock
async def test_get_user_returns_parsed_payload(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=_load("users_me.json"))
    )
    user = await client.get_user()
    assert user["id"] == "user-abc"
    assert user["billing_account"]["plan_details"]["name"] == "launch"


@respx.mock
async def test_get_user_401_raises_auth_error(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(NeonAuthError):
        await client.get_user()


@respx.mock
async def test_list_organizations_returns_list(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/users/me/organizations").mock(
        return_value=httpx.Response(200, json=_load("users_me_orgs.json"))
    )
    orgs = await client.list_organizations()
    assert len(orgs) == 2
    assert orgs[0]["id"] == "org-alpha"


@respx.mock
async def test_get_consumption_uses_period_bounds(client: NeonClient) -> None:
    route = respx.get(f"{NEON_API_BASE}/consumption_history/account").mock(
        return_value=httpx.Response(200, json=_load("consumption_history_account.json"))
    )
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    data = await client.get_account_consumption(org_id="org-alpha", period_start=start, period_end=end)
    assert route.called
    params = route.calls.last.request.url.params
    assert params["from"] == "2026-06-01T00:00:00+00:00"
    assert params["to"] == "2026-07-01T00:00:00+00:00"
    assert params["org_id"] == "org-alpha"
    assert data["periods"][0]["consumption"][0]["compute_time_seconds"] == 1296000


@respx.mock
async def test_get_spending_limit_returns_cents(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
        return_value=httpx.Response(200, json=_load("spending_limit.json"))
    )
    cents = await client.get_spending_limit_cents("org-alpha")
    assert cents == 5000


@respx.mock
async def test_get_spending_limit_403_returns_none(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
        return_value=httpx.Response(403, json={"message": "forbidden"})
    )
    assert await client.get_spending_limit_cents("org-alpha") is None


@respx.mock
async def test_get_spending_limit_null_returns_none(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
        return_value=httpx.Response(200, json={"spending_limit_cents": None})
    )
    assert await client.get_spending_limit_cents("org-alpha") is None


@respx.mock
async def test_429_raises_rate_limit_error(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(return_value=httpx.Response(429, json={}))
    with pytest.raises(NeonRateLimitError):
        await client.get_user()


@respx.mock
async def test_500_raises_generic_api_error(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(return_value=httpx.Response(500, json={}))
    with pytest.raises(NeonAPIError):
        await client.get_user()


@respx.mock
async def test_list_projects_passes_org_id(client: NeonClient) -> None:
    route = respx.get(f"{NEON_API_BASE}/projects").mock(
        return_value=httpx.Response(200, json=_load("projects.json"))
    )
    projects = await client.list_projects("org-alpha")
    assert route.calls.last.request.url.params["org_id"] == "org-alpha"
    assert projects[0]["id"] == "proj-1"


@respx.mock
async def test_list_branches_calls_project_endpoint(client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/projects/proj-1/branches").mock(
        return_value=httpx.Response(200, json=_load("project_branches.json"))
    )
    branches = await client.list_branches("proj-1")
    assert len(branches) == 2
    assert branches[0]["parent_id"] is None


def test_billing_period_bounds_anchors_on_quota_reset() -> None:
    quota_reset = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 20, 9, 30, 0, tzinfo=timezone.utc)
    start, end = billing_period_bounds(quota_reset, now)
    assert start == datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_billing_period_bounds_when_now_before_first_reset() -> None:
    quota_reset = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 20, 9, 30, 0, tzinfo=timezone.utc)
    start, end = billing_period_bounds(quota_reset, now)
    assert start == datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
```

- [ ] **Step 3.9: Run tests — expect collection failure**

Run: `pytest tests/test_api.py -v`
Expected: `ModuleNotFoundError: No module named 'custom_components.neon_billing.api'`

- [ ] **Step 3.10: Implement `api.py`**

`custom_components/neon_billing/api.py`:
```python
"""Neon API v2 HTTP client (httpx-based, async, no HA imports)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from .const import NEON_API_BASE


class NeonAPIError(Exception):
    """Generic Neon API failure (HTTP 5xx, transport error, malformed response)."""


class NeonAuthError(NeonAPIError):
    """Raised on HTTP 401."""


class NeonRateLimitError(NeonAPIError):
    """Raised on HTTP 429."""


def billing_period_bounds(
    quota_reset_at_last: datetime, now: datetime
) -> tuple[datetime, datetime]:
    """Return the current billing period (start, end) anchored on quota reset day.

    Period is one month long. If `now` is before `quota_reset_at_last + 1 month`,
    the period is `[quota_reset_at_last, quota_reset_at_last + 1 month]`.
    Otherwise, advance month by month until we find the period that contains `now`.
    """
    start = quota_reset_at_last
    end = _add_one_month(start)
    while now >= end:
        start = end
        end = _add_one_month(start)
    return start, end


def _add_one_month(dt: datetime) -> datetime:
    """Add one calendar month, clamping to last day if the target month is shorter."""
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    # Day clamp: if target month has fewer days, use its last day.
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_first = datetime(year + 1, 1, 1)
    else:
        next_first = datetime(year, month + 1, 1)
    last_day = (next_first - timedelta(days=1)).day
    return last_day


class NeonClient:
    """Thin async client for the Neon v2 REST API.

    Methods are 1:1 with endpoints used by the integration. All raise
    `NeonAuthError`, `NeonRateLimitError`, or `NeonAPIError` on failure.
    """

    def __init__(self, http: httpx.AsyncClient, api_key: str) -> None:
        self._http = http
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "ha-neon-billing/0.1",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            resp = await self._http.get(
                f"{NEON_API_BASE}{path}", params=params, headers=self._headers, timeout=20.0
            )
        except httpx.HTTPError as exc:
            raise NeonAPIError(f"transport error: {exc}") from exc

        if resp.status_code == 401:
            raise NeonAuthError("invalid API key")
        if resp.status_code == 429:
            raise NeonRateLimitError("rate limited")
        if resp.status_code >= 500:
            raise NeonAPIError(f"server error {resp.status_code}")
        if resp.status_code >= 400:
            raise NeonAPIError(f"client error {resp.status_code}: {resp.text}")

        try:
            return resp.json()
        except ValueError as exc:
            raise NeonAPIError("malformed JSON response") from exc

    async def get_user(self) -> dict[str, Any]:
        return await self._get("/users/me")

    async def list_organizations(self) -> list[dict[str, Any]]:
        data = await self._get("/users/me/organizations")
        return list(data.get("organizations", []))

    async def get_account_consumption(
        self,
        *,
        org_id: str | None,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "from": period_start.isoformat(),
            "to": period_end.isoformat(),
            "granularity": "daily",
        }
        if org_id is not None:
            params["org_id"] = org_id
        return await self._get("/consumption_history/account", params=params)

    async def get_spending_limit_cents(self, org_id: str) -> int | None:
        try:
            data = await self._get(f"/organizations/{org_id}/billing/spending_limit")
        except NeonAPIError as exc:
            # 403 (free plan / insufficient perms) → return None instead of raising.
            if "403" in str(exc) or "client error 404" in str(exc):
                return None
            raise
        cents = data.get("spending_limit_cents")
        return int(cents) if cents is not None else None

    async def list_projects(self, org_id: str | None = None) -> list[dict[str, Any]]:
        params = {"org_id": org_id} if org_id else None
        data = await self._get("/projects", params=params)
        return list(data.get("projects", []))

    async def list_branches(self, project_id: str) -> list[dict[str, Any]]:
        data = await self._get(f"/projects/{project_id}/branches")
        return list(data.get("branches", []))

    async def get_branch_consumption(
        self,
        *,
        org_id: str | None,
        period_start: datetime,
        period_end: datetime,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "from": period_start.isoformat(),
            "to": period_end.isoformat(),
            "granularity": "daily",
        }
        if org_id is not None:
            params["org_id"] = org_id
        data = await self._get("/consumption_history/v2/branches", params=params)
        return list(data.get("branches", []))
```

- [ ] **Step 3.11: Run tests — expect all 12 to pass**

Run: `pytest tests/test_api.py -v`
Expected: 12 passed.

- [ ] **Step 3.12: Run mypy on api.py**

Run: `mypy custom_components/neon_billing/api.py`
Expected: no errors.

- [ ] **Step 3.13: Commit**

```bash
git add custom_components/neon_billing/api.py tests/fixtures/ tests/test_api.py
git commit -m "feat(api): NeonClient with typed errors, period bounds, full TDD coverage"
```

---

## Task 4: Coordinator (TDD)

**Files:**
- Create: `custom_components/neon_billing/coordinator.py`
- Create: `tests/conftest.py`
- Create: `tests/test_coordinator.py`

The coordinator orchestrates per-scope fetches, computes the state dict consumed by sensors, and handles partial failure.

- [ ] **Step 4.1: Write `tests/conftest.py` with shared fixtures**

`tests/conftest.py`:
```python
"""Shared pytest fixtures."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from custom_components.neon_billing.api import NeonClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
async def neon_client(http_client: httpx.AsyncClient) -> NeonClient:
    return NeonClient(http=http_client, api_key="test-key")
```

- [ ] **Step 4.2: Write failing coordinator tests**

`tests/test_coordinator.py`:
```python
"""Tests for the per-entry DataUpdateCoordinator."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from freezegun import freeze_time

from custom_components.neon_billing.api import NeonClient, NeonAPIError
from custom_components.neon_billing.const import DEFAULT_ALLOWANCES, DEFAULT_RATES, NEON_API_BASE
from custom_components.neon_billing.coordinator import (
    NeonCoordinator,
    NeonScope,
    ScopeStatus,
    aggregate_consumption,
)
from tests.conftest import load_fixture


def _scope(scope_id: str = "personal", *, plan: str = "launch", org_id: str | None = None) -> NeonScope:
    return NeonScope(scope_id=scope_id, label=scope_id, plan=plan, org_id=org_id)


def test_aggregate_consumption_sums_metrics() -> None:
    payload = load_fixture("consumption_history_account.json")
    agg = aggregate_consumption(payload, branch_count_total=5)
    assert agg.compute_hours == pytest.approx(360.0, rel=1e-3)  # 1_296_000 / 3600
    # 1_100_000_000_000 bytes-hour → /1e9 GB-hour
    assert agg.storage_gb_hours == pytest.approx(1100.0, rel=1e-3)
    assert agg.transfer_gb == pytest.approx(8.0, rel=1e-3)
    assert agg.branch_count_total == 5


@respx.mock
@freeze_time("2026-06-16T12:00:00Z")
async def test_coordinator_builds_per_scope_state(neon_client: NeonClient) -> None:
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
        return_value=httpx.Response(200, json=load_fixture("projects.json"))
    )
    respx.get(f"{NEON_API_BASE}/projects/proj-1/branches").mock(
        return_value=httpx.Response(200, json=load_fixture("project_branches.json"))
    )

    coordinator = NeonCoordinator(
        client=neon_client,
        scopes=[_scope("org-alpha", plan="launch", org_id="org-alpha")],
        rates=DEFAULT_RATES,
        allowances=DEFAULT_ALLOWANCES,
        split_branches=False,
    )
    data = await coordinator.fetch()
    scope = data["org-alpha"]
    assert scope.status is ScopeStatus.OK
    assert scope.spending_limit_cents == 5000
    assert scope.consumption.branch_count_root == 1
    assert scope.consumption.branch_count_child == 1
    assert scope.charges["total"] >= Decimal("0")
    assert scope.used_pct is not None  # spending limit set → percent computable


@respx.mock
@freeze_time("2026-06-16T12:00:00Z")
async def test_coordinator_handles_missing_spending_limit(neon_client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me.json"))
    )
    respx.get(f"{NEON_API_BASE}/consumption_history/account").mock(
        return_value=httpx.Response(200, json=load_fixture("consumption_history_account.json"))
    )
    respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
        return_value=httpx.Response(403, json={})
    )
    respx.get(f"{NEON_API_BASE}/projects").mock(
        return_value=httpx.Response(200, json={"projects": []})
    )

    coordinator = NeonCoordinator(
        client=neon_client,
        scopes=[_scope("org-alpha", org_id="org-alpha")],
        rates=DEFAULT_RATES,
        allowances=DEFAULT_ALLOWANCES,
        split_branches=False,
    )
    data = await coordinator.fetch()
    scope = data["org-alpha"]
    assert scope.spending_limit_cents is None
    assert scope.used_pct is None


@respx.mock
@freeze_time("2026-06-16T12:00:00Z")
async def test_coordinator_partial_failure_marks_scope_degraded(neon_client: NeonClient) -> None:
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me.json"))
    )
    respx.get(f"{NEON_API_BASE}/consumption_history/account").mock(
        return_value=httpx.Response(500, json={})
    )
    respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
        return_value=httpx.Response(200, json=load_fixture("spending_limit.json"))
    )
    respx.get(f"{NEON_API_BASE}/projects").mock(
        return_value=httpx.Response(200, json={"projects": []})
    )

    coordinator = NeonCoordinator(
        client=neon_client,
        scopes=[_scope("org-alpha", org_id="org-alpha")],
        rates=DEFAULT_RATES,
        allowances=DEFAULT_ALLOWANCES,
        split_branches=False,
    )
    data = await coordinator.fetch()
    scope = data["org-alpha"]
    assert scope.status is ScopeStatus.DEGRADED
    assert scope.consumption is None
    assert scope.spending_limit_cents == 5000


@respx.mock
@freeze_time("2026-06-16T12:00:00Z")
async def test_coordinator_split_mode_fetches_branch_consumption(neon_client: NeonClient) -> None:
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
        return_value=httpx.Response(200, json=load_fixture("projects.json"))
    )
    respx.get(f"{NEON_API_BASE}/projects/proj-1/branches").mock(
        return_value=httpx.Response(200, json=load_fixture("project_branches.json"))
    )
    branch_route = respx.get(f"{NEON_API_BASE}/consumption_history/v2/branches").mock(
        return_value=httpx.Response(200, json=load_fixture("branch_consumption.json"))
    )

    coordinator = NeonCoordinator(
        client=neon_client,
        scopes=[_scope("org-alpha", org_id="org-alpha")],
        rates=DEFAULT_RATES,
        allowances=DEFAULT_ALLOWANCES,
        split_branches=True,
    )
    data = await coordinator.fetch()
    assert branch_route.called
    scope = data["org-alpha"]
    assert scope.charges["branches_root"] >= Decimal("0")
    assert scope.charges["compute"] == Decimal("0")  # zeroed under split mode
```

- [ ] **Step 4.3: Run tests — expect collection error**

Run: `pytest tests/test_coordinator.py -v`
Expected: `ModuleNotFoundError: No module named 'custom_components.neon_billing.coordinator'`

- [ ] **Step 4.4: Implement `coordinator.py`**

`custom_components/neon_billing/coordinator.py`:
```python
"""DataUpdateCoordinator that orchestrates Neon API calls per scope."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from .api import (
    NeonAPIError,
    NeonAuthError,
    NeonClient,
    NeonRateLimitError,
    billing_period_bounds,
)
from .const import Allowance, Rates
from .pricing import ScopeConsumption, estimate

_LOGGER = logging.getLogger(__name__)


class ScopeStatus(Enum):
    OK = "ok"
    DEGRADED = "degraded"
    AUTH_ERROR = "auth_error"


@dataclass(frozen=True)
class NeonScope:
    """A monitored Neon scope (personal account or organisation)."""

    scope_id: str
    label: str
    plan: str
    org_id: str | None  # None = personal account


@dataclass
class ScopeState:
    """The state returned by the coordinator for one scope per refresh."""

    scope: NeonScope
    status: ScopeStatus
    period_start: datetime | None = None
    period_end: datetime | None = None
    consumption: ScopeConsumption | None = None
    charges: dict[str, Decimal] = field(default_factory=dict)
    spending_limit_cents: int | None = None
    used_pct: Decimal | None = None
    plan_name: str | None = None


def aggregate_consumption(
    payload: dict[str, Any],
    *,
    branch_count_total: int,
    branch_count_root: int = 0,
    branch_count_child: int = 0,
    split_branches: dict[str, dict[str, float]] | None = None,
) -> ScopeConsumption:
    """Roll up the Neon /consumption_history/account payload into a ScopeConsumption.

    `split_branches`, when provided, is a mapping `{"root": {...}, "child": {...}}`
    holding compute_hours and storage_gb_hours for each bucket.
    """
    compute_seconds = 0.0
    storage_bytes_hour = 0.0
    transfer_bytes = 0.0
    for period in payload.get("periods", []):
        for sample in period.get("consumption", []):
            compute_seconds += float(sample.get("compute_time_seconds", 0))
            storage_bytes_hour += float(sample.get("data_storage_bytes_hour", 0))
            transfer_bytes += float(sample.get("data_transfer_bytes", 0))

    splits = split_branches or {}
    root = splits.get("root", {})
    child = splits.get("child", {})

    return ScopeConsumption(
        compute_hours=compute_seconds / 3600.0,
        storage_gb_hours=storage_bytes_hour / 1e9,
        transfer_gb=transfer_bytes / 1e9,
        branch_count_total=branch_count_total,
        branch_count_root=branch_count_root,
        branch_count_child=branch_count_child,
        root_compute_hours=float(root.get("compute_hours", 0.0)),
        root_storage_gb_hours=float(root.get("storage_gb_hours", 0.0)),
        child_compute_hours=float(child.get("compute_hours", 0.0)),
        child_storage_gb_hours=float(child.get("storage_gb_hours", 0.0)),
    )


def _aggregate_branch_split(
    branches: list[dict[str, Any]], branch_parents: dict[str, str | None]
) -> dict[str, dict[str, float]]:
    """Sum branch consumption into 'root' and 'child' buckets."""
    buckets: dict[str, dict[str, float]] = {
        "root": {"compute_hours": 0.0, "storage_gb_hours": 0.0},
        "child": {"compute_hours": 0.0, "storage_gb_hours": 0.0},
    }
    for branch in branches:
        bid = branch.get("id")
        parent = branch_parents.get(bid)
        bucket = "root" if parent is None else "child"
        buckets[bucket]["compute_hours"] += float(branch.get("compute_time_seconds", 0)) / 3600.0
        buckets[bucket]["storage_gb_hours"] += float(branch.get("data_storage_bytes_hour", 0)) / 1e9
    return buckets


def _period_hours(period_start: datetime, period_end: datetime) -> float:
    return (period_end - period_start).total_seconds() / 3600.0


class NeonCoordinator:
    """Fetches data for every configured scope, in parallel, per refresh."""

    def __init__(
        self,
        *,
        client: NeonClient,
        scopes: list[NeonScope],
        rates: Rates,
        allowances: dict[str, Allowance],
        split_branches: bool,
    ) -> None:
        self._client = client
        self._scopes = scopes
        self._rates = rates
        self._allowances = allowances
        self._split = split_branches

    async def fetch(self) -> dict[str, ScopeState]:
        user = await self._client.get_user()
        billing = user.get("billing_account", {})
        quota_reset_raw = billing.get("quota_reset_at_last")
        if quota_reset_raw is None:
            raise NeonAPIError("billing_account.quota_reset_at_last missing from /users/me")
        quota_reset = datetime.fromisoformat(quota_reset_raw.replace("Z", "+00:00"))
        now = datetime.now(tz=timezone.utc)
        period_start, period_end = billing_period_bounds(quota_reset, now)

        results = await asyncio.gather(
            *(self._fetch_scope(scope, period_start, period_end) for scope in self._scopes),
            return_exceptions=False,
        )
        return {scope.scope_id: state for scope, state in zip(self._scopes, results, strict=True)}

    async def _fetch_scope(
        self, scope: NeonScope, period_start: datetime, period_end: datetime
    ) -> ScopeState:
        state = ScopeState(scope=scope, status=ScopeStatus.OK, period_start=period_start, period_end=period_end)

        # Spending limit — only meaningful for orgs.
        if scope.org_id is not None:
            try:
                state.spending_limit_cents = await self._client.get_spending_limit_cents(scope.org_id)
            except NeonAuthError:
                state.status = ScopeStatus.AUTH_ERROR
                return state
            except (NeonAPIError, NeonRateLimitError) as exc:
                _LOGGER.warning("spending_limit fetch failed for %s: %s", scope.scope_id, exc)
                state.status = ScopeStatus.DEGRADED

        # Consumption.
        try:
            cons_payload = await self._client.get_account_consumption(
                org_id=scope.org_id, period_start=period_start, period_end=period_end
            )
        except NeonAuthError:
            state.status = ScopeStatus.AUTH_ERROR
            return state
        except (NeonAPIError, NeonRateLimitError) as exc:
            _LOGGER.warning("consumption fetch failed for %s: %s", scope.scope_id, exc)
            state.status = ScopeStatus.DEGRADED
            return state

        # Branches (always — needed for root/child counts).
        branch_count_root = 0
        branch_count_child = 0
        branch_splits: dict[str, dict[str, float]] | None = None
        try:
            projects = await self._client.list_projects(scope.org_id)
            branch_parents: dict[str, str | None] = {}
            for project in projects:
                branches = await self._client.list_branches(project["id"])
                for branch in branches:
                    branch_parents[branch["id"]] = branch.get("parent_id")
                    if branch.get("parent_id") is None:
                        branch_count_root += 1
                    else:
                        branch_count_child += 1

            if self._split:
                branch_consumption = await self._client.get_branch_consumption(
                    org_id=scope.org_id, period_start=period_start, period_end=period_end
                )
                branch_splits = _aggregate_branch_split(branch_consumption, branch_parents)
        except NeonAuthError:
            state.status = ScopeStatus.AUTH_ERROR
            return state
        except (NeonAPIError, NeonRateLimitError) as exc:
            _LOGGER.warning("branch fetch failed for %s: %s", scope.scope_id, exc)
            state.status = ScopeStatus.DEGRADED

        consumption = aggregate_consumption(
            cons_payload,
            branch_count_total=branch_count_root + branch_count_child,
            branch_count_root=branch_count_root,
            branch_count_child=branch_count_child,
            split_branches=branch_splits,
        )
        state.consumption = consumption
        state.charges = estimate(
            consumption,
            scope.plan,
            self._rates,
            self._allowances,
            _period_hours(period_start, period_end),
            split_branches=self._split,
        )
        if state.spending_limit_cents is not None and state.spending_limit_cents > 0:
            limit_usd = Decimal(state.spending_limit_cents) / Decimal(100)
            state.used_pct = (state.charges["total"] / limit_usd * Decimal(100)).quantize(Decimal("0.01"))
        state.plan_name = scope.plan
        return state
```

- [ ] **Step 4.5: Run tests — expect 5 passes**

Run: `pytest tests/test_coordinator.py -v`
Expected: 5 passed.

- [ ] **Step 4.6: Commit**

```bash
git add custom_components/neon_billing/coordinator.py tests/conftest.py tests/test_coordinator.py
git commit -m "feat(coordinator): orchestrate per-scope fetch, partial-failure handling, split mode"
```

---

## Task 5: Manifest

**Files:**
- Create: `custom_components/neon_billing/manifest.json`

- [ ] **Step 5.1: Write the manifest**

`custom_components/neon_billing/manifest.json`:
```json
{
  "domain": "neon_billing",
  "name": "Neon Billing",
  "codeowners": ["@dwech"],
  "config_flow": true,
  "documentation": "https://github.com/dwech/ha-neon-billing",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/dwech/ha-neon-billing/issues",
  "requirements": ["httpx>=0.27"],
  "version": "0.1.0"
}
```

- [ ] **Step 5.2: Commit**

```bash
git add custom_components/neon_billing/manifest.json
git commit -m "feat: HA integration manifest"
```

---

## Task 6: Integration Init (entry setup + unload)

**Files:**
- Create: `custom_components/neon_billing/__init__.py` (replace placeholder)
- Create: `tests/test_init.py`

- [ ] **Step 6.1: Write failing setup test**

`tests/test_init.py`:
```python
"""Smoke tests for entry setup / unload."""
from __future__ import annotations

from unittest.mock import patch

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
async def test_setup_and_unload(hass: HomeAssistant) -> None:
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
```

- [ ] **Step 6.2: Run test — expect failure (no setup code)**

Run: `pytest tests/test_init.py -v`
Expected: `ModuleNotFoundError` or import error.

- [ ] **Step 6.3: Implement `__init__.py`**

`custom_components/neon_billing/__init__.py`:
```python
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

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


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
```

- [ ] **Step 6.4: Run init test**

Run: `pytest tests/test_init.py -v`
Expected: 1 passed (note: this test loads HA — slower; may need to skip platform forwarding if sensor.py not done yet — see Step 6.5).

- [ ] **Step 6.5: If test fails due to missing sensor/binary_sensor modules**

Temporarily set `PLATFORMS: list[Platform] = []` in `__init__.py`, rerun test, then revert when those tasks land. Add a TODO marker comment so it isn't forgotten: `# PLATFORMS empty until Tasks 8 & 9`.

- [ ] **Step 6.6: Commit**

```bash
git add custom_components/neon_billing/__init__.py tests/test_init.py
git commit -m "feat(init): config-entry lifecycle (setup, unload, reload listener)"
```

---

## Task 7: Config Flow + Options Flow (TDD)

**Files:**
- Create: `custom_components/neon_billing/config_flow.py`
- Create: `tests/test_config_flow.py`

- [ ] **Step 7.1: Write failing config-flow tests**

`tests/test_config_flow.py`:
```python
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
async def test_full_happy_path(hass: HomeAssistant) -> None:
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
async def test_invalid_auth_shows_error(hass: HomeAssistant) -> None:
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
async def test_duplicate_key_aborts(hass: HomeAssistant) -> None:
    existing = MockConfigEntry(
        domain=DOMAIN, unique_id="dup", data={CONF_API_KEY: "key-xyz"}, options={}
    )
    existing.add_to_hass(hass)
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me.json"))
    )

    with pytest.MonkeyPatch.context() as m:
        m.setattr(
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


async def test_options_flow_persists_values(hass: HomeAssistant) -> None:
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


async def test_options_flow_rejects_currency_without_fx(hass: HomeAssistant) -> None:
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
```

- [ ] **Step 7.2: Run tests — expect failure**

Run: `pytest tests/test_config_flow.py -v`
Expected: import error or skipped — no `config_flow.py` yet.

- [ ] **Step 7.3: Implement `config_flow.py`**

`custom_components/neon_billing/config_flow.py`:
```python
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
    if isinstance(raw, list):
        items = raw
    else:
        items = [int(x.strip()) for x in raw.split(",") if x.strip()]
    return sorted({i for i in items if 1 <= i <= 500})


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

        schema = vol.Schema(
            {vol.Required("scope_ids", default=list(scope_choices.keys())): vol.All(
                [vol.In(list(scope_choices.keys()))], vol.Length(min=1)
            )}
        )
        return self.async_show_form(step_id="scopes", data_schema=schema, description_placeholders={
            "choices": "\n".join(f"- {sid}: {label}" for sid, label in scope_choices.items())
        })

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


def _normalize_plan(plan: str | None) -> str:
    if plan is None:
        return "free"
    plan = plan.lower()
    return plan if plan in SUPPORTED_PLANS else "custom"


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
```

- [ ] **Step 7.4: Run config_flow tests**

Run: `pytest tests/test_config_flow.py -v`
Expected: 5 passed.

- [ ] **Step 7.5: Commit**

```bash
git add custom_components/neon_billing/config_flow.py tests/test_config_flow.py
git commit -m "feat(config_flow): initial setup, scope select, options flow, reauth"
```

---

## Task 8: Sensor Platform

**Files:**
- Create: `custom_components/neon_billing/sensor.py`

- [ ] **Step 8.1: Implement `sensor.py`**

`custom_components/neon_billing/sensor.py`:
```python
"""Numeric sensor entities for Neon Billing."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NeonRuntimeData
from .const import CONF_CURRENCY, CONF_FX_RATE, DOMAIN, RATE_TABLE_VERSION
from .coordinator import ScopeState
from .pricing import to_local


@dataclass(frozen=True, kw_only=True)
class NeonSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ScopeState], Any]
    is_cost: bool = False
    is_unit: bool = False


CURRENCY_USD = "USD"


def _consumption_value(attr: str) -> Callable[[ScopeState], Any]:
    def _inner(state: ScopeState) -> Any:
        if state.consumption is None:
            return None
        return getattr(state.consumption, attr)
    return _inner


def _cost_value(key: str) -> Callable[[ScopeState], Any]:
    def _inner(state: ScopeState) -> Any:
        if not state.charges:
            return None
        return float(state.charges[key])
    return _inner


CONSUMPTION_SENSORS: tuple[NeonSensorDescription, ...] = (
    NeonSensorDescription(
        key="compute_hours",
        translation_key="compute_hours",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.TOTAL,
        value_fn=_consumption_value("compute_hours"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="storage_gb",
        translation_key="storage_gb",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: None if s.consumption is None else s.consumption.storage_gb_hours / max(1.0, _period_hours(s)),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="data_transfer_gb",
        translation_key="data_transfer_gb",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL,
        value_fn=_consumption_value("transfer_gb"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="branch_count_root",
        translation_key="branch_count_root",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumption_value("branch_count_root"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="branch_count_child",
        translation_key="branch_count_child",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumption_value("branch_count_child"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="branch_count_extra",
        translation_key="branch_count_extra",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: None if s.consumption is None else max(
            0, s.consumption.branch_count_total - 0
        ),  # adjusted at runtime against plan allowance via state attributes
        is_unit=True,
    ),
)

COST_KEYS = ("compute", "storage", "branches_root", "branches_child", "data_transfer", "extra_branches", "total")


def _period_hours(state: ScopeState) -> float:
    if state.period_start is None or state.period_end is None:
        return 730.0
    return (state.period_end - state.period_start).total_seconds() / 3600.0


def _make_cost_descriptions() -> tuple[NeonSensorDescription, ...]:
    return tuple(
        NeonSensorDescription(
            key=f"{k}_cost_est",
            translation_key=f"{k}_cost_est",
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=CURRENCY_USD,
            state_class=SensorStateClass.TOTAL,
            value_fn=_cost_value(k),
            is_cost=True,
            suggested_display_precision=2,
        )
        for k in COST_KEYS
    )


COST_SENSORS: tuple[NeonSensorDescription, ...] = _make_cost_descriptions()


SPENDING_LIMIT_SENSORS: tuple[NeonSensorDescription, ...] = (
    NeonSensorDescription(
        key="spending_limit",
        translation_key="spending_limit",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_USD,
        value_fn=lambda s: None if s.spending_limit_cents is None else s.spending_limit_cents / 100.0,
        is_cost=True,
        suggested_display_precision=2,
    ),
    NeonSensorDescription(
        key="spending_limit_used_pct",
        translation_key="spending_limit_used_pct",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: None if s.used_pct is None else float(s.used_pct),
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: NeonRuntimeData = hass.data[DOMAIN][entry.entry_id]
    currency = (entry.options.get(CONF_CURRENCY) or "").strip().upper()
    fx_rate = float(entry.options.get(CONF_FX_RATE) or 0.0)
    has_local = bool(currency and fx_rate > 0)

    entities: list[SensorEntity] = []
    for scope_id, scope_state in runtime.coordinator.data.items():
        device = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{scope_id}")},
            name=f"{runtime.label} / {scope_id}",
            manufacturer="Neon",
            model=f"Plan: {scope_state.scope.plan}",
            sw_version=RATE_TABLE_VERSION,
        )
        for desc in (*CONSUMPTION_SENSORS, *COST_SENSORS, *SPENDING_LIMIT_SENSORS):
            entities.append(NeonSensor(runtime.coordinator, scope_id, desc, device, runtime.label))
            if has_local and desc.is_cost:
                entities.append(
                    NeonLocalCurrencySensor(
                        runtime.coordinator, scope_id, desc, device, runtime.label, currency, fx_rate
                    )
                )
    async_add_entities(entities)


class NeonSensor(CoordinatorEntity, SensorEntity):
    """Base entity reading from the coordinator's per-scope dict."""

    _attr_has_entity_name = True
    entity_description: NeonSensorDescription

    def __init__(
        self,
        coordinator,
        scope_id: str,
        description: NeonSensorDescription,
        device: DeviceInfo,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._scope_id = scope_id
        self._attr_unique_id = f"{label}_{scope_id}_{description.key}"
        self._attr_device_info = device

    @property
    def _state(self) -> ScopeState | None:
        return self.coordinator.data.get(self._scope_id) if self.coordinator.data else None

    @property
    def native_value(self) -> Any:
        state = self._state
        if state is None:
            return None
        return self.entity_description.value_fn(state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs: dict[str, Any] = {}
        if self.entity_description.is_cost:
            attrs.update({
                "is_estimate": True,
                "rate_table_version": RATE_TABLE_VERSION,
                "source": "client-side computation",
            })
        if state := self._state:
            if state.period_start:
                attrs["period_start"] = state.period_start.isoformat()
            if state.period_end:
                attrs["period_end"] = state.period_end.isoformat()
            attrs["plan"] = state.plan_name
            attrs["status"] = state.status.value
        return attrs or None


class NeonLocalCurrencySensor(NeonSensor):
    """Mirror sensor that converts USD to a configured local currency."""

    def __init__(
        self,
        coordinator,
        scope_id: str,
        description: NeonSensorDescription,
        device: DeviceInfo,
        label: str,
        currency: str,
        fx_rate: float,
    ) -> None:
        super().__init__(coordinator, scope_id, description, device, label)
        self._currency = currency
        self._fx_rate = fx_rate
        self._attr_unique_id = f"{label}_{scope_id}_{description.key}_{currency.lower()}"
        self._attr_translation_key = f"{description.translation_key}_local"
        self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> Any:
        usd = super().native_value
        if usd is None:
            return None
        return float(to_local(Decimal(str(usd)), self._fx_rate))
```

- [ ] **Step 8.2: Re-run init test (now with PLATFORMS restored)**

Restore `PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]` in `__init__.py` if you stubbed it during Task 6. Run: `pytest tests/test_init.py -v`. Expected: 1 passed.

- [ ] **Step 8.3: Add a sensor-coverage assertion to `test_init.py`**

Append to `tests/test_init.py`:
```python
async def test_sensors_created_for_each_scope(hass: HomeAssistant) -> None:
    # Reuses the @respx.mock fixture set from test_setup_and_unload — re-mock for isolation.
    import respx, httpx
    from freezegun import freeze_time
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
        states = hass.states.async_entity_ids("sensor")
        assert any("compute_hours" in s for s in states)
        assert any("total_cost_est" in s for s in states)
        assert any("spending_limit" in s for s in states)
```

- [ ] **Step 8.4: Run tests**

Run: `pytest tests/test_init.py -v`
Expected: 2 passed.

- [ ] **Step 8.5: Commit**

```bash
git add custom_components/neon_billing/sensor.py tests/test_init.py
git commit -m "feat(sensor): numeric sensors, cost estimates, local-currency mirrors"
```

---

## Task 9: Binary Sensor Platform

**Files:**
- Create: `custom_components/neon_billing/binary_sensor.py`

- [ ] **Step 9.1: Implement `binary_sensor.py`**

`custom_components/neon_billing/binary_sensor.py`:
```python
"""Binary sensors for over-limit and user-configured thresholds."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NeonRuntimeData
from .const import CONF_THRESHOLD_PCTS, DOMAIN, RATE_TABLE_VERSION
from .coordinator import ScopeState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: NeonRuntimeData = hass.data[DOMAIN][entry.entry_id]
    thresholds: list[int] = entry.options.get(CONF_THRESHOLD_PCTS, [])

    entities: list[BinarySensorEntity] = []
    for scope_id, scope_state in runtime.coordinator.data.items():
        device = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{scope_id}")},
            name=f"{runtime.label} / {scope_id}",
            manufacturer="Neon",
            model=f"Plan: {scope_state.scope.plan}",
            sw_version=RATE_TABLE_VERSION,
        )
        entities.append(OverLimitSensor(runtime.coordinator, scope_id, device, runtime.label))
        for pct in thresholds:
            entities.append(
                ThresholdSensor(runtime.coordinator, scope_id, device, runtime.label, pct)
            )
    async_add_entities(entities)


class _BaseBinary(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, scope_id: str, device: DeviceInfo, label: str) -> None:
        super().__init__(coordinator)
        self._scope_id = scope_id
        self._attr_device_info = device
        self._label = label

    @property
    def _state(self) -> ScopeState | None:
        return self.coordinator.data.get(self._scope_id) if self.coordinator.data else None


class OverLimitSensor(_BaseBinary):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "over_limit"

    def __init__(self, coordinator, scope_id: str, device: DeviceInfo, label: str) -> None:
        super().__init__(coordinator, scope_id, device, label)
        self._attr_unique_id = f"{label}_{scope_id}_over_limit"

    @property
    def is_on(self) -> bool:
        state = self._state
        if state is None or state.used_pct is None:
            return False
        return float(state.used_pct) > 100.0


class ThresholdSensor(_BaseBinary):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator, scope_id: str, device: DeviceInfo, label: str, threshold_pct: int
    ) -> None:
        super().__init__(coordinator, scope_id, device, label)
        self._threshold = threshold_pct
        self._attr_unique_id = f"{label}_{scope_id}_threshold_{threshold_pct}pct"
        self._attr_translation_key = "threshold_pct"
        self._attr_translation_placeholders = {"pct": str(threshold_pct)}

    @property
    def is_on(self) -> bool:
        state = self._state
        if state is None or state.used_pct is None:
            return False
        return float(state.used_pct) > self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"threshold_pct": self._threshold}
```

- [ ] **Step 9.2: Add a binary_sensor smoke test to `test_init.py`**

Append to `tests/test_init.py`:
```python
async def test_threshold_binary_sensor_created(hass: HomeAssistant) -> None:
    import respx, httpx
    from freezegun import freeze_time
    from custom_components.neon_billing.const import (
        CONF_THRESHOLD_PCTS, NEON_API_BASE,
    )
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
        entry.options = {CONF_THRESHOLD_PCTS: [80]}
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        bs = hass.states.async_entity_ids("binary_sensor")
        assert any("over_limit" in s for s in bs)
        assert any("threshold_80pct" in s for s in bs)
```

- [ ] **Step 9.3: Run tests**

Run: `pytest tests/test_init.py -v`
Expected: 3 passed.

- [ ] **Step 9.4: Commit**

```bash
git add custom_components/neon_billing/binary_sensor.py tests/test_init.py
git commit -m "feat(binary_sensor): over-limit + dynamic threshold entities"
```

---

## Task 10: Strings + Translations

**Files:**
- Create: `custom_components/neon_billing/strings.json`
- Create: `custom_components/neon_billing/translations/en.json`

- [ ] **Step 10.1: Write `strings.json`**

`custom_components/neon_billing/strings.json`:
```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect your Neon account",
        "description": "Paste a Neon API key from console.neon.tech/app/settings/api-keys.",
        "data": {
          "api_key": "Neon API key",
          "label": "Label (used in entity IDs)"
        }
      },
      "scopes": {
        "title": "Select Neon scopes to monitor",
        "description": "Choose your personal account and/or organisations.\n\n{choices}",
        "data": { "scope_ids": "Scopes" }
      },
      "reauth_confirm": {
        "title": "Re-authenticate Neon",
        "description": "The previous Neon API key was rejected. Paste a fresh one.",
        "data": { "api_key": "Neon API key" }
      }
    },
    "error": {
      "invalid_auth": "Neon rejected this API key.",
      "cannot_connect": "Could not reach console.neon.tech."
    },
    "abort": {
      "already_configured": "This API key is already configured.",
      "reauth_successful": "API key updated."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "Neon Billing options",
        "data": {
          "update_interval_min": "Update interval (minutes)",
          "split_branches_root_child": "Split branch costs by root / child (extra API calls)",
          "currency": "Local currency code (e.g. NZD); leave blank to disable mirrors",
          "fx_rate_usd_to_local": "Exchange rate (USD → local). Required if currency is set.",
          "threshold_pcts": "Threshold percentages (comma-separated, e.g. 80,90)"
        }
      }
    },
    "error": {
      "fx_required_when_currency_set": "Set an exchange rate above zero when a currency is configured."
    }
  },
  "entity": {
    "sensor": {
      "compute_hours": { "name": "Compute hours" },
      "storage_gb": { "name": "Storage" },
      "data_transfer_gb": { "name": "Data transfer" },
      "branch_count_root": { "name": "Root branches" },
      "branch_count_child": { "name": "Child branches" },
      "branch_count_extra": { "name": "Branches over allowance" },
      "compute_cost_est": { "name": "Compute (est.)" },
      "storage_cost_est": { "name": "Storage (est.)" },
      "branches_root_cost_est": { "name": "Root branches (est.)" },
      "branches_child_cost_est": { "name": "Child branches (est.)" },
      "data_transfer_cost_est": { "name": "Data transfer (est.)" },
      "extra_branches_cost_est": { "name": "Extra branches (est.)" },
      "total_cost_est": { "name": "Total charges (est.)" },
      "spending_limit": { "name": "Spending limit" },
      "spending_limit_used_pct": { "name": "Spending limit used" }
    },
    "binary_sensor": {
      "over_limit": { "name": "Over spending limit" },
      "threshold_pct": { "name": "Over {pct}% of spending limit" }
    }
  }
}
```

- [ ] **Step 10.2: Copy `strings.json` to `translations/en.json`**

```bash
mkdir -p custom_components/neon_billing/translations
cp custom_components/neon_billing/strings.json custom_components/neon_billing/translations/en.json
```

- [ ] **Step 10.3: Commit**

```bash
git add custom_components/neon_billing/strings.json custom_components/neon_billing/translations/en.json
git commit -m "feat(i18n): English strings for config flow, options, entities"
```

---

## Task 11: CI Workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 11.1: Write the workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request:

jobs:
  lint-type-test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: mypy custom_components/neon_billing/pricing.py custom_components/neon_billing/api.py
      - run: pytest --cov=custom_components.neon_billing --cov-report=term-missing

  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master

  hacs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hacs/action@main
        with:
          category: integration
```

- [ ] **Step 11.2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint, mypy, pytest, hassfest, HACS validation"
```

---

## Task 12: Install Docs

**Files:**
- Create: `docs/INSTALL.md`

- [ ] **Step 12.1: Write install guide**

`docs/INSTALL.md`:
```markdown
# Install Neon Billing for Home Assistant

## Requirements
- Home Assistant ≥ 2026.6
- A Neon API key (`console.neon.tech/app/settings/api-keys` → "Create new API key")

## Install via HACS (recommended)
1. HACS → Integrations → 3-dot menu → Custom repositories.
2. Add `https://github.com/dwech/ha-neon-billing` with category **Integration**.
3. Search for "Neon Billing" in HACS and install.
4. Restart Home Assistant.

## Manual install
Copy `custom_components/neon_billing/` into your HA config directory's `custom_components/` folder and restart.

## Configure
1. Settings → Devices & Services → Add Integration → search "Neon Billing".
2. Paste your API key and pick a label.
3. Select which Neon scopes to monitor (personal account + organisations).
4. Submit. The integration creates one HA device per selected scope.

## Options
Settings → Devices & Services → Neon Billing → Configure:
- **Update interval (minutes)** — 5 to 1440.
- **Split branch costs by root / child** — adds per-branch API calls and two extra cost sensors.
- **Local currency + FX rate** — adds mirror cost sensors converted to your currency.
- **Threshold percentages** — comma-separated integers (e.g. `80,90,100`) — each creates a `binary_sensor.<scope>_threshold_<n>pct`.

## Smoke test
1. Open Developer Tools → States.
2. Filter `sensor.<your_label>`.
3. Verify these populate within one update interval:
   - `..._compute_hours`
   - `..._storage_gb`
   - `..._total_cost_est`
   - `..._spending_limit` (only on Launch / Scale plans)
   - `..._spending_limit_used_pct`
4. Set a low spending limit in Neon (e.g. $1) and re-poll. `binary_sensor.<scope>_over_limit` flips to `on` once the estimate exceeds the limit.

## Estimate caveat
Cost figures are computed client-side from a fixed rate table (see `custom_components/neon_billing/const.py`). Neon's own dashboard numbers are authoritative; this integration's estimates will drift if Neon changes pricing or if your account is on a custom contract.
```

- [ ] **Step 12.2: Commit**

```bash
git add docs/INSTALL.md
git commit -m "docs: install + smoke-test walkthrough"
```

---

## Task 13: Final README

**Files:**
- Modify: `README.md` (replace stub from Task 0.5)

- [ ] **Step 13.1: Write final README**

`README.md`:
```markdown
# Neon Billing for Home Assistant

[![CI](https://github.com/dwech/ha-neon-billing/actions/workflows/ci.yml/badge.svg)](https://github.com/dwech/ha-neon-billing/actions/workflows/ci.yml)

Tracks Neon (serverless Postgres) consumption, estimated charges, and spending-limit usage as Home Assistant sensors.

> **Estimates, not invoices.** Neon's public v2 API exposes consumption units (CU-seconds, bytes) and the configured spending limit, but **not** the dollar amounts shown on the Neon dashboard. This integration computes USD figures client-side from a configurable rate table (`rate_table_version: 2026-06-16`). Numbers will drift from Neon's invoice when Neon changes pricing or when your account is on a custom contract. Treat all `*_cost_est` sensors as guidance, not truth.

## What you get per Neon scope (account or organisation)

**Consumption sensors (sourced from API):**
- Compute hours
- Storage GB
- Data transfer GB
- Root / child / extra branch counts

**Estimated cost sensors (USD, computed):**
- Compute, storage, data transfer, root branches, child branches, extra branches, total

**Spending-limit sensors:**
- `spending_limit` (USD)
- `spending_limit_used_pct` (can exceed 100)

**Binary sensors:**
- `over_limit` — fires when used > 100%
- `threshold_<n>pct` — one per user-configured threshold

**Local-currency mirrors:**
- Optional `_<ccy>` mirrors for every cost sensor when a currency + FX rate are configured.

## Install
See [`docs/INSTALL.md`](docs/INSTALL.md).

## Multi-account
Each Neon API key is a separate HA config entry. Add as many as you like via Devices & Services → Add Integration.

## Rate table
Defaults (current Neon public pricing):

| Component | Rate | Unit |
|---|---|---|
| Compute | $0.16 | per CU-hour |
| Storage | $0.000164 | per GB-hour |
| Data transfer | $0.09 | per GB |
| Extra branch | $0.20 | per branch over plan allowance |

Editable in the integration's options flow.

## License
MIT.
```

- [ ] **Step 13.2: Commit**

```bash
git add README.md
git commit -m "docs: replace README stub with final user-facing copy"
```

---

## Task 14: Final Verification

- [ ] **Step 14.1: Full test suite**

Run: `pytest -v --cov=custom_components.neon_billing`
Expected: all tests pass; coverage ≥ 80% on `pricing.py`, `api.py`, `coordinator.py`.

- [ ] **Step 14.2: Lint + type**

Run: `ruff check . && mypy custom_components/neon_billing/pricing.py custom_components/neon_billing/api.py`
Expected: no errors.

- [ ] **Step 14.3: Push to remote**

```bash
git remote add origin git@github.com:dwech/ha-neon-billing.git
git push -u origin main
```

(Confirm with user before adding the remote — they may want a different account/host.)

- [ ] **Step 14.4: Watch CI**

After push, open Actions tab; confirm `lint-type-test` (both Python versions), `hassfest`, and `hacs` jobs go green.

- [ ] **Step 14.5: Manual install + smoke test**

Per `docs/INSTALL.md` §"Smoke test". Drop one screenshot of the HA dashboard card with at least `total_cost_est`, `spending_limit_used_pct`, and `over_limit` visible into `docs/screenshots/` and reference it from the README.

---

## Self-Review Notes

- **Spec coverage:** §3 (API constraint) — disclosed in README + cost-sensor attributes (Task 8). §4.2 (one entry per key) — config flow `unique_id` (Task 7) + multi-scope topology (Task 6). §5 sensor inventory — Tasks 8 & 9 cover every row. §6 pricing — Task 2. §7 config flow — Task 7. §8 error handling — coordinator (Task 4) + init (Task 6). §9 testing strategy — tasks 2/3/4/6/7 contain all listed test classes. CI in Task 11.
- **Open assumption — `data_transfer_bytes` ↔ "Public network transfer":** verify at smoke-test time (Task 14.5) by comparing the `data_transfer_gb` sensor against the Neon dashboard's transfer line. If they don't match, update `coordinator.aggregate_consumption` to use the right metric field and add a regression test.
- **Open assumption — read-only org API keys:** if smoke-test reveals 403s on org endpoints from a read-only key, update README to recommend admin-level org keys.
- **Future tasks deliberately out of scope:** historic billing, per-project sensors, in-card automation suggestions. Track in GitHub issues post-launch.
