"""Diagnostic sensors for devices discovered from the NeoLight cloud."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors from the sanitized device snapshot saved during setup."""
    devices: list[dict[str, Any]] = entry.data.get("devices", [])
    async_add_entities(
        [NeoLightDeviceCountSensor(entry, devices)]
        + [NeoLightDeviceOnlineSensor(entry, device) for device in devices if device.get("id")]
    )


class NeoLightDeviceCountSensor(SensorEntity):
    """Count devices discovered in the account during config flow."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Discovered devices"
    _attr_icon = "mdi:devices"

    def __init__(self, entry: ConfigEntry, devices: list[dict[str, Any]]) -> None:
        self._devices = devices
        self._attr_unique_id = f"{entry.entry_id}_device_count"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NeoLight cloud account",
            manufacturer="NeoLight",
            model="Tuya mobile cloud",
        )

    @property
    def native_value(self) -> int:
        """Return the number of discovered devices."""
        return len(self._devices)


class NeoLightDeviceOnlineSensor(SensorEntity):
    """Online-state snapshot for one discovered device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"

    def __init__(self, entry: ConfigEntry, device: dict[str, Any]) -> None:
        self._device = device
        dev_id = str(device["id"])
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", dev_id)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_online"
        self._attr_name = f"{device.get('name') or 'Device'} online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dev_id)},
            name=str(device.get("name") or "NeoLight device"),
            manufacturer="NeoLight",
            model=str(device.get("product_id") or "Tuya-connected device"),
            via_device=(DOMAIN, entry.entry_id),
        )
        self._attr_extra_state_attributes = {
            "product_id": device.get("product_id") or None,
            "category": device.get("category") or None,
            "home_id": device.get("home_id") or None,
        }

    @property
    def native_value(self) -> str:
        """Return the online state captured during setup."""
        return "online" if self._device.get("online") else "offline"
