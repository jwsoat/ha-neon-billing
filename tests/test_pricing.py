"""Tests for pricing.estimate and pricing.to_local."""
from __future__ import annotations

from decimal import Decimal

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
        compute_hours=100.0,
        storage_gb_hours=5.0 * PERIOD_HOURS,
        transfer_gb=20.0,
        branch_count_total=10,
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
    c = _zero_consumption(compute_hours=400.0)
    result = estimate(
        c, "launch", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    assert result["compute"] == Decimal("16.0000")
    assert result["total"] == Decimal("16.0000")


def test_estimate_computes_extra_branches() -> None:
    c = _zero_consumption(branch_count_total=505)
    result = estimate(
        c, "launch", DEFAULT_RATES, DEFAULT_ALLOWANCES, PERIOD_HOURS, split_branches=False
    )
    assert result["extra_branches"] == Decimal("1.0000")
    assert result["total"] == Decimal("1.0000")


def test_estimate_handles_free_plan_zero_allowances_for_unused() -> None:
    c = _zero_consumption(compute_hours=200.0)
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
    assert result["compute"] == Decimal("1.6000")


def test_to_local_applies_fx_rate() -> None:
    assert to_local(Decimal("10.0000"), 1.6543) == Decimal("16.5430")


def test_to_local_zero_fx_returns_zero() -> None:
    assert to_local(Decimal("10.0000"), 0.0) == Decimal("0.0000")
