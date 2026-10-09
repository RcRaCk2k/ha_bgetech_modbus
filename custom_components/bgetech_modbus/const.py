"""Constants for the BGETech Modbus integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bgetech_modbus"
MANUFACTURER_GATEWAY: Final = "BGETech Modbus"

SUBENTRY_TYPE_METER: Final = "meter"

# Gateway (config entry data / options)
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_TIMEOUT: Final = "timeout"
CONF_RETRIES: Final = "retries"
CONF_MAX_REGISTERS: Final = "max_registers"

DEFAULT_NAME: Final = "BGETech Gateway"
DEFAULT_PORT: Final = 502
DEFAULT_SCAN_INTERVAL: Final = 5
DEFAULT_TIMEOUT: Final = 5.0
DEFAULT_RETRIES: Final = 2
# 0 = automatic (protocol maximum of 125 registers)
DEFAULT_MAX_REGISTERS: Final = 0

MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 3600

# Meter (subentry data)
CONF_SLAVE_ID: Final = "slave_id"
CONF_MODEL: Final = "model"
CONF_ENABLED: Final = "enabled"
CONF_SCAN_INTERVAL_INSTANT: Final = "scan_interval_instant"
CONF_SCAN_INTERVAL_ENERGY: Final = "scan_interval_energy"

MODEL_AUTO_DRT428M: Final = "auto_drt428m"

MIN_SLAVE_ID: Final = 1
MAX_SLAVE_ID: Final = 247

# Back-off for meters that do not answer
BACKOFF_MAX: Final = 300.0
