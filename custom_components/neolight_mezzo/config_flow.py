"""Config flow for NeoLight MEZZO mobile-cloud access."""

from __future__ import annotations

import logging

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
from .const import CONF_COUNTRY_CODE, CONF_LOGIN_METHOD, CONF_PASSWORD, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class NeoLightConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup through the Tuya mobile API."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Validate account credentials against the EU mobile API."""
        errors: dict[str, str] = {}
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
                if user_input[CONF_LOGIN_METHOD] == "phone":
                    await client.login_phone()
                else:
                    await client.login_email()
                homes_raw = await client.get_homes()
                homes = []
                devices = []
                for home in homes_raw:
                    if not isinstance(home, dict):
                        continue
                    home_id = home.get("groupId") or home.get("gid") or home.get("homeId")
                    homes.append({
                        "id": str(home_id) if home_id is not None else "",
                        "name": str(home.get("name") or home.get("groupName") or "NeoLight home"),
                    })
                    if home_id is not None:
                        try:
                            home_devices = await client.get_devices(str(home_id))
                        except NeoLightApiError:
                            _LOGGER.warning("Could not enumerate devices for a discovered home.")
                            continue
                        for device in home_devices:
                            if not isinstance(device, dict):
                                continue
                            # Keep only discovery metadata; never persist local keys or cloud tokens.
                            devices.append({
                                "id": str(device.get("devId") or device.get("id") or ""),
                                "name": str(device.get("name") or "NeoLight device"),
                                "online": bool(device.get("isOnline", False)),
                                "product_id": str(device.get("productId") or ""),
                                "category": str(device.get("category") or ""),
                                "home_id": str(home_id),
                            })
                login_method = user_input[CONF_LOGIN_METHOD]
                await self.async_set_unique_id(f"{login_method}:{username.casefold()}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"NeoLight ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_LOGIN_METHOD: login_method,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_COUNTRY_CODE: user_input[CONF_COUNTRY_CODE],
                        "homes": homes,
                        "devices": devices,
                    },
                )
            except NeoLightProfileError:
                errors["base"] = "profile_missing"
            except NeoLightMFAError:
                errors["base"] = "mfa_required"
            except NeoLightAuthError:
                errors["base"] = "invalid_auth"
            except NeoLightApiError as err:
                # API errors contain only a sanitized error code/message; never
                # log request URLs, signatures, account credentials, or payloads.
                _LOGGER.warning("NeoLight cloud setup failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                # Avoid logging exception details that may contain signed request URLs.
                _LOGGER.error("Unexpected NeoLight setup error (%s).", type(err).__name__)
                errors["base"] = "unknown"

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
