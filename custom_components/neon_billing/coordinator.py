"""DataUpdateCoordinator that orchestrates Neon API calls per scope."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    branch_allowance: int = 0


def aggregate_consumption(
    payload: dict[str, Any],
    *,
    branch_count_total: int,
    branch_count_root: int = 0,
    branch_count_child: int = 0,
    split_branches: dict[str, dict[str, float]] | None = None,
) -> ScopeConsumption:
    """Roll up the Neon /consumption_history/account payload into a ScopeConsumption."""
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
        parent = branch_parents.get(bid) if bid is not None else None
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
        billing = user.get("billing_account") or {}
        quota_reset_raw = billing.get("quota_reset_at_last")
        now = datetime.now(tz=UTC)
        if quota_reset_raw:
            quota_reset = datetime.fromisoformat(quota_reset_raw.replace("Z", "+00:00"))
            period_start, period_end = billing_period_bounds(quota_reset, now)
        else:
            _LOGGER.debug(
                "billing_account.quota_reset_at_last missing; defaulting to calendar-month start"
            )
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = period_start.replace(year=period_start.year + (1 if period_start.month == 12 else 0), month=1 if period_start.month == 12 else period_start.month + 1)
            period_end = next_month

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
            err = str(exc)
            if "client error 400" in err or "client error 403" in err:
                _LOGGER.info(
                    "consumption unavailable for %s (likely Launch plan or missing org_id): %s",
                    scope.scope_id, err,
                )
                cons_payload = {"periods": []}
                state.status = ScopeStatus.DEGRADED
            else:
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
                try:
                    branch_consumption = await self._client.get_branch_consumption(
                        org_id=scope.org_id, period_start=period_start, period_end=period_end
                    )
                    branch_splits = _aggregate_branch_split(branch_consumption, branch_parents)
                except (NeonAPIError, NeonRateLimitError) as exc:
                    err = str(exc)
                    if "client error 400" in err or "client error 403" in err:
                        _LOGGER.info("branch consumption unavailable for %s: %s", scope.scope_id, err)
                        state.status = ScopeStatus.DEGRADED
                    else:
                        raise
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
        plan_allowance = self._allowances.get(scope.plan, self._allowances["custom"])
        state.branch_allowance = int(plan_allowance["branches"])
        return state
