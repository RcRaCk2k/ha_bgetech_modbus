"""Register definitions of the supported meter models.

This module is intentionally free of Home Assistant imports so that register
maps, block planning and decoding can be tested in isolation.

Sources are documented per model and in ``docs/reference-analysis.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

FC_READ_HOLDING = 3
FC_READ_INPUT = 4

MAX_REGISTERS_PER_REQUEST = 125


class DataType(StrEnum):
    """Raw data type of a register value."""

    FLOAT32 = "float32"
    UINT16 = "uint16"
    UINT32 = "uint32"
    INT32 = "int32"
    BCD16 = "bcd16"
    BCD32 = "bcd32"

    @property
    def register_count(self) -> int:
        """Return the number of 16 bit registers used by this type."""
        return 1 if self in (DataType.UINT16, DataType.BCD16) else 2


class Kind(StrEnum):
    """Physical meaning of a value, mapped to Home Assistant metadata."""

    VOLTAGE = "voltage"
    CURRENT = "current"
    FREQUENCY = "frequency"
    POWER = "power"
    REACTIVE_POWER = "reactive_power"
    APPARENT_POWER = "apparent_power"
    POWER_FACTOR = "power_factor"
    # Monotonic counters (suitable for total_increasing)
    ENERGY = "energy"
    REACTIVE_ENERGY = "reactive_energy"
    # Counters that may decrease (net values, user resettable counters)
    ENERGY_TOTAL = "energy_total"
    REACTIVE_ENERGY_TOTAL = "reactive_energy_total"
    PHASE_ANGLE = "phase_angle"
    PERCENT = "percent"
    PLAIN = "plain"


class Group(StrEnum):
    """Polling group. Each group can have its own polling interval."""

    INSTANT = "instant"
    ENERGY = "energy"


@dataclass(frozen=True, slots=True)
class Register:
    """A single measured value."""

    key: str
    address: int
    kind: Kind
    group: Group
    function_code: int = FC_READ_HOLDING
    data_type: DataType = DataType.FLOAT32
    scale: float = 1.0
    enabled_default: bool = True
    # Translation key and placeholders for the entity name
    translation_key: str | None = None
    placeholders: dict[str, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        """Number of registers."""
        return self.data_type.register_count

    @property
    def end(self) -> int:
        """Address after the last register (exclusive)."""
        return self.address + self.count


@dataclass(frozen=True, slots=True)
class ReadableRange:
    """An address range that the device answers for (inclusive start, exclusive end)."""

    function_code: int
    start: int
    end: int

    def contains(self, function_code: int, start: int, end: int) -> bool:
        """Return True if the given span is completely inside this range."""
        return function_code == self.function_code and self.start <= start and end <= self.end


@dataclass(frozen=True, slots=True)
class InfoField:
    """A device information value read once after (re)connect."""

    key: str
    address: int
    data_type: DataType


@dataclass(frozen=True, slots=True)
class WritableSetting:
    """A configuration register that may be changed from Home Assistant.

    Only registers listed here can ever be written, and only with one of the
    raw values in ``options`` (single register, FC06).
    """

    key: str
    address: int
    # option name -> raw register value
    options: dict[str, int]
    # info field holding the current value
    info_key: str


@dataclass(frozen=True, slots=True)
class DeviceModel:
    """Description of a meter model."""

    model_id: str
    name: str
    manufacturer: str
    registers: tuple[Register, ...]
    readable_ranges: tuple[ReadableRange, ...]
    source: str
    experimental: bool = False
    info_fields: tuple[InfoField, ...] = ()
    writable_settings: tuple[WritableSetting, ...] = ()
    # Optional register to distinguish model variants (answered -> variant exists)
    probe_address: int | None = None

    def register(self, key: str) -> Register:
        """Return a register by key."""
        for reg in self.registers:
            if reg.key == key:
                return reg
        raise KeyError(key)


PHASES = ("l1", "l2", "l3")


def _phase_regs(
    prefix: str,
    start: int,
    kind: Kind,
    group: Group,
    *,
    with_total: bool,
    total_suffix: str = "total",
    enabled_total: bool = True,
    enabled_phase: bool = True,
    scale: float = 1.0,
    tariff: str | None = None,
) -> list[Register]:
    """Create consecutive float32 registers [total,] L1, L2, L3."""
    regs: list[Register] = []
    addr = start
    base_placeholders = {"tariff": tariff} if tariff else {}
    if with_total:
        regs.append(
            Register(
                key=f"{prefix}_{total_suffix}",
                address=addr,
                kind=kind,
                group=group,
                scale=scale,
                enabled_default=enabled_total,
                translation_key=f"{prefix}_{total_suffix}",
                placeholders=dict(base_placeholders),
            )
        )
        addr += 2
    for phase in PHASES:
        regs.append(
            Register(
                key=f"{prefix}_{phase}",
                address=addr,
                kind=kind,
                group=group,
                scale=scale,
                enabled_default=enabled_phase,
                translation_key=f"{prefix}_phase",
                placeholders={**base_placeholders, "phase": phase.upper()},
            )
        )
        addr += 2
    return regs


# ---------------------------------------------------------------------------
# B+G E-Tech DRT428M-2 / DRT428M-3
# Source: B+G E-Tech "DRT428M-Serie" manual, Modbus register map p. 12-14,
# verified by read-only measurements on 4 x DRT428M-3 (2026-10-09).
# Power values are reported in kW/kvar/kVA, energies in kWh/kvarh.
# ---------------------------------------------------------------------------

_DRT428M_INSTANT: list[Register] = [
    *_phase_regs("voltage", 0x000E, Kind.VOLTAGE, Group.INSTANT, with_total=False),
    Register(
        key="frequency",
        address=0x0014,
        kind=Kind.FREQUENCY,
        group=Group.INSTANT,
        translation_key="frequency",
    ),
    *_phase_regs("current", 0x0016, Kind.CURRENT, Group.INSTANT, with_total=False),
    *_phase_regs("active_power", 0x001C, Kind.POWER, Group.INSTANT, with_total=True),
    *_phase_regs(
        "reactive_power",
        0x0024,
        Kind.REACTIVE_POWER,
        Group.INSTANT,
        with_total=True,
        enabled_phase=False,
    ),
    *_phase_regs(
        "apparent_power",
        0x002C,
        Kind.APPARENT_POWER,
        Group.INSTANT,
        with_total=True,
        enabled_phase=False,
    ),
    *_phase_regs(
        "power_factor",
        0x0034,
        Kind.POWER_FACTOR,
        Group.INSTANT,
        with_total=True,
        enabled_phase=False,
    ),
]

# "Total" registers depend on the meter's "combined code" (register 0x000B):
# 1 = forward only, 5 = forward + reverse, 9 = forward - reverse (net value).
# They are therefore modelled as counters that may decrease.
_DRT428M_ENERGY: list[Register] = [
    *_phase_regs(
        "total_active_energy",
        0x0100,
        Kind.ENERGY_TOTAL,
        Group.ENERGY,
        with_total=True,
        total_suffix="sum",
        enabled_phase=False,
    ),
    *_phase_regs(
        "import_active_energy",
        0x0108,
        Kind.ENERGY,
        Group.ENERGY,
        with_total=True,
        total_suffix="sum",
        enabled_phase=False,
    ),
    *_phase_regs(
        "export_active_energy",
        0x0110,
        Kind.ENERGY,
        Group.ENERGY,
        with_total=True,
        total_suffix="sum",
        enabled_phase=False,
    ),
    *_phase_regs(
        "total_reactive_energy",
        0x0118,
        Kind.REACTIVE_ENERGY_TOTAL,
        Group.ENERGY,
        with_total=True,
        total_suffix="sum",
        enabled_total=False,
        enabled_phase=False,
    ),
    *_phase_regs(
        "import_reactive_energy",
        0x0120,
        Kind.REACTIVE_ENERGY,
        Group.ENERGY,
        with_total=True,
        total_suffix="sum",
        enabled_total=False,
        enabled_phase=False,
    ),
    *_phase_regs(
        "export_reactive_energy",
        0x0128,
        Kind.REACTIVE_ENERGY,
        Group.ENERGY,
        with_total=True,
        total_suffix="sum",
        enabled_total=False,
        enabled_phase=False,
    ),
]


def _drt428m_tariffs() -> list[Register]:
    """Tariff registers T1..T4 (DRT428M-3 only)."""
    regs: list[Register] = []
    layout = (
        ("total_active_energy", Kind.ENERGY_TOTAL),
        ("import_active_energy", Kind.ENERGY),
        ("export_active_energy", Kind.ENERGY),
        ("total_reactive_energy", Kind.REACTIVE_ENERGY_TOTAL),
        ("import_reactive_energy", Kind.REACTIVE_ENERGY),
        ("export_reactive_energy", Kind.REACTIVE_ENERGY),
    )
    addr = 0x0130
    for tariff in range(1, 5):
        for name, kind in layout:
            regs.append(
                Register(
                    key=f"t{tariff}_{name}",
                    address=addr,
                    kind=kind,
                    group=Group.ENERGY,
                    enabled_default=False,
                    translation_key=f"tariff_{name}",
                    placeholders={"tariff": f"T{tariff}"},
                )
            )
            addr += 2
    return regs


_DRT428M_INFO = (
    InfoField("serial_number", 0x0000, DataType.BCD32),
    InfoField("modbus_id", 0x0002, DataType.UINT16),
    InfoField("baud_rate", 0x0003, DataType.UINT16),
    InfoField("sw_version", 0x0004, DataType.FLOAT32),
    InfoField("hw_version", 0x0006, DataType.FLOAT32),
    InfoField("combined_code", 0x000B, DataType.UINT16),
)

# Manual part 3 "The writing registers": 0x000B combined code, FC06,
# 1 = forward only, 5 = forward + reverse (factory default), 9 = forward - reverse
_DRT428M_SETTINGS = (
    WritableSetting(
        key="combined_code",
        address=0x000B,
        options={
            "forward": 1,
            "forward_plus_reverse": 5,
            "forward_minus_reverse": 9,
        },
        info_key="combined_code",
    ),
)

_DRT428M_SOURCE = (
    "B+G E-Tech DRT428M-Serie manual, register map p. 12-14; verified on DRT428M-3 hardware"
)

DRT428M_2 = DeviceModel(
    model_id="drt428m_2",
    name="DRT428M-2",
    manufacturer="B+G E-Tech",
    registers=tuple(_DRT428M_INSTANT + _DRT428M_ENERGY),
    readable_ranges=(
        ReadableRange(FC_READ_HOLDING, 0x0000, 0x000E),
        ReadableRange(FC_READ_HOLDING, 0x000E, 0x003C),
        ReadableRange(FC_READ_HOLDING, 0x0100, 0x0130),
    ),
    info_fields=_DRT428M_INFO,
    writable_settings=_DRT428M_SETTINGS,
    source=_DRT428M_SOURCE,
)

DRT428M_3 = DeviceModel(
    model_id="drt428m_3",
    name="DRT428M-3",
    manufacturer="B+G E-Tech",
    registers=tuple(_DRT428M_INSTANT + _DRT428M_ENERGY + _drt428m_tariffs()),
    readable_ranges=(
        ReadableRange(FC_READ_HOLDING, 0x0000, 0x000E),
        ReadableRange(FC_READ_HOLDING, 0x000E, 0x0042),
        ReadableRange(FC_READ_HOLDING, 0x0100, 0x0160),
    ),
    info_fields=_DRT428M_INFO,
    writable_settings=_DRT428M_SETTINGS,
    source=_DRT428M_SOURCE,
    probe_address=0x0130,
)


MODELS: dict[str, DeviceModel] = {model.model_id: model for model in (DRT428M_2, DRT428M_3)}


def get_model(model_id: str) -> DeviceModel:
    """Return a model by id."""
    return MODELS[model_id]
