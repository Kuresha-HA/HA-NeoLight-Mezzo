"""Diagnostic sensors for devices discovered from the NeoLight cloud."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NeoLightCloudCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create coordinator-backed sensors and add devices discovered later."""
    coordinator: NeoLightCloudCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_device_ids: set[str] = set()

    def create_device_entities(devices: list[dict[str, Any]]) -> list[SensorEntity]:
        entities: list[SensorEntity] = []
        for device in devices:
            device_id = str(device.get("id") or "")
            if not device_id or device_id in known_device_ids:
                continue
            known_device_ids.add(device_id)
            entities.append(NeoLightDeviceOnlineSensor(coordinator, entry, device))
            if device.get("dps"):
                entities.extend(
                    NeoLightDataPointSensor(coordinator, entry, device, dp_id)
                    for dp_id in ("136", "148", "154", "185", "231", "232", "239", "240", "241", "242")
                    if dp_id in device["dps"]
                )
        return entities

    async_add_entities(
        [NeoLightDeviceCountSensor(coordinator, entry)]
        + create_device_entities(coordinator.data.get("devices", []))
    )

    @callback
    def _add_new_devices() -> None:
        """Create entities for devices that appear after the initial setup."""
        new_entities = create_device_entities(coordinator.data.get("devices", []))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class NeoLightDeviceCountSensor(CoordinatorEntity[NeoLightCloudCoordinator], SensorEntity):
    """Count devices currently discovered in the cloud account."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Discovered devices"
    _attr_icon = "mdi:devices"

    def __init__(self, coordinator: NeoLightCloudCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_device_count"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="NeoLight cloud account",
            manufacturer="NeoLight",
            model="Tuya mobile cloud",
        )

    @property
    def native_value(self) -> int:
        """Return the latest number of discovered devices."""
        return len(self.coordinator.data.get("devices", []))


class NeoLightDeviceOnlineSensor(
    CoordinatorEntity[NeoLightCloudCoordinator], SensorEntity
):
    """Current online state for one discovered device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lan-connect"

    def __init__(
        self,
        coordinator: NeoLightCloudCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._device_id = str(device["id"])
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", self._device_id)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_online"
        self._attr_name = f"{device.get('name') or 'Device'} online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
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
        """Return the latest online state, not the initial config-flow snapshot."""
        for device in self.coordinator.data.get("devices", []):
            if str(device.get("id")) == self._device_id:
                return "online" if device.get("online") else "offline"
        return "unknown"


_DP_NAMES = {
    "136": "Doorbell event",
    "148": "Accessory lock state",
    "154": "Doorbell snapshot data",
    "185": "Alarm message data",
    "231": "Video channel configuration",
    "232": "Lock 2 state",
    "239": "Doorbell 1 call status",
    "240": "Doorbell 2 call status",
    "241": "Door 1 unlock DP state",
    "242": "Door 2 unlock DP state",
}


class NeoLightDataPointSensor(
    CoordinatorEntity[NeoLightCloudCoordinator], SensorEntity
):
    """Expose a read-only snapshot of one documented product Data Point."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NeoLightCloudCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
        dp_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = str(device["id"])
        self._dp_id = dp_id
        self._attr_unique_id = f"{entry.entry_id}_{self._device_id}_dp_{dp_id}"
        self._attr_name = _DP_NAMES.get(dp_id, f"Data Point {dp_id}")
        self._attr_icon = "mdi:door" if dp_id in {"136", "239", "240"} else "mdi:information-outline"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=str(device.get("name") or "NeoLight device"),
            manufacturer="NeoLight",
            model=str(device.get("product_id") or "Tuya-connected device"),
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def native_value(self) -> str | None:
        """Return the latest DP value as a safe string state."""
        for device in self.coordinator.data.get("devices", []):
            if str(device.get("id")) != self._device_id:
                continue
            value = (device.get("dps") or {}).get(self._dp_id)
            if value is None:
                return None
            if isinstance(value, (dict, list)):
                import json
                return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Include the DP ID and, for channel metadata, decoded channel options."""
        attrs: dict[str, Any] = {"dp_id": int(self._dp_id)}
        for device in self.coordinator.data.get("devices", []):
            if str(device.get("id")) != self._device_id:
                continue
            value = (device.get("dps") or {}).get(self._dp_id)
            if self._dp_id == "231" and isinstance(value, str):
                import json
                try:
                    decoded = json.loads(value)
                    attrs["channels"] = decoded.get("chs", [])
                    attrs["channel_config"] = decoded
                except (ValueError, TypeError):
                    pass
            break
        return attrs
