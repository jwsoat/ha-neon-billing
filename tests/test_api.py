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


@respx.mock
async def test_get_branch_consumption_returns_branch_list(client: NeonClient) -> None:
    route = respx.get(f"{NEON_API_BASE}/consumption_history/v2/branches").mock(
        return_value=httpx.Response(200, json=_load("branch_consumption.json"))
    )
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    branches = await client.get_branch_consumption(
        org_id="org-alpha", period_start=start, period_end=end
    )
    assert route.called
    params = route.calls.last.request.url.params
    assert params["from"] == "2026-06-01T00:00:00+00:00"
    assert params["to"] == "2026-07-01T00:00:00+00:00"
    assert params["org_id"] == "org-alpha"
    assert params["granularity"] == "daily"
    assert len(branches) == 2
    assert branches[0]["id"] == "br-root"
    assert branches[1]["compute_time_seconds"] == 396000


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


def test_billing_period_bounds_does_not_drift_day_31_anchor() -> None:
    """Quota reset on day 31 must keep landing on day 31 / month-end after Feb clamp."""
    quota_reset = datetime(2026, 1, 31, 12, 0, 0, tzinfo=timezone.utc)
    # After several months past a Feb clamp, the period should still anchor on day 31
    # (or each month's last day), not on day 28 frozen from Feb.
    now = datetime(2026, 11, 15, 0, 0, 0, tzinfo=timezone.utc)
    start, end = billing_period_bounds(quota_reset, now)
    assert start == datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 30, 12, 0, 0, tzinfo=timezone.utc)
