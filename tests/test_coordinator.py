"""Tests for the per-entry DataUpdateCoordinator."""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from freezegun import freeze_time

from custom_components.neon_billing.api import NeonClient
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
    assert agg.compute_hours == pytest.approx(360.0, rel=1e-3)
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
    assert scope.used_pct is not None


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
async def test_coordinator_consumption_paywall_degrades_but_keeps_branches(
    neon_client: NeonClient,
) -> None:
    """Launch-plan orgs return 403 from consumption; coordinator must still surface branch counts."""
    respx.get(f"{NEON_API_BASE}/users/me").mock(
        return_value=httpx.Response(200, json=load_fixture("users_me.json"))
    )
    respx.get(f"{NEON_API_BASE}/consumption_history/account").mock(
        return_value=httpx.Response(
            403, json={"code": "", "message": "endpoint is included with Scale plans and above"}
        )
    )
    respx.get(f"{NEON_API_BASE}/organizations/org-alpha/billing/spending_limit").mock(
        return_value=httpx.Response(200, json=load_fixture("spending_limit.json"))
    )
    respx.get(f"{NEON_API_BASE}/projects").mock(
        return_value=httpx.Response(200, json={"projects": [{"id": "p1"}]})
    )
    respx.get(f"{NEON_API_BASE}/projects/p1/branches").mock(
        return_value=httpx.Response(
            200,
            json={
                "branches": [
                    {"id": "b1", "parent_id": None},
                    {"id": "b2", "parent_id": "b1"},
                ]
            },
        )
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
    assert scope.consumption is not None
    assert scope.consumption.branch_count_root == 1
    assert scope.consumption.branch_count_child == 1
    assert scope.consumption.compute_hours == 0.0
    assert scope.spending_limit_cents == 5000


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
    assert scope.charges["compute"] == Decimal("0")


@respx.mock
@freeze_time("2026-06-16T12:00:00Z")
async def test_coordinator_stores_plan_branch_allowance(neon_client: NeonClient) -> None:
    """branch_allowance must be populated from plan defaults so sensor can compute overage."""
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

    coordinator = NeonCoordinator(
        client=neon_client,
        scopes=[_scope("org-alpha", plan="launch", org_id="org-alpha")],
        rates=DEFAULT_RATES,
        allowances=DEFAULT_ALLOWANCES,
        split_branches=False,
    )
    data = await coordinator.fetch()
    scope = data["org-alpha"]
    assert scope.branch_allowance == 500  # Launch plan allowance from DEFAULT_ALLOWANCES
