"""Fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bgetech_modbus.const import (
    CONF_ENABLED,
    CONF_MAX_REGISTERS,
    CONF_MODEL,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE_ID,
    CONF_TIMEOUT,
    DOMAIN,
    SUBENTRY_TYPE_METER,
)

from .fake_modbus import FakeGateway, make_drt428m


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations."""


@pytest.fixture(autouse=True)
def allow_local_sockets(socket_enabled: None) -> None:
    """The simulated gateway listens on 127.0.0.1."""


@pytest.fixture
async def gateway() -> AsyncGenerator[FakeGateway]:
    """A running fake gateway with four DRT428M-3 (slaves 3-6)."""
    gw = FakeGateway()
    for slave in (3, 4, 5, 6):
        gw.meters[slave] = make_drt428m("drt428m_3", slave)
    await gw.start()
    yield gw
    await gw.stop()


def meter_subentry(
    slave_id: int, name: str, model: str = "drt428m_3", **extra
) -> ConfigSubentryData:
    """Subentry data of a meter."""
    return ConfigSubentryData(
        data={CONF_SLAVE_ID: slave_id, CONF_MODEL: model, CONF_ENABLED: True, **extra},
        subentry_type=SUBENTRY_TYPE_METER,
        title=name,
        unique_id=str(slave_id),
    )


def gateway_entry(port: int, subentries: list[ConfigSubentryData], **options) -> MockConfigEntry:
    """Config entry of a gateway."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Gateway",
        unique_id=f"127.0.0.1:{port}",
        data={CONF_NAME: "Test Gateway", CONF_HOST: "127.0.0.1", CONF_PORT: port},
        options={
            CONF_SCAN_INTERVAL: 5,
            CONF_TIMEOUT: 0.3,
            CONF_RETRIES: 0,
            CONF_MAX_REGISTERS: 0,
            **options,
        },
        subentries_data=subentries,
    )


DEFAULT_METERS = [
    meter_subentry(3, "Hausanschluss"),
    meter_subentry(4, "Wärmepumpe"),
    meter_subentry(5, "Ladesäule 1"),
    meter_subentry(6, "Ladesäule 2"),
]
