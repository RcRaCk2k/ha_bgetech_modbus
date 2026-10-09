"""Polling coordinator: one per gateway, reading all meters sequentially."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .block_planner import ReadBlock, plan_blocks
from .const import (
    BACKOFF_MAX,
    CONF_ENABLED,
    CONF_MAX_REGISTERS,
    CONF_MODEL,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL_ENERGY,
    CONF_SCAN_INTERVAL_INSTANT,
    CONF_SLAVE_ID,
    CONF_TIMEOUT,
    DEFAULT_MAX_REGISTERS,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SUBENTRY_TYPE_METER,
)
from .decoder import DecodeError, decode_block, decode_info
from .modbus_client import ModbusConnectionError, ModbusError, ModbusTcpClient
from .register_map import DeviceModel, Group, get_model

_LOGGER = logging.getLogger(__name__)

type BGETechConfigEntry = ConfigEntry[GatewayCoordinator]


def gateway_option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return a gateway setting (options override data)."""
    return entry.options.get(key, entry.data.get(key, default))


def meter_device_identifier(entry: ConfigEntry, slave_id: int) -> tuple[str, str]:
    """Stable device identifier of a meter (independent of its name)."""
    return (DOMAIN, f"{entry.entry_id}_{slave_id}")


def gateway_device_identifier(entry: ConfigEntry) -> tuple[str, str]:
    """Stable device identifier of a gateway."""
    return (DOMAIN, entry.entry_id)


@dataclass(slots=True)
class MeterState:
    """Runtime state of one meter."""

    subentry_id: str
    slave_id: int
    name: str
    model: DeviceModel
    enabled: bool
    intervals: dict[Group, float]
    blocks: list[ReadBlock]
    values: dict[str, float | None] = field(default_factory=dict)
    info: dict[str, Any] | None = None
    block_ok: dict[int, bool] = field(default_factory=dict)
    block_last_read: dict[int, float] = field(default_factory=dict)
    online: bool = False
    failures: int = 0
    next_attempt: float = 0.0
    last_success: datetime | None = None
    last_error: str | None = None
    error_count: int = 0

    def block_index(self, key: str) -> int | None:
        """Return the index of the block containing ``key``."""
        for idx, block in enumerate(self.blocks):
            if any(reg.key == key for reg in block.registers):
                return idx
        return None

    def value_available(self, key: str) -> bool:
        """Return True if the value of ``key`` comes from a successful read."""
        idx = self.block_index(key)
        return self.enabled and self.online and idx is not None and self.block_ok.get(idx, False)


@dataclass(slots=True)
class CycleStats:
    """Statistics of the last polling cycle."""

    started: datetime | None = None
    duration_ms: float | None = None
    requests: int = 0
    meters_ok: int = 0
    meters_failed: int = 0
    meters_skipped: int = 0
    cycles: int = 0
    duration_ms_total: float = 0.0

    @property
    def average_duration_ms(self) -> float | None:
        """Average cycle duration."""
        return self.duration_ms_total / self.cycles if self.cycles else None


class GatewayCoordinator(DataUpdateCoordinator[CycleStats]):
    """Read all meters of one gateway in one sequential cycle."""

    config_entry: BGETechConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BGETechConfigEntry,
        client: ModbusTcpClient | None = None,
    ) -> None:
        self.base_interval = float(gateway_option(entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        self.client = client or ModbusTcpClient(
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            timeout=float(gateway_option(entry, CONF_TIMEOUT, DEFAULT_TIMEOUT)),
            retries=int(gateway_option(entry, CONF_RETRIES, DEFAULT_RETRIES)),
        )
        max_registers = (
            int(gateway_option(entry, CONF_MAX_REGISTERS, DEFAULT_MAX_REGISTERS)) or None
        )
        self.meters: dict[str, MeterState] = {}
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_METER:
                continue
            data = subentry.data
            model = get_model(data[CONF_MODEL])
            intervals = {
                Group.INSTANT: float(data.get(CONF_SCAN_INTERVAL_INSTANT) or self.base_interval),
                Group.ENERGY: float(data.get(CONF_SCAN_INTERVAL_ENERGY) or self.base_interval),
            }
            self.meters[subentry.subentry_id] = MeterState(
                subentry_id=subentry.subentry_id,
                slave_id=int(data[CONF_SLAVE_ID]),
                name=subentry.title,
                model=model,
                enabled=bool(data.get(CONF_ENABLED, True)),
                intervals=intervals,
                blocks=plan_blocks(model, max_registers=max_registers),
            )
        self.tick = min(
            [self.base_interval]
            + [
                interval
                for meter in self.meters.values()
                if meter.enabled
                for interval in meter.intervals.values()
            ]
        )
        self.stats = CycleStats()
        self.gateway_device_id: str | None = None
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self.error_count = 0
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=self.tick),
            always_update=True,
        )

    @property
    def gateway_name(self) -> str:
        """Configured gateway name."""
        return self.config_entry.data.get(CONF_NAME, self.config_entry.title)

    async def async_shutdown(self) -> None:
        """Close the connection on unload."""
        await super().async_shutdown()
        await self.client.close()

    def _is_due(self, meter: MeterState, idx: int, now: float) -> bool:
        last = meter.block_last_read.get(idx)
        if last is None or not meter.block_ok.get(idx, False):
            return True
        interval = meter.intervals[meter.blocks[idx].group]
        tolerance = min(1.0, self.tick * 0.2)
        return now - last >= interval - tolerance

    async def _async_update_data(self) -> CycleStats:
        """Run one polling cycle over all meters."""
        started = time.monotonic()
        requests_before = self.client.stats.requests
        stats = self.stats
        stats.started = dt_util.utcnow()
        stats.meters_ok = stats.meters_failed = stats.meters_skipped = 0

        try:
            await self.client.connect()
        except ModbusConnectionError as err:
            self._record_gateway_error(str(err))
            for meter in self.meters.values():
                meter.online = False
            self._finish_cycle(started, requests_before)
            raise UpdateFailed(str(err)) from err

        for meter in self.meters.values():
            if not meter.enabled:
                continue
            now = time.monotonic()
            if now < meter.next_attempt:
                stats.meters_skipped += 1
                continue
            try:
                await self._poll_meter(meter)
            except ModbusConnectionError as err:
                # The gateway itself is gone: not the fault of this meter
                self._record_gateway_error(str(err))
                for other in self.meters.values():
                    other.online = False
                    other.block_ok.clear()
                self._finish_cycle(started, requests_before)
                raise UpdateFailed(str(err)) from err
            if meter.online:
                stats.meters_ok += 1
            else:
                stats.meters_failed += 1

        if stats.meters_ok:
            self.last_success = dt_util.utcnow()
        self._finish_cycle(started, requests_before)
        return stats

    def _finish_cycle(self, started: float, requests_before: int) -> None:
        stats = self.stats
        duration = time.monotonic() - started
        stats.duration_ms = duration * 1000
        stats.requests = self.client.stats.requests - requests_before
        stats.cycles += 1
        stats.duration_ms_total += stats.duration_ms
        # Keep the cadence: the next cycle is scheduled after this one ended.
        self.update_interval = timedelta(seconds=max(self.tick - duration, 0.2))
        if duration > self.tick:
            _LOGGER.debug(
                "Polling cycle of %s took %.2f s (interval %.1f s)",
                self.gateway_name,
                duration,
                self.tick,
            )

    def _record_gateway_error(self, message: str) -> None:
        self.last_error = message
        self.error_count += 1

    async def _poll_meter(self, meter: MeterState) -> None:
        """Read all due blocks of one meter. Errors only affect this meter."""
        client = self.client
        try:
            if meter.info is None and meter.model.info_fields:
                await self._read_info(meter)
            now = time.monotonic()
            for idx, block in enumerate(meter.blocks):
                if not self._is_due(meter, idx, now):
                    continue
                words = await client.read_registers(
                    meter.slave_id, block.function_code, block.start, block.count
                )
                meter.values.update(decode_block(block, words))
                meter.block_ok[idx] = True
                meter.block_last_read[idx] = time.monotonic()
        except ModbusConnectionError:
            raise
        except (ModbusError, DecodeError) as err:
            self._meter_failed(meter, err)
            return
        if not meter.online:
            _LOGGER.info("Meter %s (slave %s) is reachable", meter.name, meter.slave_id)
        meter.online = True
        meter.failures = 0
        meter.next_attempt = 0.0
        meter.last_success = dt_util.utcnow()

    async def _read_info(self, meter: MeterState) -> None:
        fields = meter.model.info_fields
        start = min(f.address for f in fields)
        end = max(f.address + f.data_type.register_count for f in fields)
        words = await self.client.read_registers(meter.slave_id, 3, start, end - start)
        meter.info = decode_info(fields, start, words)
        self._update_device_info(meter)

    def _update_device_info(self, meter: MeterState) -> None:
        info = meter.info or {}
        registry = dr.async_get(self.hass)
        identifier = meter_device_identifier(self.config_entry, meter.slave_id)
        if hasattr(registry, "async_get_device_by_identifier"):  # HA >= 2026.10
            device = registry.async_get_device_by_identifier(identifier, self.config_entry.entry_id)
        else:  # pragma: no cover
            device = registry.async_get_device(identifiers={identifier})
        if device is None:
            return
        changes: dict[str, Any] = {}
        if (sw := info.get("sw_version")) is not None:
            changes["sw_version"] = f"{sw:g}"
        if (hw := info.get("hw_version")) is not None:
            changes["hw_version"] = f"{hw:g}"
        if serial := info.get("serial_number"):
            changes["serial_number"] = f"{serial:08d}"
        if changes:
            registry.async_update_device(device.id, **changes)

    async def async_write_setting(self, meter: MeterState, key: str, option: str) -> None:
        """Change a whitelisted configuration register of a meter.

        The new value is read back from the meter afterwards.
        """
        setting = next((s for s in meter.model.writable_settings if s.key == key), None)
        if setting is None or option not in setting.options:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_setting",
                translation_placeholders={"setting": key, "option": option},
            )
        value = setting.options[option]
        old = (meter.info or {}).get(setting.info_key)
        _LOGGER.warning(
            "Changing %s of meter %s (slave %s) from %s to %s (register 0x%04X)",
            key,
            meter.name,
            meter.slave_id,
            old,
            value,
            setting.address,
        )
        try:
            await self.client.write_single_register(meter.slave_id, setting.address, value)
            await self._read_info(meter)
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"name": meter.name, "error": str(err)},
            ) from err
        if (meter.info or {}).get(setting.info_key) != value:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_not_applied",
                translation_placeholders={"name": meter.name},
            )
        self.async_update_listeners()

    def _meter_failed(self, meter: MeterState, err: Exception) -> None:
        was_online = meter.online or meter.failures == 0
        meter.online = False
        meter.failures += 1
        meter.error_count += 1
        meter.last_error = str(err)
        meter.block_ok.clear()
        # Re-read device info after recovery (meter may have been replaced)
        meter.info = None
        backoff = min(self.tick * (2 ** (meter.failures - 1)), BACKOFF_MAX)
        meter.next_attempt = time.monotonic() + backoff
        self._record_gateway_error(f"Slave {meter.slave_id}: {err}")
        if was_online:
            _LOGGER.warning(
                "Meter %s (slave %s) not reachable: %s", meter.name, meter.slave_id, err
            )
        else:
            _LOGGER.debug(
                "Meter %s (slave %s) still not reachable, next attempt in %.0f s: %s",
                meter.name,
                meter.slave_id,
                backoff,
                err,
            )
