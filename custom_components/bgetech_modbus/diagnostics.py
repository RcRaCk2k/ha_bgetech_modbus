"""Diagnostics support."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import BGETechConfigEntry

TO_REDACT = {CONF_HOST, "serial_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BGETechConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a gateway."""
    coordinator = entry.runtime_data
    client = coordinator.client
    stats = coordinator.stats
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "gateway": {
            "connected": client.connected,
            "last_update_success": coordinator.last_update_success,
            "last_success": coordinator.last_success,
            "last_error": coordinator.last_error,
            "error_count": coordinator.error_count,
            "tick_seconds": coordinator.tick,
            "client": asdict(client.stats),
            "average_response_ms": client.stats.average_response_ms,
            "cycle": {
                "duration_ms": stats.duration_ms,
                "average_duration_ms": stats.average_duration_ms,
                "requests": stats.requests,
                "cycles": stats.cycles,
                "meters_ok": stats.meters_ok,
                "meters_failed": stats.meters_failed,
                "meters_skipped": stats.meters_skipped,
            },
        },
        "meters": [
            {
                "slave_id": meter.slave_id,
                "model": meter.model.model_id,
                "enabled": meter.enabled,
                "online": meter.online,
                "intervals": {str(k): v for k, v in meter.intervals.items()},
                "blocks": [str(block) for block in meter.blocks],
                "block_ok": meter.block_ok,
                "failures": meter.failures,
                "error_count": meter.error_count,
                "last_error": meter.last_error,
                "last_success": meter.last_success,
                "info": async_redact_data(meter.info or {}, TO_REDACT),
                "values": meter.values,
            }
            for meter in coordinator.meters.values()
        ],
    }
