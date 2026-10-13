"""Helpers for sanitizing NeoLight cloud discovery records."""

from __future__ import annotations

from typing import Any


def normalize_snapshot(
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
