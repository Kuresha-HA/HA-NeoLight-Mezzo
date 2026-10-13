"""NeoLight MEZZO Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    NeoLightApiError,
    NeoLightAuthError,
    NeoLightMobileApi,
    load_profile,
)
from .const import (
    CONF_COUNTRY_CODE,
    CONF_LOGIN_METHOD,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]
UPDATE_INTERVAL = timedelta(minutes=5)


def _normalize_snapshot(
    homes_raw: list[Any], devices_by_home: dict[str, list[Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Normalize cloud records while retaining only non-sensitive metadata."""
    homes: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    for home in homes_raw:
        if not isinstance(home, dict):
            continue
        home_id = home.get("groupId") or home.get("gid") or home.get("homeId")
        if home_id is None:
            continue
        home_id = str(home_id)
        homes.append({
            "id": home_id,
            "name": str(home.get("name") or home.get("groupName") or "NeoLight home"),
        })
        for device in devices_by_home.get(home_id, []):
            if not isinstance(device, dict):
                continue
            device_id = device.get("devId") or device.get("id")
            if device_id is None or not str(device_id):
                continue
            devices.append({
                "id": str(device_id),
                "name": str(device.get("name") or "NeoLight device"),
                "online": bool(device.get("isOnline", False)),
                "product_id": str(device.get("productId") or ""),
                "category": str(device.get("category") or ""),
                "home_id": home_id,
            })
    return {"homes": homes, "devices": devices}


class NeoLightCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll current home/device metadata from the NeoLight cloud."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.entry = entry
        self.client: NeoLightMobileApi | None = None

    def _new_client(self) -> NeoLightMobileApi:
        """Build a client from this config entry and the local app profile."""
        data = self.entry.data
        return NeoLightMobileApi(
            async_get_clientsession(self.hass),
            str(data[CONF_USERNAME]),
            str(data[CONF_PASSWORD]),
            str(data[CONF_COUNTRY_CODE]),
            load_profile(),
        )

    async def _login(self) -> None:
        """Create an authenticated client for this account."""
        client = self._new_client()
        if self.entry.data.get(CONF_LOGIN_METHOD) == "phone":
            await client.login_phone()
        else:
            await client.login_email()
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch a fresh snapshot, re-authenticating once if the session expired."""
        try:
            if self.client is None or not self.client.session_id:
                await self._login()
            assert self.client is not None
            try:
                homes_raw = await self.client.get_homes()
                devices_by_home: dict[str, list[Any]] = {}
                for home in homes_raw:
                    if not isinstance(home, dict):
                        continue
                    home_id = home.get("groupId") or home.get("gid") or home.get("homeId")
                    if home_id is not None:
                        devices_by_home[str(home_id)] = await self.client.get_devices(str(home_id))
            except NeoLightAuthError:
                await self._login()
                assert self.client is not None
                homes_raw = await self.client.get_homes()
                devices_by_home = {}
                for home in homes_raw:
                    if not isinstance(home, dict):
                        continue
                    home_id = home.get("groupId") or home.get("gid") or home.get("homeId")
                    if home_id is not None:
                        devices_by_home[str(home_id)] = await self.client.get_devices(str(home_id))
            return _normalize_snapshot(homes_raw, devices_by_home)
        except NeoLightApiError as err:
            raise UpdateFailed(f"Unable to refresh NeoLight cloud data: {err}") from err
        except (KeyError, OSError, ValueError) as err:
            raise UpdateFailed("NeoLight configuration or local mobile profile is invalid.") from err


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the cloud coordinator and its live diagnostic entities."""
    coordinator = NeoLightCloudCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        # Do not expose exception details; requests may include account-related data.
        raise ConfigEntryNotReady("Could not initialize the NeoLight cloud session.") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and release cached coordinator data."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
