"""Sensor platform."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactiveEnergy,
    UnitOfReactivePower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BGETechConfigEntry, GatewayCoordinator, MeterState
from .entity import GatewayEntity, MeterEntity
from .register_map import Kind, Register

PARALLEL_UPDATES = 0


@dataclass(frozen=True, slots=True)
class KindMeta:
    """Home Assistant metadata of a value kind."""

    device_class: SensorDeviceClass | None
    unit: str | None
    state_class: SensorStateClass | None
    precision: int | None
    suggested_unit: str | None = None


# Units are the device's native units; Home Assistant converts to the
# suggested unit (e.g. kW -> W) without manual scaling in this integration.
KIND_META: dict[Kind, KindMeta] = {
    Kind.VOLTAGE: KindMeta(
        SensorDeviceClass.VOLTAGE,
        UnitOfElectricPotential.VOLT,
        SensorStateClass.MEASUREMENT,
        1,
    ),
    Kind.CURRENT: KindMeta(
        SensorDeviceClass.CURRENT,
        UnitOfElectricCurrent.AMPERE,
        SensorStateClass.MEASUREMENT,
        2,
    ),
    Kind.FREQUENCY: KindMeta(
        SensorDeviceClass.FREQUENCY,
        UnitOfFrequency.HERTZ,
        SensorStateClass.MEASUREMENT,
        2,
    ),
    Kind.POWER: KindMeta(
        SensorDeviceClass.POWER,
        UnitOfPower.KILO_WATT,
        SensorStateClass.MEASUREMENT,
        3,
        UnitOfPower.WATT,
    ),
    Kind.REACTIVE_POWER: KindMeta(
        SensorDeviceClass.REACTIVE_POWER,
        UnitOfReactivePower.KILO_VOLT_AMPERE_REACTIVE,
        SensorStateClass.MEASUREMENT,
        3,
        UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    ),
    Kind.APPARENT_POWER: KindMeta(
        SensorDeviceClass.APPARENT_POWER,
        UnitOfApparentPower.KILO_VOLT_AMPERE,
        SensorStateClass.MEASUREMENT,
        3,
        UnitOfApparentPower.VOLT_AMPERE,
    ),
    Kind.POWER_FACTOR: KindMeta(
        SensorDeviceClass.POWER_FACTOR, None, SensorStateClass.MEASUREMENT, 2
    ),
    Kind.ENERGY: KindMeta(
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorStateClass.TOTAL_INCREASING,
        2,
    ),
    Kind.ENERGY_TOTAL: KindMeta(
        SensorDeviceClass.ENERGY,
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorStateClass.TOTAL,
        2,
    ),
    Kind.REACTIVE_ENERGY: KindMeta(
        SensorDeviceClass.REACTIVE_ENERGY,
        UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        SensorStateClass.TOTAL_INCREASING,
        2,
    ),
    Kind.REACTIVE_ENERGY_TOTAL: KindMeta(
        SensorDeviceClass.REACTIVE_ENERGY,
        UnitOfReactiveEnergy.KILO_VOLT_AMPERE_REACTIVE_HOUR,
        SensorStateClass.TOTAL,
        2,
    ),
    Kind.PHASE_ANGLE: KindMeta(None, DEGREE, SensorStateClass.MEASUREMENT, 1),
    Kind.PERCENT: KindMeta(None, PERCENTAGE, SensorStateClass.MEASUREMENT, 1),
    Kind.PLAIN: KindMeta(None, None, SensorStateClass.MEASUREMENT, 2),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BGETechConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors for the gateway and all meters."""
    coordinator = entry.runtime_data
    async_add_entities(GatewaySensor(coordinator, key) for key in GATEWAY_SENSORS)
    for meter in coordinator.meters.values():
        entities: list[SensorEntity] = [
            MeterValueSensor(coordinator, meter, reg) for reg in meter.model.registers
        ]
        async_add_entities(entities, config_subentry_id=meter.subentry_id)


class MeterValueSensor(MeterEntity, SensorEntity):
    """A measured value of a meter."""

    def __init__(
        self, coordinator: GatewayCoordinator, meter: MeterState, register: Register
    ) -> None:
        super().__init__(coordinator, meter, register.key)
        self.register = register
        meta = KIND_META[register.kind]
        self._attr_translation_key = register.translation_key or register.key
        self._attr_translation_placeholders = dict(register.placeholders)
        self._attr_device_class = meta.device_class
        self._attr_native_unit_of_measurement = meta.unit
        self._attr_state_class = meta.state_class
        self._attr_suggested_display_precision = meta.precision
        if meta.suggested_unit:
            self._attr_suggested_unit_of_measurement = meta.suggested_unit
        self._attr_entity_registry_enabled_default = register.enabled_default

    @property
    def available(self) -> bool:
        """Available if the block of this value was read successfully."""
        return super().available and self.meter.value_available(self.key)

    @property
    def native_value(self) -> float | None:
        """Return the decoded value."""
        return self.meter.values.get(self.key)


GATEWAY_SENSORS = (
    "last_success",
    "last_error",
    "error_count",
    "cycle_duration",
    "average_cycle_duration",
    "requests_per_cycle",
    "average_response_time",
    "reconnects",
    "meters_online",
)


class GatewaySensor(GatewayEntity, SensorEntity):
    """Diagnostic values of the gateway communication."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GatewayCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self.key = key
        self._attr_translation_key = key
        match key:
            case "last_success":
                self._attr_device_class = SensorDeviceClass.TIMESTAMP
            case "cycle_duration" | "average_cycle_duration" | "average_response_time":
                self._attr_device_class = SensorDeviceClass.DURATION
                self._attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
                self._attr_state_class = SensorStateClass.MEASUREMENT
                self._attr_suggested_display_precision = 0
            case "error_count" | "reconnects":
                self._attr_state_class = SensorStateClass.TOTAL_INCREASING
            case "requests_per_cycle" | "meters_online":
                self._attr_state_class = SensorStateClass.MEASUREMENT
        if key in ("average_cycle_duration", "average_response_time", "reconnects"):
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> str | int | float | datetime | None:
        """Return the value."""
        coordinator = self.coordinator
        client_stats = coordinator.client.stats
        stats = coordinator.stats
        match self.key:
            case "last_success":
                return coordinator.last_success
            case "last_error":
                return coordinator.last_error[:255] if coordinator.last_error else None
            case "error_count":
                return coordinator.error_count
            case "cycle_duration":
                return stats.duration_ms
            case "average_cycle_duration":
                return stats.average_duration_ms
            case "requests_per_cycle":
                return stats.requests
            case "average_response_time":
                return client_stats.average_response_ms
            case "reconnects":
                return client_stats.reconnects
            case "meters_online":
                return sum(1 for m in coordinator.meters.values() if m.online)
        return None
