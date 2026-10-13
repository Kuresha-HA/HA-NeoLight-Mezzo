"""Config flow for NeoLight MEZZO mobile-cloud access."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    NeoLightApiError,
    NeoLightAuthError,
    NeoLightMobileApi,
    NeoLightProfileError,
    load_profile,
)
from .const import CONF_COUNTRY_CODE, CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class NeoLightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup through the Tuya mobile API."""

    VERSION = 1

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}

    async def async_step_user(self, user_input=None):
        """Validate account credentials against the EU mobile API."""
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            try:
                profile = load_profile()
                client = NeoLightMobileApi(
                    async_get_clientsession(self.hass),
                    username,
                    user_input[CONF_PASSWORD],
                    user_input[CONF_COUNTRY_CODE],
                    profile,
                )
                await client.login_email()
                homes = await client.get_homes()
                await self.async_set_unique_id(username.casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"NeoLight ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_COUNTRY_CODE: user_input[CONF_COUNTRY_CODE],
                        "homes": homes,
                    },
                )
            except NeoLightProfileError:
                self._errors["base"] = "profile_missing"
            except NeoLightAuthError:
                self._errors["base"] = "invalid_auth"
            except NeoLightApiError:
                _LOGGER.warning("NeoLight cloud setup failed; see form error for details.")
                self._errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during NeoLight cloud setup")
                self._errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_COUNTRY_CODE, default="380"): str,
                }
            ),
            errors=self._errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return NeoLightOptionsFlow(config_entry)


class NeoLightOptionsFlow(config_entries.OptionsFlow):
    """Placeholder for future device and refresh options."""

    def __init__(self, config_entry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """No options are exposed yet."""
        return self.async_abort(reason="not_supported")
