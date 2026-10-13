"""Unit tests for the ThingClips mobile API signer and request envelope."""
import asyncio
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes

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
_ch_key = _API._ch_key
_master_key_g = _API._master_key_g
_encrypt_post_data = _API._encrypt_post_data
_decrypt_et3_result = _API._decrypt_et3_result


def _profile():
    return {
        "app_key": "12345678901234567890",
        "app_secret": "a" * 32,
        "cert_sha256": ":".join(["AB"] * 32),
        "bmp_token": "0123456789abcdef" * 4,
        "ttid": "rawsdk",
    }


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
    assert _signature(params, b"test-signing-key") == (
        "8d9b84c7cc6c12dfad706102e1c5b0b165a4acdce5d5e24770cb333329a3278f"
    )


def test_ch_key_is_8_hex_characters_and_matches_hmac_slice():
    profile = _profile()
    cert = _API._cert_colon_upper(profile)
    msg = f"{_API.APP_PACKAGE_NAME}_{cert}".encode()
    expected = hmac.new(profile["app_key"].encode(), msg, hashlib.sha256).hexdigest()[8:16]
    value = _ch_key(profile)
    assert value == expected
    assert len(value) == 8
    assert all(c in "0123456789abcdef" for c in value)


def test_master_key_uses_package_cert_raw_bmp_token_and_secret():
    profile = _profile()
    expected = b"_".join((
        _API.APP_PACKAGE_NAME.encode(),
        _API._cert_colon_upper(profile).encode(),
        bytes.fromhex(profile["bmp_token"]),
        profile["app_secret"].encode(),
    ))
    assert _master_key_g(profile) == expected


def test_et3_encrypt_decrypt_round_trip():
    profile = _profile()
    master = _master_key_g(profile)
    request_id = "b5ef7dc7-bb72-4a19-a67b-8f7b2ac12345"
    body = '{"countryCode":"380","username":"test@example.com","isUid":false}'
    encrypted = _encrypt_post_data(body, request_id, master)
    assert encrypted != body
    # Round-trip through the same ET=3 primitive without exposing payload in logs.
    import base64
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(encrypted)
    plain = AESGCM(_API._et3_key(request_id, master)).decrypt(raw[:12], raw[12:], None)
    assert plain.decode() == body


def test_password_encryption_uses_rsa_pkcs1v15_of_md5_hex():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    public_numbers = private_key.public_key().public_numbers()
    password = "test-password"
    encrypted_hex = _encrypt_password(password, str(public_numbers.n), str(public_numbers.e))
    decrypted = private_key.decrypt(bytes.fromhex(encrypted_hex), padding.PKCS1v15())
    assert decrypted == hashlib.md5(password.encode()).hexdigest().encode("ascii")


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


def test_request_has_chkey_and_sends_signed_et3_form_without_query_params():
    session = _FakeSession()
    profile = _profile()
    client = _API.NeoLightMobileApi(
        session, "user@example.com", "password", "380", profile
    )
    asyncio.run(client._request(
        "thing.m.user.username.token.get",
        {"countryCode": "380", "username": "user@example.com", "isUid": False},
        version="2.0",
        requires_sid=False,
    ))
    request = session.request
    assert request is not None
    assert request["url"] == _API.ENDPOINT_EU
    assert "params" not in request
    assert request["headers"]["x-client-trace-id"]
    form = parse_qs(request["data"])
    assert form["a"] == ["smartlife.m.user.username.token.get"]
    assert form["ttid"] == [f"sdk_international@{profile['app_key']}"]
    assert form["chKey"] == [_ch_key(profile)]
    assert len(form["chKey"][0]) == 8
    assert form["et"] == ["3"]
    assert form["channel"] == ["oem"]
    assert "postData" in form
    signing_params = {key: values[0] for key, values in form.items() if key not in {"sign", "postData"}}
    signing_params["postData"] = form["postData"][0]
    assert form["sign"] == [_signature(signing_params, _master_key_g(profile))]


def test_device_discovery_uses_thingclips_home_and_device_actions():
    client = _API.NeoLightMobileApi(
        _FakeSession(), "user@example.com", "password", "380", _profile()
    )
    calls = []

    async def fake_request(action, post_data=None, **kwargs):
        calls.append((action, post_data, kwargs))
        if action == "m.life.my.group.device.list":
            return [{"devId": "device-1", "name": "Intercom", "isOnline": True}]
        raise AssertionError(f"Unexpected action: {action}")

    client._request = fake_request
    devices = asyncio.run(client.get_devices("123"))
    assert devices == [{"devId": "device-1", "name": "Intercom", "isOnline": True}]
    assert calls == [("m.life.my.group.device.list", {"gid": 123}, {"version": "2.2", "ecode": None})]



def test_email_login_passes_mfa_code_inside_options():
    client = _API.NeoLightMobileApi(
        _FakeSession(), "user@example.com", "password", "380", _profile()
    )
    calls = []

    # A real RSA modulus is needed by the password encryption helper.
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    numbers = private_key.public_key().public_numbers()
    async def token_and_login(action, post_data=None, **kwargs):
        calls.append((action, post_data, kwargs))
        if action == "thing.m.user.username.token.get":
            return {"publicKey": str(numbers.n), "exponent": str(numbers.e), "token": "ticket"}
        if action == "thing.m.user.email.password.login":
            return {"sid": "session"}
        raise AssertionError(f"Unexpected action: {action}")
    client._request = token_and_login

    asyncio.run(client.login_email(mfa_code="123456"))
    login_call = next(call for call in calls if call[0] == "thing.m.user.email.password.login")
    assert json.loads(login_call[1]["options"]) == {"group": 1, "mfaCode": "123456"}
    assert client.session_id == "session"
