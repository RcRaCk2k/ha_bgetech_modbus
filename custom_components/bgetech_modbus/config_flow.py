"""Config flow, options flow and meter subentry flow."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
import voluptuous as vol

from .const import (
    CONF_ENABLED,
    CONF_MAX_REGISTERS,
    CONF_MODEL,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SCAN_INTERVAL_ENERGY,
    CONF_SCAN_INTERVAL_INSTANT,
    CONF_SLAVE_ID,
    CONF_TIMEOUT,
    DEFAULT_MAX_REGISTERS,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MAX_SLAVE_ID,
    MIN_SCAN_INTERVAL,
    MIN_SLAVE_ID,
    MODEL_AUTO_DRT428M,
    SUBENTRY_TYPE_METER,
)
from .modbus_client import ModbusConnectionError, ModbusError, ModbusTcpClient
from .register_map import DRT428M_2, DRT428M_3, MODELS, DeviceModel

_LOGGER = logging.getLogger(__name__)

CONF_VERIFY = "verify"


def _seconds_selector(minimum: float = MIN_SCAN_INTERVAL) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=MAX_SCAN_INTERVAL,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _settings_schema(defaults: dict[str, Any]) -> dict[vol.Marker, Any]:
    return {
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ): _seconds_selector(),
        vol.Required(
            CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.5,
                max=30,
                step=0.5,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Required(
            CONF_RETRIES, default=defaults.get(CONF_RETRIES, DEFAULT_RETRIES)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=5, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Required(
            CONF_MAX_REGISTERS,
            default=defaults.get(CONF_MAX_REGISTERS, DEFAULT_MAX_REGISTERS),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=125, step=1, mode=selector.NumberSelectorMode.BOX
            )
        ),
    }


def _normalize_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
        CONF_TIMEOUT: float(user_input[CONF_TIMEOUT]),
        CONF_RETRIES: int(user_input[CONF_RETRIES]),
        CONF_MAX_REGISTERS: int(user_input[CONF_MAX_REGISTERS]),
    }


async def _test_connection(host: str, port: int, timeout: float) -> None:
    client = ModbusTcpClient(host, port, timeout=timeout, retries=0)
    try:
        await client.connect()
    finally:
        await client.close()


class BGETechConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a gateway."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Gateway connection and polling settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()
            try:
                await _test_connection(host, port, float(user_input[CONF_TIMEOUT]))
            except ModbusConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: host,
                        CONF_PORT: port,
                    },
                    options=_normalize_settings(user_input),
                )

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=65535, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                **_settings_schema(defaults),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change name, host or port of a gateway."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{host}:{port}")
            if self.unique_id != entry.unique_id:
                self._abort_if_unique_id_configured()
            try:
                await _test_connection(
                    host, port, float(entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
                )
            except ModbusConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_and_abort(
                    entry,
                    unique_id=f"{host}:{port}",
                    title=user_input[CONF_NAME],
                    data_updates={
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: host,
                        CONF_PORT: port,
                    },
                )
        defaults = user_input or dict(entry.data)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, entry.title)): str,
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=65535, step=1, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BGETechOptionsFlow:
        """Return the options flow."""
        return BGETechOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Meters are managed as subentries of a gateway."""
        return {SUBENTRY_TYPE_METER: MeterSubentryFlow}


class BGETechOptionsFlow(OptionsFlow):
    """Polling and communication settings of a gateway."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=_normalize_settings(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_settings_schema(dict(self.config_entry.options))),
        )


def _model_selector(include_auto: bool) -> selector.SelectSelector:
    options = [MODEL_AUTO_DRT428M] if include_auto else []
    options += list(MODELS)
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="model",
        )
    )


def _optional_interval(key: str, current: Any) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": current} if current else None)


class MeterSubentryFlow(ConfigSubentryFlow):
    """Add or edit a meter (slave) of a gateway."""

    async def _probe(self, slave_id: int, model_id: str) -> str:
        """Check that the meter answers and resolve automatic model selection.

        Returns the model id. Raises ModbusError if the meter does not answer.
        """
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            raise ModbusConnectionError("Gateway is not loaded")
        client: ModbusTcpClient = entry.runtime_data.client
        if model_id == MODEL_AUTO_DRT428M:
            model: DeviceModel = DRT428M_3
        else:
            model = MODELS[model_id]
        first = min(model.registers, key=lambda r: r.address)
        await client.read_registers(
            slave_id, first.function_code, first.address, first.count, retries=1
        )
        if model_id != MODEL_AUTO_DRT428M:
            return model_id
        assert DRT428M_3.probe_address is not None
        try:
            await client.read_registers(slave_id, 3, DRT428M_3.probe_address, 2, retries=0)
        except ModbusConnectionError:
            raise
        except ModbusError:
            return DRT428M_2.model_id
        return DRT428M_3.model_id

    def _slave_in_use(self, slave_id: int) -> bool:
        return any(
            sub.subentry_type == SUBENTRY_TYPE_METER and int(sub.data[CONF_SLAVE_ID]) == slave_id
            for sub in self._get_entry().subentries.values()
        )

    @staticmethod
    def _intervals(user_input: dict[str, Any]) -> dict[str, int | None]:
        return {
            key: int(user_input[key]) if user_input.get(key) else None
            for key in (CONF_SCAN_INTERVAL_INSTANT, CONF_SCAN_INTERVAL_ENERGY)
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a meter."""
        errors: dict[str, str] = {}
        if user_input is not None:
            slave_id = int(user_input[CONF_SLAVE_ID])
            model_id = user_input[CONF_MODEL]
            if self._slave_in_use(slave_id):
                errors[CONF_SLAVE_ID] = "slave_id_in_use"
            elif user_input.get(CONF_VERIFY, True) or model_id == MODEL_AUTO_DRT428M:
                try:
                    model_id = await self._probe(slave_id, model_id)
                except ModbusConnectionError:
                    errors["base"] = "cannot_connect"
                except ModbusError as err:
                    _LOGGER.debug("Probe of slave %s failed: %s", slave_id, err)
                    errors["base"] = "meter_not_responding"
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_SLAVE_ID: slave_id,
                        CONF_MODEL: model_id,
                        CONF_ENABLED: user_input.get(CONF_ENABLED, True),
                        **self._intervals(user_input),
                    },
                    unique_id=str(slave_id),
                )

        defaults = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SLAVE_ID, default=defaults.get(CONF_SLAVE_ID, MIN_SLAVE_ID)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SLAVE_ID,
                        max=MAX_SLAVE_ID,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
                vol.Required(
                    CONF_MODEL, default=defaults.get(CONF_MODEL, MODEL_AUTO_DRT428M)
                ): _model_selector(include_auto=True),
                vol.Required(CONF_ENABLED, default=defaults.get(CONF_ENABLED, True)): bool,
                vol.Required(CONF_VERIFY, default=defaults.get(CONF_VERIFY, True)): bool,
                _optional_interval(
                    CONF_SCAN_INTERVAL_INSTANT, defaults.get(CONF_SCAN_INTERVAL_INSTANT)
                ): _seconds_selector(),
                _optional_interval(
                    CONF_SCAN_INTERVAL_ENERGY, defaults.get(CONF_SCAN_INTERVAL_ENERGY)
                ): _seconds_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit name, model, state and polling intervals of a meter.

        The slave id is the identity of the meter and cannot be changed;
        remove the meter and add it again instead.
        """
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data={
                    CONF_SLAVE_ID: subentry.data[CONF_SLAVE_ID],
                    CONF_MODEL: user_input[CONF_MODEL],
                    CONF_ENABLED: user_input[CONF_ENABLED],
                    **self._intervals(user_input),
                },
            )
        data = subentry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=subentry.title): str,
                vol.Required(CONF_MODEL, default=data[CONF_MODEL]): _model_selector(
                    include_auto=False
                ),
                vol.Required(CONF_ENABLED, default=data.get(CONF_ENABLED, True)): bool,
                _optional_interval(
                    CONF_SCAN_INTERVAL_INSTANT, data.get(CONF_SCAN_INTERVAL_INSTANT)
                ): _seconds_selector(),
                _optional_interval(
                    CONF_SCAN_INTERVAL_ENERGY, data.get(CONF_SCAN_INTERVAL_ENERGY)
                ): _seconds_selector(),
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            description_placeholders={"slave_id": str(data[CONF_SLAVE_ID])},
        )
