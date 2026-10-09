"""The BGETech Modbus integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import MANUFACTURER_GATEWAY
from .coordinator import BGETechConfigEntry, GatewayCoordinator, gateway_device_identifier

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SELECT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: BGETechConfigEntry) -> bool:
    """Set up a gateway from a config entry."""
    coordinator = GatewayCoordinator(hass, entry)
    # The gateway device must exist before meter devices can reference it
    gateway_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={gateway_device_identifier(entry)},
        name=coordinator.gateway_name,
        manufacturer=MANUFACTURER_GATEWAY,
        model="Modbus TCP gateway",
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
    coordinator.gateway_device_id = gateway_device.id
    # A gateway that is not reachable at startup is not an error: the
    # entities become available as soon as the gateway answers.
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BGETechConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: BGETechConfigEntry) -> None:
    """Reload after options or meters (subentries) changed."""
    await hass.config_entries.async_reload(entry.entry_id)
