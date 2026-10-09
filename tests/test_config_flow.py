"""Config flow, options flow and meter subentries."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.bgetech_modbus.const import (
    CONF_ENABLED,
    CONF_MAX_REGISTERS,
    CONF_MODEL,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL_ENERGY,
    CONF_SCAN_INTERVAL_INSTANT,
    CONF_SLAVE_ID,
    CONF_TIMEOUT,
    DOMAIN,
    SUBENTRY_TYPE_METER,
)

from .conftest import DEFAULT_METERS, gateway_entry, meter_subentry
from .fake_modbus import FakeGateway, make_drt428m
from .test_init import setup_entry

GATEWAY_INPUT = {
    CONF_NAME: "BGETech Gateway",
    CONF_HOST: "127.0.0.1",
    CONF_SCAN_INTERVAL: 5,
    CONF_TIMEOUT: 1,
    CONF_RETRIES: 2,
    CONF_MAX_REGISTERS: 0,
}


async def test_user_flow(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Create a gateway entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**GATEWAY_INPUT, CONF_PORT: gateway.port}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "BGETech Gateway"
    assert result["data"] == {
        CONF_NAME: "BGETech Gateway",
        CONF_HOST: "127.0.0.1",
        CONF_PORT: gateway.port,
    }
    assert result["options"] == {
        CONF_SCAN_INTERVAL: 5,
        CONF_TIMEOUT: 1.0,
        CONF_RETRIES: 2,
        CONF_MAX_REGISTERS: 0,
    }
    await hass.async_block_till_done()

    # Same host/port a second time is rejected
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**GATEWAY_INPUT, CONF_PORT: gateway.port}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Unreachable gateway."""
    gw = FakeGateway()
    await gw.start()
    port = gw.port
    await gw.stop()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**GATEWAY_INPUT, CONF_PORT: port, CONF_TIMEOUT: 0.5}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_change_interval(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """The polling interval can be changed without re-adding the gateway."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    coordinator = await setup_entry(hass, entry)
    assert coordinator.tick == 5

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 10, CONF_TIMEOUT: 0.5, CONF_RETRIES: 0, CONF_MAX_REGISTERS: 40},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert coordinator.tick == 10
    assert coordinator.update_interval.total_seconds() <= 10
    assert all(b.count <= 40 for m in coordinator.meters.values() for b in m.blocks)


async def test_reconfigure_gateway(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Host/port can be changed, entities keep their ids."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    await setup_entry(hass, entry)
    registry = er.async_get(hass)
    before = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    second = FakeGateway()
    second.meters = gateway.meters
    await second.start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_NAME: "Neu", CONF_HOST: "127.0.0.1", CONF_PORT: second.port},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
        assert entry.data[CONF_PORT] == second.port
        after = {
            e.unique_id: e.entity_id
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert before == after
        assert entry.runtime_data.client.port == second.port
    finally:
        await entry.runtime_data.async_shutdown()
        await second.stop()


async def _add_meter(hass: HomeAssistant, entry, user_input: dict):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_METER), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(result["flow_id"], user_input)


async def test_add_meters_with_detection(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Meters are added via subentries; DRT428M-2/-3 are detected."""
    gateway.meters[9] = make_drt428m("drt428m_2", 9)
    entry = gateway_entry(gateway.port, [meter_subentry(3, "Hausanschluss")])
    await setup_entry(hass, entry)

    result = await _add_meter(
        hass,
        entry,
        {
            CONF_SLAVE_ID: 4,
            CONF_NAME: "Wärmepumpe",
            CONF_MODEL: "auto_drt428m",
            CONF_ENABLED: True,
            "verify": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    result = await _add_meter(
        hass,
        entry,
        {
            CONF_SLAVE_ID: 9,
            CONF_NAME: "Alt",
            CONF_MODEL: "auto_drt428m",
            CONF_ENABLED: True,
            "verify": True,
            CONF_SCAN_INTERVAL_ENERGY: 60,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    models = {sub.data[CONF_SLAVE_ID]: sub.data[CONF_MODEL] for sub in entry.subentries.values()}
    assert models == {3: "drt428m_3", 4: "drt428m_3", 9: "drt428m_2"}
    sub9 = next(s for s in entry.subentries.values() if s.data[CONF_SLAVE_ID] == 9)
    assert sub9.data[CONF_SCAN_INTERVAL_ENERGY] == 60
    assert sub9.data[CONF_SCAN_INTERVAL_INSTANT] is None

    coordinator = entry.runtime_data
    assert {m.slave_id for m in coordinator.meters.values()} == {3, 4, 9}
    assert all(m.online for m in coordinator.meters.values())
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_9_voltage_l1")


async def test_add_meter_errors(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Duplicate slave ids and silent meters are rejected; check can be skipped."""
    entry = gateway_entry(gateway.port, [meter_subentry(3, "Hausanschluss")])
    await setup_entry(hass, entry)

    result = await _add_meter(
        hass,
        entry,
        {
            CONF_SLAVE_ID: 3,
            CONF_NAME: "Doppelt",
            CONF_MODEL: "drt428m_3",
            CONF_ENABLED: True,
            "verify": False,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SLAVE_ID: "slave_id_in_use"}

    result = await _add_meter(
        hass,
        entry,
        {
            CONF_SLAVE_ID: 42,
            CONF_NAME: "Fehlt",
            CONF_MODEL: "drt428m_3",
            CONF_ENABLED: True,
            "verify": True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "meter_not_responding"}

    gateway.requests.clear()
    result = await _add_meter(
        hass,
        entry,
        {
            CONF_SLAVE_ID: 42,
            CONF_NAME: "Später",
            CONF_MODEL: "drt428m_3",
            CONF_ENABLED: False,
            "verify": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    meter = next(m for m in entry.runtime_data.meters.values() if m.slave_id == 42)
    assert not meter.enabled
    assert gateway.requests
    assert not any(r[0] == 42 for r in gateway.requests)


async def test_rename_meter_keeps_ids(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Renaming a meter does not create new devices or entities."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    await setup_entry(hass, entry)
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    before = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    device_ids = {d.id for d in dr.async_entries_for_config_entry(devices, entry.entry_id)}

    sub = next(s for s in entry.subentries.values() if s.data[CONF_SLAVE_ID] == 4)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_METER),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Heizung",
            CONF_MODEL: "drt428m_3",
            CONF_ENABLED: True,
            CONF_SCAN_INTERVAL_INSTANT: 2,
        },
    )
    assert result["type"] is FlowResultType.ABORT
    await hass.async_block_till_done()

    after = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert before == after
    assert device_ids == {d.id for d in dr.async_entries_for_config_entry(devices, entry.entry_id)}
    device = devices.async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_4"), entry.entry_id)
    assert device.name == "Heizung"
    assert entry.runtime_data.tick == 2


async def test_remove_meter(hass: HomeAssistant, gateway: FakeGateway) -> None:
    """Removing a meter removes its device and entities and stops polling it."""
    entry = gateway_entry(gateway.port, DEFAULT_METERS)
    await setup_entry(hass, entry)
    sub = next(s for s in entry.subentries.values() if s.data[CONF_SLAVE_ID] == 5)
    assert hass.config_entries.async_remove_subentry(entry, sub.subentry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_5_voltage_l1") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_6_voltage_l1")
    devices = dr.async_get(hass)
    assert (
        devices.async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_5"), entry.entry_id)
        is None
    )
    assert {m.slave_id for m in entry.runtime_data.meters.values()} == {3, 4, 6}
