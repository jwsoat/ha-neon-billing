"""Pure pricing logic — converts Neon consumption to USD estimates."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

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
