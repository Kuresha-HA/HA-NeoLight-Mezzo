"""Helpers for sanitizing NeoLight cloud discovery records."""

from __future__ import annotations

from typing import Any


def _as_bool(value: Any) -> bool:
    """Normalize common JSON/API boolean encodings without treating 'false' as true."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "online"}
    return False


def _clean_name(name: str) -> str:
    """Repair mojibake caused by UTF-8 strings interpreted as latin1."""
    if not name:
        return ""
    if any(ch in name for ch in ("Ð", "Ñ", "Ã", "Â")):
        try:
            return name.encode("latin1").decode("utf-8")
        except Exception:
            pass
    return name


def normalize_snapshot(
    homes_raw: list[Any], devices_by_home: dict[str, list[Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Normalize cloud records while retaining only non-sensitive metadata."""
    homes: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    seen_devices: set[str] = set()
    for home in homes_raw:
        if not isinstance(home, dict):
            continue
        home_id = home.get("groupId") or home.get("gid") or home.get("homeId")
        if home_id is None:
            continue
        home_id = str(home_id)
        raw_home_name = str(home.get("name") or home.get("groupName") or "NeoLight home")
        homes.append({
            "id": home_id,
            "name": _clean_name(raw_home_name),
        })
        for device in devices_by_home.get(home_id, []):
            if not isinstance(device, dict):
                continue
            device_id = device.get("devId") or device.get("id")
            if device_id is None or not str(device_id):
                continue
            device_id = str(device_id)
            if device_id in seen_devices:
                continue
            seen_devices.add(device_id)
            dp_info = device.get("dataPointInfo")
            dp_info = dp_info if isinstance(dp_info, dict) else {}
            raw_dps = dp_info.get("dps")
            raw_dps_time = dp_info.get("dpsTime")
            raw_max_time = dp_info.get("dpMaxTime")
            raw_dev_name = str(device.get("name") or "NeoLight device")
            devices.append({
                "id": device_id,
                "name": _clean_name(raw_dev_name),
                "online": _as_bool(
                    device.get("isOnline")
                    if "isOnline" in device
                    else device.get("cloudOnline", False)
                ),
                "product_id": str(device.get("productId") or ""),
                "category": str(device.get("category") or ""),
                "home_id": home_id,
                # Keep only the current DP snapshot; retain localKey for local push.
                "dps": (
                    {
                        str(key): value
                        for key, value in raw_dps.items()
                        if isinstance(value, (str, int, float, bool)) or value is None
                    }
                    if isinstance(raw_dps, dict)
                    else {}
                ),
                "dps_time": (
                    {
                        str(key): int(value)
                        for key, value in raw_dps_time.items()
                        if isinstance(value, (int, float))
                    }
                    if isinstance(raw_dps_time, dict)
                    else {}
                ),
                "dp_max_time": (
                    int(raw_max_time)
                    if isinstance(raw_max_time, (int, float))
                    else None
                ),
            })
    return {"homes": homes, "devices": devices}
