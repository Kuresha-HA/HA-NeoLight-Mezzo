"""Unit tests for the Tuya mobile API signer and request formatting.

Load api.py directly so collecting these tests does not import the Home
Assistant integration package (Home Assistant is not installed in CI).
"""

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

_API_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "neolight_mezzo"
    / "api.py"
)
_SPEC = importlib.util.spec_from_file_location("neolight_mezzo_api_under_test", _API_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_API = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_API)

_encrypt_password = _API._encrypt_password
_mobile_hash = _API._mobile_hash
_signature = _API._signature


def test_mobile_hash_uses_expected_digest_permutation():
    assert _mobile_hash("abc") == "3cd24fb09001509828e17f72d6963f7d"


def test_signature_sorts_and_filters_parameters():
    params = {
        "ignored": "not signed",
        "v": "1.0",
        "postData": '{"x":1}',
        "clientId": "12345678901234567890",
        "a": "test.action",
    }
    assert _signature(params, "test-signing-key") == (
        "8d9b84c7cc6c12dfad706102e1c5b0b165a4acdce5d5e24770cb333329a3278f"
    )


def test_password_encryption_has_legacy_prefix():
    # A toy modulus/exponent is used only to test deterministic encoding.
    password = "test"
    modulus = str((1 << 256) - 189)
    result = _encrypt_password(password, modulus, "1")
    assert result.startswith("0" * 64)
    assert result.endswith(hashlib.md5(password.encode()).hexdigest().encode("ascii").hex())


class _FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def json(self, content_type=None):
        return {"success": True, "result": []}


class _FakeSession:
    def __init__(self):
        self.request = None

    def post(self, url, **kwargs):
        self.request = {"url": url, **kwargs}
        return _FakeResponse()


def test_post_data_is_signed_but_sent_only_in_form_body():
    session = _FakeSession()
    profile = {
        "app_key": "12345678901234567890",
        "signing_key": "test-signing-key",
        "ttid": "testtt",
    }
    client = _API.NeoLightMobileApi(
        session, "user@example.com", "password", "380", profile
    )

    asyncio.run(client._request("test.action", {"x": 1}, requires_sid=False))

    request = session.request
    assert request is not None
    params = request["params"]
    form = request["data"]
    body = json.dumps({"x": 1}, separators=(",", ":"), ensure_ascii=False)
    assert "postData" not in params
    assert params["ttid"] == "testtt"
    assert form == {"postData": body}
    signing_params = {key: value for key, value in params.items() if key != "sign"}
    signing_params["postData"] = body
    assert params["sign"] == _signature(signing_params, profile["signing_key"])



def test_device_discovery_enriches_list_entries_with_details():
    client = _API.NeoLightMobileApi(
        _FakeSession(),
        "user@example.com",
        "password",
        "380",
        {
            "app_key": "12345678901234567890",
            "signing_key": "test-signing-key",
            "ttid": "testtt",
        },
    )
    calls = []

    async def fake_request(action, post_data=None, **kwargs):
        calls.append((action, post_data, kwargs))
        if action == "tuya.m.my.group.device.list":
            return [{"devId": "device-1", "name": "Intercom", "isOnline": True}]
        if action == "tuya.m.device.get":
            return {"devId": "device-1", "productId": "product-1", "category": "sp"}
        raise AssertionError(f"Unexpected action: {action}")

    client._request = fake_request
    devices = asyncio.run(client.get_devices("home-1"))

    assert devices == [{
        "devId": "device-1",
        "name": "Intercom",
        "isOnline": True,
        "productId": "product-1",
        "category": "sp",
    }]
    assert calls[0][0] == "tuya.m.my.group.device.list"
    assert calls[1][0] == "tuya.m.device.get"
    assert calls[1][1] == {"devId": "device-1"}
