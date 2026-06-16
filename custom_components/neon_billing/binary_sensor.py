"""Binary sensors for over-limit and user-configured thresholds."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NeonRuntimeData
from .const import CONF_THRESHOLD_PCTS, DOMAIN, RATE_TABLE_VERSION
from .coordinator import ScopeState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime: NeonRuntimeData = hass.data[DOMAIN][entry.entry_id]
    thresholds: list[int] = entry.options.get(CONF_THRESHOLD_PCTS, [])

    entities: list[BinarySensorEntity] = []
    for scope_id, scope_state in runtime.coordinator.data.items():
        device = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{scope_id}")},
            name=f"{runtime.label} / {scope_id}",
            manufacturer="Neon",
            model=f"Plan: {scope_state.scope.plan}",
            sw_version=RATE_TABLE_VERSION,
        )
        entities.append(OverLimitSensor(runtime.coordinator, scope_id, device, runtime.label))
        for pct in thresholds:
            entities.append(
                ThresholdSensor(runtime.coordinator, scope_id, device, runtime.label, pct)
            )
    async_add_entities(entities)


class _BaseBinary(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, scope_id: str, device: DeviceInfo, label: str) -> None:
        super().__init__(coordinator)
        self._scope_id = scope_id
        self._attr_device_info = device
        self._label = label

    @property
    def _state(self) -> ScopeState | None:
        return self.coordinator.data.get(self._scope_id) if self.coordinator.data else None


class OverLimitSensor(_BaseBinary):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "over_limit"

    def __init__(self, coordinator, scope_id: str, device: DeviceInfo, label: str) -> None:
        super().__init__(coordinator, scope_id, device, label)
        self._attr_unique_id = f"{label}_{scope_id}_over_limit"

    @property
    def is_on(self) -> bool:
        state = self._state
        if state is None or state.used_pct is None:
            return False
        return float(state.used_pct) > 100.0


class ThresholdSensor(_BaseBinary):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator, scope_id: str, device: DeviceInfo, label: str, threshold_pct: int
    ) -> None:
        super().__init__(coordinator, scope_id, device, label)
        self._threshold = threshold_pct
        self._attr_unique_id = f"{label}_{scope_id}_threshold_{threshold_pct}pct"
        self._attr_translation_key = "threshold_pct"
        self._attr_translation_placeholders = {"pct": str(threshold_pct)}

    @property
    def is_on(self) -> bool:
        state = self._state
        if state is None or state.used_pct is None:
            return False
        return float(state.used_pct) > self._threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"threshold_pct": self._threshold}
