"""Camera platform displaying caller snapshots captured by NeoLight MEZZO doorbell."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NeoLightCloudCoordinator

_LOGGER = logging.getLogger(__name__)


def _device_info_for(device: dict[str, Any]) -> DeviceInfo:
    """Build a consistent DeviceInfo attaching camera to the doorbell device."""
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
    """Set up NeoLight caller snapshot camera from a config entry."""
    coordinator: NeoLightCloudCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_device_ids: set[str] = set()

    def create_device_entities(devices: list[dict[str, Any]]) -> list[Camera]:
        entities: list[Camera] = []
        for device in devices:
            device_id = str(device.get("id") or "")
            if not device_id or device_id in known_device_ids:
                continue
            known_device_ids.add(device_id)
            entities.append(NeoLightCallerCamera(coordinator, entry, device))
        return entities

    entities = create_device_entities(coordinator.data.get("devices", []))
    async_add_entities(entities)

    @callback
    def _add_new_devices() -> None:
        new_entities = create_device_entities(coordinator.data.get("devices", []))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class NeoLightCallerCamera(CoordinatorEntity[NeoLightCloudCoordinator], Camera):
    """Camera entity showing the high-resolution snapshot of the doorbell caller."""

    _attr_has_entity_name = True
    _attr_translation_key = "caller_photo"
    _attr_icon = "mdi:camera-front-variant"
    _attr_supported_features = CameraEntityFeature(0)

    def __init__(
        self,
        coordinator: NeoLightCloudCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._device_id = str(device.get("id") or "")
        self._attr_unique_id = f"{entry.entry_id}_{self._device_id}_caller_camera"
        self._attr_device_info = _device_info_for(device)
        self._last_loaded_url: str | None = None
        self._last_image_bytes: bytes | None = None

    @property
    def is_on(self) -> bool:
        """Return true as caller camera is always active."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return caller metadata alongside camera entity."""
        ring_state = self.coordinator.get_doorbell_ring_state(self._device_id)
        return {
            "device_id": self._device_id,
            "last_ring_time": ring_state.get("time_iso"),
            "last_ring_timestamp": ring_state.get("timestamp"),
            "message": ring_state.get("message"),
            "caller_photo_url": ring_state.get("picture_url"),
            "source": ring_state.get("source"),
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Fetch the high-resolution caller snapshot from the secure S3 pre-signed URL."""
        ring_state = self.coordinator.get_doorbell_ring_state(self._device_id)
        pic_url = ring_state.get("picture_url")

        if not pic_url:
            cached = self.coordinator.get_cached_snapshot(self._device_id)
            return cached or self._last_image_bytes

        if pic_url == self._last_loaded_url and self._last_image_bytes is not None:
            return self._last_image_bytes

        try:
            session = async_get_clientsession(self.hass)
            async with session.get(pic_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if data and (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")):
                        self._last_loaded_url = pic_url
                        self._last_image_bytes = data
                        self.coordinator.set_cached_snapshot(self._device_id, data)
                        return data
        except Exception as err:
            _LOGGER.debug("Failed to download caller photo from %s: %s", pic_url[:80], err)

        cached = self.coordinator.get_cached_snapshot(self._device_id)
        return cached or self._last_image_bytes
