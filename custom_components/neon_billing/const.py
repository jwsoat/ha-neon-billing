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
