# Neon Billing for Home Assistant

[![CI](https://github.com/jwsoat/ha-neon-billing/actions/workflows/ci.yml/badge.svg)](https://github.com/jwsoat/ha-neon-billing/actions/workflows/ci.yml)

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
