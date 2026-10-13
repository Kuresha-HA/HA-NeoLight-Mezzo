"""Tests for sanitizing NeoLight cloud snapshots."""

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "neolight_mezzo"
    / "cloud_data.py"
)
_SPEC = importlib.util.spec_from_file_location("neolight_cloud_data_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
normalize_snapshot = _MODULE.normalize_snapshot


def test_normalize_snapshot_keeps_only_safe_home_and_device_metadata():
    snapshot = normalize_snapshot(
        [
            {"groupId": 123, "name": "Home", "token": "must-not-leak"},
            {"name": "invalid home"},
            "invalid record",
        ],
        {
            "123": [
                {
                    "devId": "device-1",
                    "name": "MEZZO",
                    "isOnline": True,
                    "productId": "product-1",
                    "category": "doorbell",
                    "localKey": "must-not-leak",
                    "secret": "must-not-leak",
                },
                {"name": "missing device id", "isOnline": True},
                None,
            ]
        },
    )

    assert snapshot == {
        "homes": [{"id": "123", "name": "Home"}],
        "devices": [
            {
                "id": "device-1",
                "name": "MEZZO",
                "online": True,
                "product_id": "product-1",
                "category": "doorbell",
                "home_id": "123",
            }
        ],
    }


def test_normalize_snapshot_reflects_changed_online_state():
    online = normalize_snapshot(
        [{"gid": "42", "groupName": "Home"}],
        {"42": [{"id": "device-2", "isOnline": True}]},
    )
    offline = normalize_snapshot(
        [{"gid": "42", "groupName": "Home"}],
        {"42": [{"id": "device-2", "isOnline": False}]},
    )

    assert online["devices"][0]["online"] is True
    assert offline["devices"][0]["online"] is False


def test_normalize_snapshot_accepts_empty_cloud_response():
    assert normalize_snapshot([], {}) == {"homes": [], "devices": []}
