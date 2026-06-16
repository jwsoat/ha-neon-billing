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
