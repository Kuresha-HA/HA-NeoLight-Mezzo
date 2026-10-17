"""Diagnostic sensors for devices discovered from the NeoLight cloud."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NeoLightCloudCoordinator
from .const import DOMAIN


def _ms_to_datetime(ms: int | None) -> datetime | None:
    """Convert a millisecond Unix timestamp to a timezone-aware UTC datetime."""
    if not isinstance(ms, int) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _device_info_for(device: dict[str, Any]) -> DeviceInfo:
    """Build a consistent DeviceInfo so all entities attach to the same device."""
    device_id = str(device["id"])
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=str(device.get("name") or "NeoLight device"),
        manufacturer="NeoLight",
        model=str(device.get("product_id") or "Tuya-connected device"),
    )


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
            entities.append(NeoLightDeviceLastActivitySensor(coordinator, entry, device))
            entities.append(NeoLightDoorbellLastRingSensor(coordinator, entry, device))
            present_dps = set((device.get("dps") or {}).keys()) | set(
                (device.get("dps_time") or {}).keys()
            )
            entities.extend(
                NeoLightDataPointSensor(coordinator, entry, device, dp_id)
                for dp_id in ("136", "148", "154", "185", "231", "232", "239", "240", "241", "242")
                if dp_id in present_dps
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
        self._attr_name = "Online"
        self._attr_device_info = _device_info_for(device)
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


class NeoLightDeviceLastActivitySensor(
    CoordinatorEntity[NeoLightCloudCoordinator], SensorEntity
):
    """Latest dpMaxTime reported by the cloud for this device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Last DP activity"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(
        self,
        coordinator: NeoLightCloudCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._device_id = str(device["id"])
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", self._device_id)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_dp_max_time"
        self._attr_device_info = _device_info_for(device)

    @property
    def native_value(self) -> datetime | None:
        """Return dpMaxTime as a UTC datetime."""
        for device in self.coordinator.data.get("devices", []):
            if str(device.get("id")) == self._device_id:
                return _ms_to_datetime(device.get("dp_max_time"))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose raw millisecond timestamps for all DPs."""
        for device in self.coordinator.data.get("devices", []):
            if str(device.get("id")) == self._device_id:
                return {
                    "dp_max_time_ms": device.get("dp_max_time"),
                    "dps_time_ms": device.get("dps_time") or {},
                }
        return {}


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
        self._attr_icon = "mdi:door" if dp_id in {"136", "154", "185", "239", "240"} else "mdi:information-outline"
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
            dps = device.get("dps") or {}
            dps_time = device.get("dps_time") or {}
            if self._dp_id not in dps:
                dt = _ms_to_datetime(dps_time.get(self._dp_id))
                return dt.isoformat() if dt else None
            value = dps.get(self._dp_id)
            if value is None:
                return None
            if isinstance(value, (dict, list)):
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
            dps_time = device.get("dps_time") or {}
            ts_ms = dps_time.get(self._dp_id)
            if isinstance(ts_ms, int):
                attrs["dp_time_ms"] = ts_ms
                dt = _ms_to_datetime(ts_ms)
                if dt is not None:
                    attrs["dp_time_utc"] = dt.isoformat()
            value = (device.get("dps") or {}).get(self._dp_id)
            if self._dp_id == "231" and isinstance(value, str):
                try:
                    decoded = json.loads(value)
                    attrs["channels"] = decoded.get("chs", [])
                    attrs["channel_config"] = decoded
                except (ValueError, TypeError):
                    pass
            break
        return attrs


class NeoLightDoorbellLastRingSensor(
    CoordinatorEntity[NeoLightCloudCoordinator], SensorEntity
):
    """Timestamp sensor for the last time the doorbell was pressed."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_name = "Last doorbell ring"
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(
        self,
        coordinator: NeoLightCloudCoordinator,
        entry: ConfigEntry,
        device: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._device_id = str(device.get("id") or "")
        self._attr_unique_id = f"{entry.entry_id}_{self._device_id}_last_ring"
        self._attr_device_info = _device_info_for(device)

    @property
    def native_value(self) -> datetime | None:
        """Return the UTC datetime of the last doorbell ring."""
        ring_state = self.coordinator.get_doorbell_ring_state(self._device_id)
        ts = ring_state.get("timestamp")
        if isinstance(ts, int) and ts > 0:
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                pass
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return message and caller image attributes."""
        ring_state = self.coordinator.get_doorbell_ring_state(self._device_id)
        attrs: dict[str, Any] = {
            "message": ring_state.get("message"),
            "source": ring_state.get("source"),
        }
        if ring_state.get("picture_url"):
            attrs["caller_photo_url"] = ring_state["picture_url"]
        return attrs

