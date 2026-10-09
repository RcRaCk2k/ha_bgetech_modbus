"""Decode raw Modbus register values."""

from __future__ import annotations

from collections.abc import Sequence
import math
import struct

from .block_planner import ReadBlock
from .register_map import DataType, InfoField, Register


class DecodeError(ValueError):
    """Raised for malformed register data."""


def _bcd(value: int, digits: int) -> int | None:
    result = 0
    for shift in range((digits - 1) * 4, -1, -4):
        nibble = (value >> shift) & 0xF
        if nibble > 9:
            return None
        result = result * 10 + nibble
    return result


def decode_value(data_type: DataType, words: Sequence[int]) -> float | int | None:
    """Decode registers (big endian words, high word first).

    Returns None for values that are not representable (NaN, Inf, invalid BCD).
    """
    if len(words) != data_type.register_count:
        raise DecodeError(
            f"{data_type} needs {data_type.register_count} registers, got {len(words)}"
        )
    match data_type:
        case DataType.UINT16:
            return words[0]
        case DataType.BCD16:
            return _bcd(words[0], 4)
        case DataType.UINT32:
            return (words[0] << 16) | words[1]
        case DataType.INT32:
            raw = (words[0] << 16) | words[1]
            return raw - (1 << 32) if raw & 0x80000000 else raw
        case DataType.BCD32:
            return _bcd((words[0] << 16) | words[1], 8)
        case DataType.FLOAT32:
            value = struct.unpack(">f", struct.pack(">HH", words[0], words[1]))[0]
            if math.isnan(value) or math.isinf(value):
                return None
            return value
    raise DecodeError(f"Unsupported data type {data_type}")  # pragma: no cover


def decode_register(reg: Register, block_start: int, words: Sequence[int]) -> float | None:
    """Decode a register from the words of a block and apply its scale."""
    offset = reg.address - block_start
    if offset < 0 or offset + reg.count > len(words):
        raise DecodeError(f"Register {reg.key} is outside of the block")
    value = decode_value(reg.data_type, words[offset : offset + reg.count])
    if value is None:
        return None
    value = value * reg.scale if reg.scale != 1 else value
    if isinstance(value, float):
        # Remove float32 noise (e.g. 233.6999969 -> 233.7)
        value = float(f"{value:.7g}")
    return value


def decode_block(block: ReadBlock, words: Sequence[int]) -> dict[str, float | None]:
    """Decode all registers of a block."""
    if len(words) != block.count:
        raise DecodeError(f"Block {block} expected {block.count} registers, got {len(words)}")
    return {reg.key: decode_register(reg, block.start, words) for reg in block.registers}


def decode_info(
    fields: Sequence[InfoField], start: int, words: Sequence[int]
) -> dict[str, float | int | None]:
    """Decode device information fields from a block starting at ``start``."""
    result: dict[str, float | int | None] = {}
    for info in fields:
        offset = info.address - start
        count = info.data_type.register_count
        if offset < 0 or offset + count > len(words):
            continue
        value = decode_value(info.data_type, words[offset : offset + count])
        if isinstance(value, float):
            value = float(f"{value:.7g}")
        result[info.key] = value
    return result
