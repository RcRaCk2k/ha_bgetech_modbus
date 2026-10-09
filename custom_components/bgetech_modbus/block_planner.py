"""Plan Modbus read blocks from register definitions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .register_map import (
    MAX_REGISTERS_PER_REQUEST,
    DeviceModel,
    Group,
    ReadableRange,
    Register,
)

# Reading a few unused registers is cheaper than an additional request
# (request overhead ~ 15-20 ms on a 9600 bit/s bus, one register ~ 2.3 ms).
DEFAULT_MAX_GAP = 8


@dataclass(frozen=True, slots=True)
class ReadBlock:
    """A contiguous range of registers read with one request."""

    function_code: int
    start: int
    count: int
    group: Group
    registers: tuple[Register, ...]

    @property
    def end(self) -> int:
        """Address after the last register (exclusive)."""
        return self.start + self.count

    def __str__(self) -> str:
        return (
            f"FC{self.function_code:02d} 0x{self.start:04X}+{self.count} "
            f"({self.group}, {len(self.registers)} values)"
        )


def _range_for(ranges: Iterable[ReadableRange], reg: Register) -> ReadableRange | None:
    for rng in ranges:
        if rng.contains(reg.function_code, reg.address, reg.end):
            return rng
    return None


def plan_blocks(
    model: DeviceModel,
    *,
    max_registers: int | None = None,
    max_gap: int = DEFAULT_MAX_GAP,
    registers: Iterable[Register] | None = None,
) -> list[ReadBlock]:
    """Compute read blocks for a model.

    Rules:
    - registers with different function codes or polling groups are never merged
    - a block never leaves a readable range of the model (the meters do not
      answer reads touching undefined addresses)
    - a block never exceeds ``max_registers``
    - gaps between registers are only bridged if they are at most ``max_gap``
    """
    limit = min(max_registers or MAX_REGISTERS_PER_REQUEST, MAX_REGISTERS_PER_REQUEST)
    regs = list(model.registers if registers is None else registers)

    for reg in regs:
        if reg.count > limit:
            raise ValueError(f"Register {reg.key} does not fit into {limit} registers")
        if _range_for(model.readable_ranges, reg) is None:
            raise ValueError(
                f"Register {reg.key} (0x{reg.address:04X}) of {model.model_id} "
                "is outside of all readable ranges"
            )

    regs.sort(key=lambda r: (r.function_code, r.group, r.address))

    blocks: list[ReadBlock] = []
    current: list[Register] = []
    current_range: ReadableRange | None = None

    def flush() -> None:
        if not current:
            return
        start = current[0].address
        end = max(r.end for r in current)
        blocks.append(
            ReadBlock(
                function_code=current[0].function_code,
                start=start,
                count=end - start,
                group=current[0].group,
                registers=tuple(current),
            )
        )
        current.clear()

    for reg in regs:
        rng = _range_for(model.readable_ranges, reg)
        if current:
            first = current[0]
            cur_end = max(r.end for r in current)
            if (
                reg.function_code == first.function_code
                and reg.group == first.group
                and rng is current_range
                and reg.address - cur_end <= max_gap
                and max(cur_end, reg.end) - first.address <= limit
            ):
                current.append(reg)
                continue
            flush()
        current.append(reg)
        current_range = rng
    flush()
    blocks.sort(key=lambda b: (b.function_code, b.start))
    return blocks
