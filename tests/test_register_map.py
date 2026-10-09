"""Register definitions, decoding and block planning (no Home Assistant needed)."""

from __future__ import annotations

import math
import struct

import pytest

from custom_components.bgetech_modbus.block_planner import plan_blocks
from custom_components.bgetech_modbus.decoder import (
    DecodeError,
    decode_block,
    decode_info,
    decode_value,
)
from custom_components.bgetech_modbus.register_map import (
    DRT428M_2,
    DRT428M_3,
    MODELS,
    DataType,
    DeviceModel,
    Group,
    Kind,
    ReadableRange,
    Register,
)

from .fake_modbus import DRT428M_SAMPLE, make_drt428m


def test_float32_big_endian_word_order() -> None:
    """Float32 is ABCD: high word first, big endian bytes."""
    # Raw words read from a real DRT428M-3: 233.5 V and 50 Hz
    assert decode_value(DataType.FLOAT32, [0x4369, 0x8000]) == 233.5
    assert decode_value(DataType.FLOAT32, [0x4248, 0x0000]) == 50.0
    # Swapped word order must not give the same result
    assert decode_value(DataType.FLOAT32, [0x8000, 0x4369]) != 233.5
    assert decode_value(DataType.FLOAT32, [0xC56B, 0x835C]) == pytest.approx(-3768.21, abs=0.01)


@pytest.mark.parametrize("words", [[0x7FC0, 0x0000], [0x7F80, 0x0000], [0xFF80, 0x0000]])
def test_invalid_floats_are_none(words: list[int]) -> None:
    """NaN and +/-Inf are reported as None (unknown)."""
    assert decode_value(DataType.FLOAT32, words) is None


def test_integer_and_bcd_types() -> None:
    """Integer and BCD types."""
    assert decode_value(DataType.UINT16, [0x2580]) == 9600
    assert decode_value(DataType.UINT32, [0x0001, 0x0002]) == 65538
    assert decode_value(DataType.INT32, [0xFFFF, 0xFFFE]) == -2
    assert decode_value(DataType.BCD32, [0x1234, 0x5678]) == 12345678
    assert decode_value(DataType.BCD16, [0x0A00]) is None
    with pytest.raises(DecodeError):
        decode_value(DataType.FLOAT32, [1])


def test_drt428m_register_map_matches_manual() -> None:
    """Spot checks against the B+G E-Tech manual."""
    reg = DRT428M_3.register
    assert reg("voltage_l1").address == 0x000E
    assert reg("frequency").address == 0x0014
    assert reg("current_l3").address == 0x001A
    assert reg("active_power_total").address == 0x001C
    assert reg("power_factor_l3").address == 0x003A
    assert reg("total_active_energy_sum").address == 0x0100
    assert reg("import_active_energy_sum").address == 0x0108
    assert reg("export_active_energy_sum").address == 0x0110
    assert reg("export_reactive_energy_l3").address == 0x012E
    assert reg("t1_total_active_energy").address == 0x0130
    assert reg("t4_export_reactive_energy").address == 0x015E
    # 23 instantaneous values + 24 energy values (+ 24 tariff values on -3)
    assert len(DRT428M_2.registers) == 47
    assert len(DRT428M_3.registers) == 71
    assert all(r.function_code == 3 for r in DRT428M_3.registers)
    keys = [r.key for r in DRT428M_3.registers]
    assert len(keys) == len(set(keys))


def test_energy_semantics() -> None:
    """Import/export are monotonic, 'total' registers may decrease (combined code 9)."""
    reg = DRT428M_3.register
    assert reg("import_active_energy_sum").kind is Kind.ENERGY
    assert reg("export_active_energy_sum").kind is Kind.ENERGY
    assert reg("total_active_energy_sum").kind is Kind.ENERGY_TOTAL
    assert reg("total_reactive_energy_sum").kind is Kind.REACTIVE_ENERGY_TOTAL
    assert reg("t1_total_active_energy").kind is Kind.ENERGY_TOTAL


def test_decode_drt428m_blocks() -> None:
    """All values of the sample meter are decoded correctly."""
    meter = make_drt428m()
    blocks = plan_blocks(DRT428M_3)
    values: dict[str, float | None] = {}
    for block in blocks:
        words = [meter.registers.get(a, 0) for a in range(block.start, block.end)]
        values.update(decode_block(block, words))
    by_address = {r.address: r.key for r in DRT428M_3.registers}
    for address, expected in DRT428M_SAMPLE.items():
        assert values[by_address[address]] == pytest.approx(expected, rel=1e-6), hex(address)
    # Float32 noise is removed
    assert values["voltage_l2"] == 233.7
    assert values["t4_total_active_energy"] == 0.0


def test_scaling() -> None:
    """Scale factors are applied."""
    model = DeviceModel(
        model_id="test",
        name="Test",
        manufacturer="Test",
        registers=(
            Register("a", 0, Kind.VOLTAGE, Group.INSTANT, data_type=DataType.UINT16, scale=0.1),
            Register("b", 1, Kind.POWER, Group.INSTANT, scale=1000),
        ),
        readable_ranges=(ReadableRange(3, 0, 3),),
        source="test",
    )
    (block,) = plan_blocks(model)
    hi, lo = struct.unpack(">HH", struct.pack(">f", 0.151))
    values = decode_block(block, [2305, hi, lo])
    assert values["a"] == pytest.approx(230.5)
    assert values["b"] == pytest.approx(151.0)


def test_decode_info() -> None:
    """Device information block of the DRT428M."""
    meter = make_drt428m(slave_id=6)
    words = [meter.registers[a] for a in range(0, 14)]
    info = decode_info(DRT428M_3.info_fields, 0, words)
    assert info == {
        "serial_number": 0,
        "modbus_id": 6,
        "baud_rate": 9600,
        "sw_version": 1.02,
        "hw_version": 1.0,
        "combined_code": 9,
    }


def test_block_plan_drt428m_3() -> None:
    """Two requests: instantaneous values and all energy counters incl. tariffs."""
    blocks = plan_blocks(DRT428M_3)
    assert [(b.start, b.count, b.group) for b in blocks] == [
        (0x000E, 46, Group.INSTANT),
        (0x0100, 96, Group.ENERGY),
    ]
    assert sum(len(b.registers) for b in blocks) == len(DRT428M_3.registers)


def test_block_plan_drt428m_2() -> None:
    """The -2 has no tariff registers."""
    blocks = plan_blocks(DRT428M_2)
    assert [(b.start, b.count) for b in blocks] == [(0x000E, 46), (0x0100, 48)]


@pytest.mark.parametrize("limit", [2, 10, 31, 40, 64, 125])
def test_block_plan_respects_limit(limit: int) -> None:
    """Blocks never exceed the limit and never leave readable ranges."""
    for model in MODELS.values():
        blocks = plan_blocks(model, max_registers=limit)
        covered = set()
        for block in blocks:
            assert block.count <= limit
            assert any(
                r.contains(block.function_code, block.start, block.end)
                for r in model.readable_ranges
            )
            assert len({r.group for r in block.registers}) == 1
            for reg in block.registers:
                assert block.start <= reg.address and reg.end <= block.end
                covered.add(reg.key)
        assert covered == {r.key for r in model.registers}


def test_block_plan_gaps_and_function_codes() -> None:
    """Gaps are bridged only when small; function codes are never mixed."""
    regs = (
        Register("a", 0, Kind.PLAIN, Group.INSTANT),
        Register("b", 4, Kind.PLAIN, Group.INSTANT),  # gap 2 -> merged
        Register("c", 40, Kind.PLAIN, Group.INSTANT),  # gap 34 -> new block
        Register("d", 6, Kind.PLAIN, Group.INSTANT, function_code=4),
    )
    model = DeviceModel(
        "t",
        "T",
        "T",
        regs,
        (ReadableRange(3, 0, 100), ReadableRange(4, 0, 100)),
        source="test",
    )
    blocks = plan_blocks(model)
    assert [(b.function_code, b.start, b.count) for b in blocks] == [
        (3, 0, 6),
        (3, 40, 2),
        (4, 6, 2),
    ]


def test_block_plan_does_not_bridge_ranges() -> None:
    """Adjacent but separate readable ranges are not merged (undefined addresses)."""
    regs = (
        Register("a", 0, Kind.PLAIN, Group.INSTANT),
        Register("b", 4, Kind.PLAIN, Group.INSTANT),
    )
    model = DeviceModel(
        "t", "T", "T", regs, (ReadableRange(3, 0, 2), ReadableRange(3, 4, 6)), source="t"
    )
    assert len(plan_blocks(model)) == 2


def test_register_outside_ranges_is_rejected() -> None:
    """Definitions outside readable ranges are a programming error."""
    model = DeviceModel(
        "t",
        "T",
        "T",
        (Register("a", 10, Kind.PLAIN, Group.INSTANT),),
        (ReadableRange(3, 0, 4),),
        source="t",
    )
    with pytest.raises(ValueError):
        plan_blocks(model)


def test_no_nan_in_sample() -> None:
    """Sanity check of the fixture."""
    assert not any(math.isnan(v) for v in DRT428M_SAMPLE.values())
