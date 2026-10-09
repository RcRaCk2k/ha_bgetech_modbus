"""Modbus TCP client against the simulated gateway."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.bgetech_modbus.modbus_client import (
    ModbusConnectionError,
    ModbusExceptionResponse,
    ModbusTcpClient,
    ModbusTimeoutError,
)

from .fake_modbus import FakeGateway


async def test_read_and_reconnect(gateway: FakeGateway) -> None:
    """Read registers, survive a dropped connection."""
    client = ModbusTcpClient("127.0.0.1", gateway.port, timeout=0.3, retries=1)
    words = await client.read_registers(3, 3, 0x000E, 2)
    assert words == [0x4369, 0x8000]
    await gateway.drop_connections()
    words = await client.read_registers(4, 3, 0x0014, 2)
    assert words == [0x4248, 0x0000]
    assert client.stats.reconnects >= 1
    await client.close()


async def test_undefined_address_times_out(gateway: FakeGateway) -> None:
    """The meters do not answer undefined addresses."""
    client = ModbusTcpClient("127.0.0.1", gateway.port, timeout=0.2, retries=1)
    with pytest.raises(ModbusTimeoutError):
        await client.read_registers(3, 3, 0x004A, 2)
    assert client.stats.timeouts == 2
    # The client recovers for the next request
    assert len(await client.read_registers(3, 3, 0x000E, 46)) == 46
    await client.close()


async def test_exception_response_raised(
    gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Modbus exception from the device is reported as such."""
    monkeypatch.setattr(gateway, "_answer", lambda unit, fc, pdu: bytes([fc | 0x80, 2]))
    client = ModbusTcpClient("127.0.0.1", gateway.port, timeout=0.2, retries=3)
    with pytest.raises(ModbusExceptionResponse) as err:
        await client.read_registers(3, 3, 0x000E, 2)
    assert err.value.code == 2
    assert client.stats.requests == 1
    await client.close()


async def test_gateway_unreachable() -> None:
    """Connection errors."""
    gw = FakeGateway()
    await gw.start()
    port = gw.port
    await gw.stop()
    client = ModbusTcpClient("127.0.0.1", port, timeout=0.2, retries=0)
    with pytest.raises(ModbusConnectionError):
        await client.read_registers(3, 3, 0, 2)


async def test_function_codes_restricted(gateway: FakeGateway) -> None:
    """Reads only with FC03/FC04, writes only single registers (FC06), no broadcast."""
    client = ModbusTcpClient("127.0.0.1", gateway.port, timeout=0.3, retries=0)
    public = [name for name in dir(client) if not name.startswith("_")]
    assert [name for name in public if "write" in name.lower()] == ["write_single_register"]
    for fc in (1, 2, 5, 6, 15, 16):
        with pytest.raises(ValueError):
            await client.read_registers(1, fc, 0, 1)
    with pytest.raises(ValueError):
        await client.read_registers(1, 3, 0, 126)
    with pytest.raises(ValueError):
        await client.write_single_register(0, 0x000B, 5)
    assert gateway.writes == []
    await client.close()


async def test_write_single_register(gateway: FakeGateway) -> None:
    """FC06 with echo check and exception handling."""
    client = ModbusTcpClient("127.0.0.1", gateway.port, timeout=0.3, retries=0)
    await client.write_single_register(3, 0x000B, 5)
    assert gateway.meters[3].registers[0x000B] == 5
    assert await client.read_registers(3, 3, 0x000B, 1) == [5]
    with pytest.raises(ModbusExceptionResponse) as err:
        await client.write_single_register(3, 0x000B, 7)
    assert err.value.code == 3
    with pytest.raises(ModbusExceptionResponse):
        await client.write_single_register(3, 0x0100, 0)
    assert gateway.meters[3].registers[0x000B] == 5
    await client.close()


async def test_requests_are_serialised(gateway: FakeGateway) -> None:
    """Concurrent callers never have two requests on the bus at the same time."""
    gateway.delay = 0.02
    client = ModbusTcpClient("127.0.0.1", gateway.port, timeout=1, retries=0)
    await asyncio.gather(
        *(client.read_registers(slave, 3, 0x000E, 46) for slave in (3, 4, 5, 6) for _ in range(3))
    )
    assert gateway.max_in_flight == 1
    assert len(gateway.requests) == 12
    await client.close()
