"""Binary sensor platform for NeoLight MEZZO doorbell ringing events."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NeoLightCloudCoordinator
from .const import DOMAIN


def _device_info_for(device: dict[str, Any]) -> DeviceInfo:
    """Build a consistent DeviceInfo so all entities attach to the same device."""
    device_id = str(device["id"])
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=str(device.get("name") or "NeoLight MEZZO"),
        manufacturer="NeoLight",
        model=str(device.get("product_id") or "MEZZO"),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NeoLight binary sensors from a config entry."""
    coordinator: NeoLightCloudCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_device_ids: set[str] = set()

    def create_device_entities(devices: list[dict[str, Any]]) -> list[BinarySensorEntity]:
        entities: list[BinarySensorEntity] = []
        for device in devices:
            device_id = str(device.get("id") or "")
            if not device_id or device_id in known_device_ids:
                continue
            known_device_ids.add(device_id)
            entities.append(NeoLightDoorbellRingingSensor(coordinator, entry, device))
        return entities

    async_add_entities(create_device_entities(coordinator.data.get("devices", [])))

    @callback
    def _add_new_devices() -> None:
        """Create entities for devices discovered after setup."""
        new_entities = create_device_entities(coordinator.data.get("devices", []))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class NeoLightDoorbellRingingSensor(
    CoordinatorEntity[NeoLightCloudCoordinator], BinarySensorEntity
):
    """Binary sensor indicating when someone is ringing the doorbell."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_name = "Doorbell ringing"

    @property
    def icon(self) -> str:
        """Return dynamic doorbell icon based on ringing state."""
        return "mdi:bell-ring" if self.is_on else "mdi:doorbell-video"

    def __init__(
        self,
        coordinator: NeoLightCloudCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._device_id = str(device.get("id") or "")
        self._attr_unique_id = f"{entry.entry_id}_{self._device_id}_doorbell_ringing"
        self._attr_device_info = _device_info_for(device)

    @property
    def is_on(self) -> bool:
        """Return True if the doorbell is currently ringing."""
        ring_state = self.coordinator.get_doorbell_ring_state(self._device_id)
        return bool(ring_state.get("is_ringing", False))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about the last doorbell ring."""
        ring_state = self.coordinator.get_doorbell_ring_state(self._device_id)
        attrs: dict[str, Any] = {
            "device_id": self._device_id,
            "last_ring_time": ring_state.get("time_iso"),
            "last_ring_timestamp": ring_state.get("timestamp"),
            "message": ring_state.get("message"),
            "source": ring_state.get("source", "cloud"),
        }
        if ring_state.get("picture_url"):
            attrs["caller_photo_url"] = ring_state["picture_url"]
        return attrs
