"""Select platform: configuration registers of the meters."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BGETechConfigEntry, GatewayCoordinator, MeterState
from .entity import MeterEntity
from .register_map import WritableSetting

# Writes are serialised by the Modbus client anyway
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BGETechConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up selects for writable meter settings."""
    coordinator = entry.runtime_data
    for meter in coordinator.meters.values():
        async_add_entities(
            [
                MeterSettingSelect(coordinator, meter, setting)
                for setting in meter.model.writable_settings
            ],
            config_subentry_id=meter.subentry_id,
        )


class MeterSettingSelect(MeterEntity, SelectEntity):
    """A whitelisted configuration register (e.g. the DRT428M combined code)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: GatewayCoordinator, meter: MeterState, setting: WritableSetting
    ) -> None:
        super().__init__(coordinator, meter, setting.key)
        self.setting = setting
        self._attr_translation_key = setting.key
        self._attr_options = list(setting.options)

    @property
    def available(self) -> bool:
        """Available while the meter is online and its settings are known."""
        return super().available and self.meter.online and self.meter.info is not None

    @property
    def current_option(self) -> str | None:
        """Return the option matching the value read from the meter."""
        raw = (self.meter.info or {}).get(self.setting.info_key)
        for option, value in self.setting.options.items():
            if value == raw:
                return option
        return None

    async def async_select_option(self, option: str) -> None:
        """Write the new value to the meter."""
        await self.coordinator.async_write_setting(self.meter, self.setting.key, option)
