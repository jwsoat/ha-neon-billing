"""Numeric sensor entities for Neon Billing."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NeonRuntimeData
from .const import CONF_CURRENCY, CONF_FX_RATE, DOMAIN, RATE_TABLE_VERSION
from .coordinator import ScopeState
from .pricing import to_local


@dataclass(frozen=True, kw_only=True)
class NeonSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ScopeState], Any]
    is_cost: bool = False
    is_unit: bool = False


CURRENCY_USD = "USD"


def _consumption_value(attr: str) -> Callable[[ScopeState], Any]:
    def _inner(state: ScopeState) -> Any:
        if state.consumption is None:
            return None
        return getattr(state.consumption, attr)
    return _inner


def _cost_value(key: str) -> Callable[[ScopeState], Any]:
    def _inner(state: ScopeState) -> Any:
        if not state.charges:
            return None
        return float(state.charges[key])
    return _inner


def _period_hours(state: ScopeState) -> float:
    if state.period_start is None or state.period_end is None:
        return 730.0
    return (state.period_end - state.period_start).total_seconds() / 3600.0


CONSUMPTION_SENSORS: tuple[NeonSensorDescription, ...] = (
    NeonSensorDescription(
        key="compute_hours",
        translation_key="compute_hours",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.TOTAL,
        value_fn=_consumption_value("compute_hours"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="storage_gb",
        translation_key="storage_gb",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: None if s.consumption is None else s.consumption.storage_gb_hours / max(1.0, _period_hours(s)),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="data_transfer_gb",
        translation_key="data_transfer_gb",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL,
        value_fn=_consumption_value("transfer_gb"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="branch_count_root",
        translation_key="branch_count_root",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumption_value("branch_count_root"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="branch_count_child",
        translation_key="branch_count_child",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_consumption_value("branch_count_child"),
        is_unit=True,
    ),
    NeonSensorDescription(
        key="branch_count_extra",
        translation_key="branch_count_extra",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: None if s.consumption is None else max(0, s.consumption.branch_count_total - s.branch_allowance),
        is_unit=True,
    ),
)

COST_KEYS = ("compute", "storage", "branches_root", "branches_child", "data_transfer", "extra_branches", "total")


def _make_cost_descriptions() -> tuple[NeonSensorDescription, ...]:
    return tuple(
        NeonSensorDescription(
            key=f"{k}_cost_est",
            translation_key=f"{k}_cost_est",
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=CURRENCY_USD,
            state_class=SensorStateClass.TOTAL,
            value_fn=_cost_value(k),
            is_cost=True,
            suggested_display_precision=2,
        )
        for k in COST_KEYS
    )


COST_SENSORS: tuple[NeonSensorDescription, ...] = _make_cost_descriptions()


SPENDING_LIMIT_SENSORS: tuple[NeonSensorDescription, ...] = (
    NeonSensorDescription(
        key="spending_limit",
        translation_key="spending_limit",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_USD,
        value_fn=lambda s: None if s.spending_limit_cents is None else s.spending_limit_cents / 100.0,
        is_cost=True,
        suggested_display_precision=2,
    ),
    NeonSensorDescription(
        key="spending_limit_used_pct",
        translation_key="spending_limit_used_pct",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: None if s.used_pct is None else float(s.used_pct),
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: NeonRuntimeData = hass.data[DOMAIN][entry.entry_id]
    currency = (entry.options.get(CONF_CURRENCY) or "").strip().upper()
    fx_rate = float(entry.options.get(CONF_FX_RATE) or 0.0)
    has_local = bool(currency and fx_rate > 0)

    entities: list[SensorEntity] = []
    for scope_id, scope_state in runtime.coordinator.data.items():
        device = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{scope_id}")},
            name=f"{runtime.label} / {scope_id}",
            manufacturer="Neon",
            model=f"Plan: {scope_state.scope.plan}",
            sw_version=RATE_TABLE_VERSION,
        )
        for desc in (*CONSUMPTION_SENSORS, *COST_SENSORS, *SPENDING_LIMIT_SENSORS):
            entities.append(NeonSensor(runtime.coordinator, scope_id, desc, device, runtime.label))
            if has_local and desc.is_cost:
                entities.append(
                    NeonLocalCurrencySensor(
                        runtime.coordinator, scope_id, desc, device, runtime.label, currency, fx_rate
                    )
                )
    async_add_entities(entities)


class NeonSensor(CoordinatorEntity, SensorEntity):
    """Base entity reading from the coordinator's per-scope dict."""

    _attr_has_entity_name = True
    entity_description: NeonSensorDescription

    def __init__(
        self,
        coordinator,
        scope_id: str,
        description: NeonSensorDescription,
        device: DeviceInfo,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._scope_id = scope_id
        self._attr_unique_id = f"{label}_{scope_id}_{description.key}"
        self._attr_device_info = device

    @property
    def _state(self) -> ScopeState | None:
        return self.coordinator.data.get(self._scope_id) if self.coordinator.data else None

    @property
    def native_value(self) -> Any:
        state = self._state
        if state is None:
            return None
        return self.entity_description.value_fn(state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs: dict[str, Any] = {}
        if self.entity_description.is_cost:
            attrs.update({
                "is_estimate": True,
                "rate_table_version": RATE_TABLE_VERSION,
                "source": "client-side computation",
            })
        if state := self._state:
            if state.period_start:
                attrs["period_start"] = state.period_start.isoformat()
            if state.period_end:
                attrs["period_end"] = state.period_end.isoformat()
            attrs["plan"] = state.plan_name
            attrs["status"] = state.status.value
        return attrs or None


class NeonLocalCurrencySensor(NeonSensor):
    """Mirror sensor that converts USD to a configured local currency."""

    def __init__(
        self,
        coordinator,
        scope_id: str,
        description: NeonSensorDescription,
        device: DeviceInfo,
        label: str,
        currency: str,
        fx_rate: float,
    ) -> None:
        super().__init__(coordinator, scope_id, description, device, label)
        self._currency = currency
        self._fx_rate = fx_rate
        self._attr_unique_id = f"{label}_{scope_id}_{description.key}_{currency.lower()}"
        self._attr_translation_key = f"{description.translation_key}_local"
        self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> Any:
        usd = super().native_value
        if usd is None:
            return None
        return float(to_local(Decimal(str(usd)), self._fx_rate))
