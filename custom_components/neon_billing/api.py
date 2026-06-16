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
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    next_first = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
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
            data: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise NeonAPIError("malformed JSON response") from exc
        return data

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
