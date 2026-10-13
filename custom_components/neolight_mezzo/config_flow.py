"""Config flow for NeoLight MEZZO mobile-cloud access."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    NeoLightApiError,
    NeoLightAuthError,
    NeoLightMFAError,
    NeoLightMobileApi,
    NeoLightProfileError,
    load_profile,
)
from .cloud_data import normalize_snapshot
from .const import (
    CONF_COUNTRY_CODE,
    CONF_LOGIN_METHOD,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class NeoLightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup through the NeoLight mobile API."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Validate account credentials and discover the account's devices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            values = {
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
                CONF_COUNTRY_CODE: user_input[CONF_COUNTRY_CODE].strip(),
                CONF_LOGIN_METHOD: user_input[CONF_LOGIN_METHOD],
            }
            return await self._async_attempt_login(values)

        return self._show_user_form(errors)

    async def async_step_mfa(self, user_input: dict[str, Any] | None = None):
        """Complete the cloud's additional email verification step."""
        credentials = self.context.get("neolight_credentials")
        if not isinstance(credentials, dict):
            return self.async_abort(reason="reauth_failed")

        errors: dict[str, str] = {}
        if user_input is not None:
            code = user_input["mfa_code"].strip()
            if not code:
                errors["base"] = "mfa_invalid"
            else:
                return await self._async_attempt_login(credentials, mfa_code=code)

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({vol.Required("mfa_code"): str}),
            errors=errors,
            description_placeholders={"account": str(credentials[CONF_USERNAME])},
        )

    async def _async_attempt_login(
        self, values: dict[str, str], mfa_code: str = ""
    ):
        """Log in, discover devices, and create the entry only after success."""
        errors: dict[str, str] = {}
        try:
            client = NeoLightMobileApi(
                async_get_clientsession(self.hass),
                values[CONF_USERNAME],
                values[CONF_PASSWORD],
                values[CONF_COUNTRY_CODE],
                load_profile(),
            )
            if values[CONF_LOGIN_METHOD] == "phone":
                await client.login_phone(mfa_code=mfa_code)
            else:
                await client.login_email(mfa_code=mfa_code)

            homes_raw = await client.get_homes()
            devices_by_home: dict[str, list[Any]] = {}
            for home in homes_raw:
                if not isinstance(home, dict):
                    continue
                home_id = home.get("groupId") or home.get("gid") or home.get("homeId")
                if home_id is not None:
                    try:
                        devices_by_home[str(home_id)] = await client.get_devices(str(home_id))
                    except NeoLightApiError:
                        _LOGGER.warning("Could not enumerate devices for a discovered home.")
                        devices_by_home[str(home_id)] = []

            snapshot = normalize_snapshot(homes_raw, devices_by_home)
            login_method = values[CONF_LOGIN_METHOD]
            username = values[CONF_USERNAME]
            await self.async_set_unique_id(f"{login_method}:{username.casefold()}")
            self._abort_if_unique_id_configured()
            self.context.pop("neolight_credentials", None)
            return self.async_create_entry(
                title=f"NeoLight ({username})",
                data={
                    CONF_USERNAME: username,
                    CONF_LOGIN_METHOD: login_method,
                    CONF_PASSWORD: values[CONF_PASSWORD],
                    CONF_COUNTRY_CODE: values[CONF_COUNTRY_CODE],
                    **snapshot,
                },
            )
        except NeoLightMFAError:
            # Keep credentials only in the transient flow context, never in flow
            # options, logs, or a persistent config entry before authentication.
            self.context["neolight_credentials"] = dict(values)
            if mfa_code:
                errors["base"] = "mfa_invalid"
            else:
                return await self.async_step_mfa()
        except NeoLightProfileError:
            errors["base"] = "profile_missing"
        except NeoLightAuthError:
            errors["base"] = "invalid_auth"
        except NeoLightApiError as err:
            _LOGGER.warning("NeoLight cloud setup failed: %s", err)
            errors["base"] = "cannot_connect"
        except Exception as err:
            _LOGGER.error("Unexpected NeoLight setup error (%s).", type(err).__name__)
            errors["base"] = "unknown"

        if mfa_code:
            return self.async_show_form(
                step_id="mfa",
                data_schema=vol.Schema({vol.Required("mfa_code"): str}),
                errors=errors,
                description_placeholders={
                    "account": str(values[CONF_USERNAME])
                },
            )
        return self._show_user_form(errors)

    def _show_user_form(self, errors: dict[str, str]):
        """Render the account credentials form."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN_METHOD, default="email"): vol.In(["email", "phone"]),
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_COUNTRY_CODE, default="380"): str,
                }
            ),
            errors=errors,
        )
