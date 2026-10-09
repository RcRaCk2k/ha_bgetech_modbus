"""Simulated Modbus TCP gateway with DRT428M meters behind it."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import struct

from custom_components.bgetech_modbus.register_map import DeviceModel, get_model

# Values measured on a real DRT428M-3 (slave 6 of the reference system)
DRT428M_SAMPLE: dict[int, float] = {
    0x000E: 233.5,
    0x0010: 233.7,
    0x0012: 233.6,
    0x0014: 50.0,
    0x0016: 0.06,
    0x0018: 0.05,
    0x001A: 0.84,
    0x001C: 0.151,
    0x001E: 0.007,
    0x0020: 0.005,
    0x0022: 0.137,
    0x0024: 0.121,
    0x0026: 0.001,
    0x0028: 0.0,
    0x002A: 0.12,
    0x002C: 0.196,
    0x002E: 0.007,
    0x0030: 0.006,
    0x0032: 0.182,
    0x0034: 0.78,
    0x0036: 0.99,
    0x0038: 0.99,
    0x003A: 0.75,
    0x0100: 17766.6,
    0x0102: 7487.79,
    0x0104: 5169.79,
    0x0106: 5128.25,
    0x0108: 17776.2,
    0x010A: 7486.02,
    0x010C: 5161.94,
    0x010E: 5128.25,
    0x0110: 9.62,
    0x0112: 1.77,
    0x0114: 7.85,
    0x0116: 0.0,
    0x0118: -1735.33,
    0x011A: 1285.95,
    0x011C: 720.66,
    0x011E: 225.16,
    0x0120: 248.22,
    0x0122: 87.86,
    0x0124: 73.46,
    0x0126: 86.9,
    0x0128: 1983.55,
    0x012A: 1198.09,
    0x012C: 647.2,
    0x012E: 138.26,
    0x0130: 13157.1,
    0x0132: 13165.5,
    0x0134: 8.43,
    0x0136: -1081.07,
    0x0138: 179.08,
    0x013A: 1260.15,
}


def float_words(value: float) -> tuple[int, int]:
    """Encode a float32 as two big endian registers."""
    return struct.unpack(">HH", struct.pack(">f", value))


@dataclass
class FakeMeter:
    """A simulated meter."""

    model: DeviceModel
    registers: dict[int, int] = field(default_factory=dict)
    online: bool = True
    # Addresses accepting FC06 (DRT428M manual part 3)
    writable: set[int] = field(default_factory=set)
    # Simulate a meter that acknowledges but ignores writes
    ignore_writes: bool = False

    def set_float(self, address: int, value: float) -> None:
        hi, lo = float_words(value)
        self.registers[address] = hi
        self.registers[address + 1] = lo

    def readable(self, fc: int, start: int, count: int) -> bool:
        return any(r.contains(fc, start, start + count) for r in self.model.readable_ranges)


def make_drt428m(
    model_id: str = "drt428m_3", slave_id: int = 1, combined_code: int = 9
) -> FakeMeter:
    """Create a meter filled with sample values."""
    meter = FakeMeter(get_model(model_id))
    for addr in range(0x0000, 0x0042):
        meter.registers[addr] = 0
    meter.registers[0x0002] = slave_id
    meter.registers[0x0003] = 9600
    meter.set_float(0x0004, 1.02)
    meter.set_float(0x0006, 1.0)
    meter.registers[0x000B] = combined_code
    meter.writable = {0x0002, 0x0003, 0x000B, 0x000D}
    for addr, value in DRT428M_SAMPLE.items():
        if model_id == "drt428m_2" and addr >= 0x0130:
            continue
        meter.set_float(addr, value)
    return meter


class FakeGateway:
    """Modbus TCP server. Unknown addresses and offline meters are not answered."""

    def __init__(self) -> None:
        self.meters: dict[int, FakeMeter] = {}
        self.requests: list[tuple[int, int, int, int]] = []
        self.writes: list[tuple[int, int, int]] = []
        self.max_in_flight = 0
        self.delay = 0.0
        self._in_flight = 0
        self._server: asyncio.base_events.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.port = 0

    async def start(self, port: int = 0) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        await self.drop_connections()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def drop_connections(self) -> None:
        for writer in list(self._writers):
            writer.close()
        self._writers.clear()
        await asyncio.sleep(0)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            while True:
                header = await reader.readexactly(7)
                tid, _proto, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                fc = pdu[0]
                self._in_flight += 1
                self.max_in_flight = max(self.max_in_flight, self._in_flight)
                try:
                    if self.delay:
                        await asyncio.sleep(self.delay)
                    answer = self._answer(unit, fc, pdu)
                finally:
                    self._in_flight -= 1
                if answer is None:
                    continue
                writer.write(struct.pack(">HHHB", tid, 0, len(answer) + 1, unit) + answer)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    def _answer(self, unit: int, fc: int, pdu: bytes) -> bytes | None:
        if fc == 6:
            return self._write(unit, pdu)
        if fc not in (3, 4):
            return bytes([fc | 0x80, 1])
        address, count = struct.unpack(">HH", pdu[1:5])
        self.requests.append((unit, fc, address, count))
        meter = self.meters.get(unit)
        if meter is None or not meter.online:
            return None
        if not meter.readable(fc, address, count):
            # Like the DRT428M: invalid addresses are not answered at all
            return None
        words = [meter.registers.get(a, 0) for a in range(address, address + count)]
        return bytes([fc, count * 2]) + struct.pack(f">{count}H", *words)

    def _write(self, unit: int, pdu: bytes) -> bytes | None:
        address, value = struct.unpack(">HH", pdu[1:5])
        self.writes.append((unit, address, value))
        meter = self.meters.get(unit)
        if meter is None or not meter.online:
            return None
        if address not in meter.writable:
            return bytes([0x86, 2])
        if address == 0x000B and value not in (1, 5, 9):
            return bytes([0x86, 3])
        if not meter.ignore_writes:
            meter.registers[address] = value
        return pdu[:5]
