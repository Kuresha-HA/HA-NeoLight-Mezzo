"""Unit tests for the Tuya mobile API signer."""

import hashlib

from custom_components.neolight_mezzo.api import _encrypt_password, _mobile_hash, _signature


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
    assert result.endswith(hashlib.md5(password.encode()).hexdigest())
