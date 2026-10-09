"""Binary sensor platform."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BGETechConfigEntry, GatewayCoordinator, MeterState
from .entity import GatewayEntity, MeterEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BGETechConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up connectivity sensors."""
    coordinator = entry.runtime_data
    async_add_entities([GatewayConnectivity(coordinator)])
    for meter in coordinator.meters.values():
        async_add_entities(
            [MeterConnectivity(coordinator, meter)],
            config_subentry_id=meter.subentry_id,
        )


class GatewayConnectivity(GatewayEntity, BinarySensorEntity):
    """Gateway reachable."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "gateway_connected"

    def __init__(self, coordinator: GatewayCoordinator) -> None:
        super().__init__(coordinator, "connected")

    @property
    def is_on(self) -> bool:
        """Return True if the last cycle could talk to the gateway."""
        return self.coordinator.last_update_success


class MeterConnectivity(MeterEntity, BinarySensorEntity):
    """Meter answered in the last cycle."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "meter_connected"

    def __init__(self, coordinator: GatewayCoordinator, meter: MeterState) -> None:
        super().__init__(coordinator, meter, "connected")

    @property
    def available(self) -> bool:
        """Always available (unless the meter is disabled)."""
        return self.meter.enabled

    @property
    def is_on(self) -> bool:
        """Return True if the meter answered."""
        return self.meter.online
