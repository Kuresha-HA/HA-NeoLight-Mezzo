"""NeoLight MEZZO Home Assistant integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import NeoLightCloudCoordinator

__all__ = ["DOMAIN", "NeoLightCloudCoordinator"]

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.LOCK,
    Platform.CAMERA,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the cloud coordinator and its live diagnostic entities."""
    coordinator = NeoLightCloudCoordinator(hass, entry)
    await coordinator._async_init_snapshots()
    await coordinator._diag("SETUP_START integration_version=0.5.1")
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await coordinator._diag(f"SETUP_FAILED exception_type={type(err).__name__}")
        raise ConfigEntryNotReady(f"Could not initialize the NeoLight cloud session: {err}") from err

    if "_initial_cloud_session" in entry.data:
        cleaned_data = dict(entry.data)
        cleaned_data.pop("_initial_cloud_session", None)
        hass.config_entries.async_update_entry(entry, data=cleaned_data)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.start_doorbell_listener()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and release cached coordinator data."""
    coordinator: NeoLightCloudCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator:
        await coordinator.stop_doorbell_listener()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
