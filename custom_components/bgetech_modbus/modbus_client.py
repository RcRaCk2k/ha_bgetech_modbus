"""Minimal asyncio Modbus TCP client.

Implemented function codes: 03 (read holding registers), 04 (read input
registers) and 06 (write single register). Writing is only used for the
explicitly whitelisted configuration registers of a device model (see
``WritableSetting`` in register_map); the coordinator enforces this.

All requests of one gateway are serialised with a lock, because the
gateway forwards them to a single RS485 bus.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
import logging
import struct
import time

from .register_map import FC_READ_HOLDING, FC_READ_INPUT, MAX_REGISTERS_PER_REQUEST

_LOGGER = logging.getLogger(__name__)

ALLOWED_FUNCTION_CODES = frozenset({FC_READ_HOLDING, FC_READ_INPUT})
FC_WRITE_SINGLE = 6


class ModbusError(Exception):
    """Base class of all Modbus errors."""


class ModbusConnectionError(ModbusError):
    """The gateway could not be reached or closed the connection."""


class ModbusTimeoutError(ModbusError):
    """No (complete) answer within the timeout."""


class ModbusProtocolError(ModbusError):
    """The answer was malformed."""


class ModbusExceptionResponse(ModbusError):
    """The device answered with a Modbus exception."""

    def __init__(self, unit: int, function_code: int, code: int) -> None:
        super().__init__(f"Unit {unit} returned Modbus exception {code} for FC{function_code:02d}")
        self.unit = unit
        self.function_code = function_code
        self.code = code


@dataclass(slots=True)
class ClientStats:
    """Counters for diagnostics."""

    requests: int = 0
    errors: int = 0
    timeouts: int = 0
    connects: int = 0
    reconnects: int = 0
    last_error: str | None = None
    last_response_ms: float | None = None
    response_ms_total: float = 0.0
    response_count: int = 0
    exceptions: dict[int, int] = field(default_factory=dict)

    @property
    def average_response_ms(self) -> float | None:
        """Average response time."""
        if not self.response_count:
            return None
        return self.response_ms_total / self.response_count


class ModbusTcpClient:
    """Read-only Modbus TCP client with automatic reconnect."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 5.0,
        retries: int = 2,
        request_delay: float = 0.02,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.request_delay = request_delay
        self.stats = ClientStats()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._transaction_id = 0
        self._last_request_end = 0.0
        self._had_connection = False

    @property
    def connected(self) -> bool:
        """Return True if a TCP connection is open."""
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the TCP connection if needed."""
        async with self._lock:
            await self._ensure_connected()

    async def close(self) -> None:
        """Close the TCP connection."""
        async with self._lock:
            await self._close()

    async def _ensure_connected(self) -> None:
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
        except (TimeoutError, OSError) as err:
            self._reader = self._writer = None
            raise ModbusConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err or type(err).__name__}"
            ) from err
        self.stats.connects += 1
        if self._had_connection:
            self.stats.reconnects += 1
        self._had_connection = True
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)

    async def _close(self) -> None:
        writer = self._writer
        self._reader = self._writer = None
        if writer is None:
            return
        writer.close()
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(writer.wait_closed(), 1)

    def _next_transaction_id(self) -> int:
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return self._transaction_id

    async def read_registers(
        self,
        unit: int,
        function_code: int,
        address: int,
        count: int,
        *,
        retries: int | None = None,
    ) -> list[int]:
        """Read ``count`` registers and return them as unsigned 16 bit words.

        Timeouts and connection errors are retried ``retries`` times.
        Modbus exception responses are not retried.
        """
        if function_code not in ALLOWED_FUNCTION_CODES:
            raise ValueError(f"Function code {function_code} is not allowed")
        if not 1 <= count <= MAX_REGISTERS_PER_REQUEST:
            raise ValueError(f"Invalid register count {count}")
        if not 0 <= address <= 0xFFFF or address + count > 0x10000:
            raise ValueError(f"Invalid address {address}")
        if not 0 <= unit <= 255:
            raise ValueError(f"Invalid unit id {unit}")

        async with self._lock:
            last_err: ModbusError | None = None
            attempts = (self.retries if retries is None else retries) + 1
            for attempt in range(attempts):
                try:
                    return await self._request(unit, function_code, address, count)
                except ModbusExceptionResponse as err:
                    self._record_error(err)
                    self.stats.exceptions[err.code] = self.stats.exceptions.get(err.code, 0) + 1
                    raise
                except (ModbusTimeoutError, ModbusConnectionError, ModbusProtocolError) as err:
                    self._record_error(err)
                    if isinstance(err, ModbusTimeoutError):
                        self.stats.timeouts += 1
                    last_err = err
                    # A late answer would corrupt the next transaction: start over.
                    await self._close()
                    _LOGGER.debug(
                        "Attempt %s/%s for unit %s FC%02d 0x%04X+%s failed: %s",
                        attempt + 1,
                        attempts,
                        unit,
                        function_code,
                        address,
                        count,
                        err,
                    )
            assert last_err is not None
            raise last_err

    async def write_single_register(self, unit: int, address: int, value: int) -> None:
        """Write one holding register (FC06) and check the echoed answer.

        Callers must only pass whitelisted registers and values.
        """
        if not 1 <= unit <= 247:
            raise ValueError(f"Invalid unit id {unit} (broadcast writes are not allowed)")
        if not 0 <= address <= 0xFFFF or not 0 <= value <= 0xFFFF:
            raise ValueError("Invalid address or value")
        async with self._lock:
            last_err: ModbusError | None = None
            for _ in range(self.retries + 1):
                try:
                    await self._ensure_connected()
                    pdu = await self._transaction(
                        unit, struct.pack(">BHH", FC_WRITE_SINGLE, address, value), 5
                    )
                except ModbusExceptionResponse as err:
                    self._record_error(err)
                    raise
                except (ModbusTimeoutError, ModbusConnectionError, ModbusProtocolError) as err:
                    self._record_error(err)
                    last_err = err
                    await self._close()
                    continue
                if pdu != struct.pack(">BHH", FC_WRITE_SINGLE, address, value):
                    raise ModbusProtocolError(f"Unexpected write echo {pdu.hex()}")
                return
            assert last_err is not None
            raise last_err

    def _record_error(self, err: ModbusError) -> None:
        self.stats.errors += 1
        self.stats.last_error = str(err)

    async def _request(self, unit: int, function_code: int, address: int, count: int) -> list[int]:
        await self._ensure_connected()
        pdu = await self._transaction(
            unit, struct.pack(">BHH", function_code, address, count), 2 + count * 2
        )
        if pdu[1] != count * 2:
            raise ModbusProtocolError(f"Unexpected byte count {pdu[1]}, expected {count * 2}")
        return list(struct.unpack(f">{count}H", pdu[2:]))

    async def _transaction(self, unit: int, request: bytes, answer_length: int) -> bytes:
        """Send a request PDU and return the answer PDU (function code included)."""
        assert self._reader is not None and self._writer is not None
        function_code = request[0]

        # Give slow RS485 gateways a short pause between two frames
        wait = self._last_request_end + self.request_delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

        tid = self._next_transaction_id()
        frame = struct.pack(">HHHB", tid, 0, len(request) + 1, unit) + request
        self.stats.requests += 1
        started = time.monotonic()
        try:
            self._writer.write(frame)
            await self._writer.drain()
            pdu = await asyncio.wait_for(
                self._read_response(tid, unit, function_code, answer_length), self.timeout
            )
        except TimeoutError as err:
            raise ModbusTimeoutError(
                f"No answer from unit {unit} for FC{function_code:02d} "
                f"{request[1:].hex()} within {self.timeout:g} s"
            ) from err
        except (OSError, asyncio.IncompleteReadError) as err:
            raise ModbusConnectionError(f"Connection lost: {err}") from err
        finally:
            self._last_request_end = time.monotonic()
        elapsed = (self._last_request_end - started) * 1000
        self.stats.last_response_ms = elapsed
        self.stats.response_ms_total += elapsed
        self.stats.response_count += 1
        return pdu

    async def _read_response(
        self, tid: int, unit: int, function_code: int, answer_length: int
    ) -> bytes:
        assert self._reader is not None
        while True:
            header = await self._reader.readexactly(7)
            r_tid, protocol, length, r_unit = struct.unpack(">HHHB", header)
            if protocol != 0 or not 2 <= length <= 254:
                raise ModbusProtocolError(f"Invalid MBAP header {header.hex()}")
            pdu = await self._reader.readexactly(length - 1)
            if r_tid != tid:
                # Stale answer of an earlier transaction: ignore it
                _LOGGER.debug("Discarding frame with transaction id %s", r_tid)
                continue
            if r_unit != unit:
                raise ModbusProtocolError(f"Answer from unit {r_unit}, expected {unit}")
            r_fc = pdu[0]
            if r_fc == function_code | 0x80:
                raise ModbusExceptionResponse(unit, function_code, pdu[1] if len(pdu) > 1 else 0)
            if r_fc != function_code:
                raise ModbusProtocolError(f"Unexpected function code {r_fc}")
            if len(pdu) != answer_length:
                raise ModbusProtocolError(
                    f"Unexpected answer length {len(pdu)}, expected {answer_length}"
                )
            return pdu
