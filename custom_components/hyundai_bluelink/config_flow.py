from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .client import (
    BluelinkAuthenticationError,
    BluelinkConnectionError,
    async_close_client,
    async_create_client,
    async_login_client,
)
from .const import CONF_PIN, CONF_REGION, DEFAULT_REGION, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HyundaiBluelinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Hyundai Bluelink."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle user-initiated setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _clean_user_input(user_input)
            try:
                info = await _async_validate_input(self.hass, data)
            except BluelinkAuthenticationError:
                errors["base"] = "invalid_auth"
            except BluelinkConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Hyundai Bluelink login")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["account_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=_data_schema(user_input),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Handle reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm and process reauthentication."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = dict(reauth_entry.data)
            data.update(_clean_user_input(user_input))
            try:
                info = await _async_validate_input(self.hass, data)
            except BluelinkAuthenticationError:
                errors["base"] = "invalid_auth"
            except BluelinkConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error reauthenticating Hyundai Bluelink")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["account_id"])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates=data,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_data_schema(reauth_entry.data),
            errors=errors,
        )


async def _async_validate_input(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> dict[str, str]:
    """Validate credentials with the upstream client."""
    client = await async_create_client(hass, data)
    try:
        await async_login_client(client, data)
        vehicles = await client.async_get_vehicles()
        account_id = str(getattr(client, "account_id", None) or data[CONF_USERNAME])
    finally:
        await async_close_client(client)

    return {
        "account_id": account_id,
        "title": f"Hyundai Bluelink ({len(vehicles)} vehicles)",
    }


def _data_schema(defaults: dict[str, Any] | None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_USERNAME,
                default=defaults.get(CONF_USERNAME, ""),
            ): selector.TextSelector(),
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_PIN,
                default=defaults.get(CONF_PIN, ""),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(
                CONF_REGION,
                default=defaults.get(CONF_REGION, DEFAULT_REGION),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[DEFAULT_REGION])
            ),
        }
    )


def _clean_user_input(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    if CONF_PIN in data and not data[CONF_PIN]:
        data.pop(CONF_PIN)
    return data
