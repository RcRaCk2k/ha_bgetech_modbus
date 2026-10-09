"""Integration tests with the simulated gateway."""

from __future__ import annotations

import asyncio

from homeassistant.components.sensor import ATTR_STATE_CLASS, SensorStateClass
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bgetech_modbus.const import (
    CONF_SCAN_INTERVAL_ENERGY,
    DOMAIN,
)
from custom_components.bgetech_modbus.coordinator import GatewayCoordinator
from custom_components.bgetech_modbus.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import DEFAULT_METERS, gateway_entry, meter_subentry
from .fake_modbus import FakeGateway, make_drt428m


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> GatewayCoordinator:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry.runtime_data


async def poll(coordinator: GatewayCoordinator) -> None:
    """Run a polling cycle as if the polling interval had elapsed."""
    for meter in coordinator.meters.values():
        meter.block_last_read.clear()
    await coordinator.async_refresh()


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, slave: int, key: str) -> str:
    registry = er.async_get(hass)
    for platform in ("sensor", "binary_sensor", "select"):
        eid = registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{slave}_{key}")
        if eid:
            return eid
    raise AssertionError(f"No entity for slave {slave} {key}")


def state(hass: HomeAssistant, entry: MockConfigEntry, slave: int, key: str):
    return hass.states.get(entity_id(hass, entry, slave, key))


async def test_four_meters_one_gateway(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Four DRT428M-3 on one gateway: correct values, 2 requests per meter."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    coordinator = await setup_entry(hass, entry)

    voltage = state(hass, entry, 3, "voltage_l1")
    assert float(voltage.state) == 233.5
    assert voltage.attributes[ATTR_UNIT_OF_MEASUREMENT] == "V"

    power = state(hass, entry, 6, "active_power_total")
    assert power.attributes[ATTR_UNIT_OF_MEASUREMENT] == "W"
    assert float(power.state) == pytest.approx(151.0)

    assert float(state(hass, entry, 4, "frequency").state) == 50.0
    assert float(state(hass, entry, 5, "power_factor_total").state) == 0.78

    # First cycle: device info + 2 blocks per meter. Afterwards one request
    # per block and meter, no matter how many entities exist.
    assert coordinator.stats.requests == 4 * 3
    gateway.requests.clear()
    await poll(coordinator)
    assert len(gateway.requests) == 8
    assert {(r[2], r[3]) for r in gateway.requests} == {(0x000E, 46), (0x0100, 96)}

    # Devices: one per meter, linked to the gateway device
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_3"), entry.entry_id)
    assert device.name == "Hausanschluss"
    assert device.model == "DRT428M-3"
    assert device.manufacturer == "B+G E-Tech"
    assert device.sw_version == "1.02"
    gw_device = devices.async_get_device_by_identifier((DOMAIN, entry.entry_id), entry.entry_id)
    assert device.via_device_id == gw_device.id

    combined = hass.states.get(entity_id(hass, entry, 3, "combined_code"))
    assert combined.state == "forward_minus_reverse"


async def test_energy_dashboard_metadata(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Import/export are total_increasing kWh, the net total is 'total'."""
    entry = gateway_entry(gateway.port, [meter_subentry(6, "Zähler")])
    await setup_entry(hass, entry)

    for key in ("import_active_energy_sum", "export_active_energy_sum"):
        st = state(hass, entry, 6, key)
        assert st.attributes[ATTR_DEVICE_CLASS] == "energy"
        assert st.attributes[ATTR_UNIT_OF_MEASUREMENT] == "kWh"
        assert st.attributes[ATTR_STATE_CLASS] == SensorStateClass.TOTAL_INCREASING
    assert float(state(hass, entry, 6, "import_active_energy_sum").state) == 17776.2
    assert float(state(hass, entry, 6, "export_active_energy_sum").state) == 9.62

    total = state(hass, entry, 6, "total_active_energy_sum")
    assert total.attributes[ATTR_STATE_CLASS] == SensorStateClass.TOTAL
    assert float(total.state) == 17766.6

    # Rarely needed values exist but are disabled by default
    registry = er.async_get(hass)
    for key in ("t1_import_active_energy", "reactive_power_l1", "import_active_energy_l1"):
        reg_entry = registry.async_get(entity_id(hass, entry, 6, key))
        assert reg_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_unreachable_meter(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """A dead meter only affects its own entities and is retried with back-off."""
    gateway.meters[5].online = False
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    coordinator = await setup_entry(hass, entry)

    assert state(hass, entry, 5, "voltage_l1").state == STATE_UNAVAILABLE
    assert state(hass, entry, 5, "connected").state == STATE_OFF
    assert float(state(hass, entry, 3, "voltage_l1").state) == 233.5
    assert state(hass, entry, 3, "connected").state == STATE_ON
    meter5 = next(m for m in coordinator.meters.values() if m.slave_id == 5)
    assert meter5.failures == 1

    # Back-off: the dead meter is skipped in the next cycle
    gateway.requests.clear()
    await poll(coordinator)
    assert {r[0] for r in gateway.requests} == {3, 4, 6}
    assert coordinator.stats.meters_skipped == 1

    # Recovery
    gateway.meters[5].online = True
    meter5.next_attempt = 0
    await poll(coordinator)
    await hass.async_block_till_done()
    assert float(state(hass, entry, 5, "voltage_l1").state) == 233.5
    assert meter5.failures == 0


async def test_gateway_connection_loss(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """All entities become unavailable and recover after reconnect."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    coordinator = await setup_entry(hass, entry)
    port = gateway.port

    await gateway.stop()
    await poll(coordinator)
    await hass.async_block_till_done()
    assert not coordinator.last_update_success
    for slave in (3, 4, 5, 6):
        assert state(hass, entry, slave, "voltage_l1").state == STATE_UNAVAILABLE
    gw_conn = hass.states.get("binary_sensor.test_gateway_gateway_connection")
    assert gw_conn.state == STATE_OFF

    await gateway.start(port)
    await poll(coordinator)
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    for slave in (3, 4, 5, 6):
        assert float(state(hass, entry, slave, "voltage_l1").state) == 233.5
    # Meters were not put into back-off because of the gateway outage
    assert all(m.failures == 0 for m in coordinator.meters.values())


async def test_gateway_drops_connection(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """A dropped TCP connection is re-established transparently."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS, retries=1)
    coordinator = await setup_entry(hass, entry)
    await gateway.drop_connections()
    await poll(coordinator)
    assert coordinator.last_update_success
    assert coordinator.client.stats.reconnects >= 1
    assert all(m.online for m in coordinator.meters.values())


async def test_gateway_unreachable_at_startup(hass: HomeAssistant) -> None:
    """The entry loads even if the gateway is down; entities are unavailable."""
    gw = FakeGateway()
    await gw.start()
    port = gw.port
    await gw.stop()
    entry = gateway_entry(port, [meter_subentry(3, "Zähler")])
    await setup_entry(hass, entry)
    assert state(hass, entry, 3, "voltage_l1").state == STATE_UNAVAILABLE


async def test_no_overlapping_cycles(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Concurrent refresh requests never overlap on the bus."""
    gateway.delay = 0.01
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    coordinator = await setup_entry(hass, entry)
    await asyncio.gather(*(coordinator._async_refresh() for _ in range(3)))
    assert gateway.max_in_flight == 1


async def test_multiple_gateways(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Independent gateways with the same slave ids."""
    second = FakeGateway()
    second.meters[3] = make_drt428m("drt428m_3", 3)
    second.meters[3].set_float(0x000E, 229.9)
    await second.start()
    try:
        entry1 = gateway_entry(gateway.port, [meter_subentry(3, "A")])
        entry2 = gateway_entry(second.port, [meter_subentry(3, "B")])
        c1 = await setup_entry(hass, entry1)
        c2 = await setup_entry(hass, entry2)
        assert c1.client is not c2.client
        assert float(state(hass, entry1, 3, "voltage_l1").state) == 233.5
        assert float(state(hass, entry2, 3, "voltage_l1").state) == 229.9
    finally:
        await second.stop()


async def test_different_models_one_gateway(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """DRT428M-2 and DRT428M-3 side by side."""
    gateway.meters[7] = make_drt428m("drt428m_2", 7)
    entry = gateway_entry(
        gateway.port,
        [meter_subentry(3, "Drei"), meter_subentry(7, "Zwei", model="drt428m_2")],
    )
    coordinator = await setup_entry(hass, entry)
    assert coordinator.last_update_success
    reads = {(r[0], r[2], r[3]) for r in gateway.requests if r[2] != 0}
    assert (3, 0x0100, 96) in reads
    assert (7, 0x0100, 48) in reads
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_7_t1_total_active_energy")
        is None
    )
    assert float(state(hass, entry, 7, "import_active_energy_sum").state) == 17776.2


async def test_per_meter_energy_interval(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Energy counters can be polled less often than instantaneous values."""
    entry = gateway_entry(gateway.port, [meter_subentry(3, "A", **{CONF_SCAN_INTERVAL_ENERGY: 60})])
    coordinator = await setup_entry(hass, entry)
    assert coordinator.tick == 5
    # 6 s later: the instantaneous block is due, the energy block is not
    meter = next(iter(coordinator.meters.values()))
    for idx in meter.block_last_read:
        meter.block_last_read[idx] -= 6
    gateway.requests.clear()
    await coordinator.async_refresh()
    assert [(r[2], r[3]) for r in gateway.requests] == [(0x000E, 46)]
    # 61 s later both are due
    for idx in meter.block_last_read:
        meter.block_last_read[idx] -= 61
    gateway.requests.clear()
    await coordinator.async_refresh()
    assert [(r[2], r[3]) for r in gateway.requests] == [(0x000E, 46), (0x0100, 96)]
    # Values of the skipped block stay available
    assert float(state(hass, entry, 3, "import_active_energy_sum").state) == 17776.2


async def test_diagnostics(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Diagnostics contain no host name."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    await setup_entry(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["host"] == "**REDACTED**"
    assert "127.0.0.1" not in str(diag)
    assert diag["gateway"]["cycle"]["requests"] == 12
    assert len(diag["meters"]) == 4


async def test_unload(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Unloading closes the connection."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    coordinator = await setup_entry(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not coordinator.client.connected


async def test_change_combined_code(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """The combined code can be changed via the select entity and is read back."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    await setup_entry(hass, entry)
    select_id = entity_id(hass, entry, 4, "combined_code")
    assert hass.states.get(select_id).attributes["options"] == [
        "forward",
        "forward_plus_reverse",
        "forward_minus_reverse",
    ]

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": select_id, "option": "forward_plus_reverse"},
        blocking=True,
    )
    assert gateway.writes == [(4, 0x000B, 5)]
    assert gateway.meters[4].registers[0x000B] == 5
    assert gateway.meters[3].registers[0x000B] == 9
    assert hass.states.get(select_id).state == "forward_plus_reverse"


async def test_change_combined_code_errors(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Invalid options are rejected locally, ignored writes are detected."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    coordinator = await setup_entry(hass, entry)
    select_id = entity_id(hass, entry, 5, "combined_code")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": select_id, "option": "7"}, blocking=True
        )
    meter = next(m for m in coordinator.meters.values() if m.slave_id == 5)
    with pytest.raises(HomeAssistantError):
        await coordinator.async_write_setting(meter, "modbus_id", "1")
    with pytest.raises(HomeAssistantError):
        await coordinator.async_write_setting(meter, "combined_code", "everything")
    assert gateway.writes == []

    gateway.meters[5].ignore_writes = True
    with pytest.raises(HomeAssistantError, match="did not apply"):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": select_id, "option": "forward"},
            blocking=True,
        )
    assert hass.states.get(select_id).state == "forward_minus_reverse"
