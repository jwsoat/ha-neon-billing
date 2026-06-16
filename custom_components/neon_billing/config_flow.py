"""Config flow stub for Neon Billing.

Minimal placeholder so HA can import the platform during ``async_setup_entry``;
manifest.json declares ``config_flow: true``. The real flow lands in Task 7.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class NeonBillingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Placeholder config flow. Replaced in Task 7."""

    VERSION = 1
