"""Base entities."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import MANUFACTURER_GATEWAY
from .coordinator import (
    GatewayCoordinator,
    MeterState,
    gateway_device_identifier,
    meter_device_identifier,
)


class GatewayEntity(CoordinatorEntity[GatewayCoordinator]):
    """Entity attached to the gateway device. Always available."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GatewayCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_gateway_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={gateway_device_identifier(entry)},
            name=coordinator.gateway_name,
            manufacturer=MANUFACTURER_GATEWAY,
            model="Modbus TCP gateway",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    @property
    def available(self) -> bool:
        """Diagnostics of the gateway are always available."""
        return True


class MeterEntity(CoordinatorEntity[GatewayCoordinator]):
    """Entity attached to a meter device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GatewayCoordinator, meter: MeterState, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.meter = meter
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{meter.slave_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={meter_device_identifier(entry, meter.slave_id)},
            name=meter.name,
            manufacturer=meter.model.manufacturer,
            model=meter.model.name,
            model_id=meter.model.model_id,
        )
        if coordinator.gateway_device_id:
            self._attr_device_info["via_device_id"] = coordinator.gateway_device_id
        info = meter.info or {}
        if (sw := info.get("sw_version")) is not None:
            self._attr_device_info["sw_version"] = f"{sw:g}"
        if (hw := info.get("hw_version")) is not None:
            self._attr_device_info["hw_version"] = f"{hw:g}"
        if serial := info.get("serial_number"):
            self._attr_device_info["serial_number"] = f"{serial:08d}"
