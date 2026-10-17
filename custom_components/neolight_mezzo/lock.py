"""Lock platform for NeoLight MEZZO electric door strikes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NeoLightCloudCoordinator


def _device_info_for(device: dict[str, Any]) -> DeviceInfo:
    """Build a consistent DeviceInfo attaching locks to the doorbell device."""
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
    """Set up NeoLight door lock entities from a config entry."""
    coordinator: NeoLightCloudCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_device_ids: set[str] = set()

    def create_device_entities(devices: list[dict[str, Any]]) -> list[LockEntity]:
        entities: list[LockEntity] = []
        for device in devices:
            device_id = str(device.get("id") or "")
            if not device_id or device_id in known_device_ids:
                continue
            known_device_ids.add(device_id)
            entities.append(
                NeoLightDoorLock(coordinator, entry, device, door_channel=1, name="Door 1")
            )
            entities.append(
                NeoLightDoorLock(coordinator, entry, device, door_channel=2, name="Door 2")
            )
        return entities

    async_add_entities(create_device_entities(coordinator.data.get("devices", [])))

    @callback
    def _add_new_devices() -> None:
        new_entities = create_device_entities(coordinator.data.get("devices", []))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class NeoLightDoorLock(
    CoordinatorEntity[NeoLightCloudCoordinator], LockEntity
):
    """Lock entity for an electric door strike controlled by NeoLight MEZZO."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NeoLightCloudCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
        door_channel: int,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = str(device.get("id") or "")
        self._door_channel = door_channel
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{self._device_id}_lock_ch{door_channel}"
        self._attr_device_info = _device_info_for(device)
        self._is_locked = True

    @property
    def is_locked(self) -> bool:
        """Return True as intercom door strikes are normally locked."""
        return self._is_locked

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the electric door strike, auto-relocking after 5 seconds."""
        await self.coordinator.async_unlock_door(self._device_id, self._door_channel)
        self._is_locked = False
        self.async_write_ha_state()

        @callback
        def _auto_relock() -> None:
            self._is_locked = True
            self.async_write_ha_state()

        self.hass.loop.call_later(5, _auto_relock)

    async def async_lock(self, **kwargs: Any) -> None:
        """Return lock to secured state."""
        self._is_locked = True
        self.async_write_ha_state()
