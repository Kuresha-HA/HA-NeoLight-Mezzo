"""Unit tests for the Tuya mobile API signer.

Load api.py directly so collecting these unit tests does not import the
Home Assistant integration package (Home Assistant is not installed in CI).
"""

import hashlib
import importlib.util
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
