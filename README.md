# Neon Billing for Home Assistant

Tracks Neon (serverless Postgres) consumption, estimated charges, and spending-limit usage as HA sensors.

> **Estimates, not invoices.** Neon's public API returns consumption units, not dollar charges. This integration computes USD figures client-side from a configurable rate table. Numbers will not exactly match your Neon invoice and may drift when Neon changes pricing.

Full docs and install instructions in [`docs/INSTALL.md`](docs/INSTALL.md). This README is filled out in Task 17.
