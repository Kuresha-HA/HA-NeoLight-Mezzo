"""Tuya mobile API client used by NeoLight MEZZO.

The mobile API is not the public Tuya Cloud API. Its signing profile is loaded
from a local JSON file and must never be committed to the repository.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import string
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientSession

_LOGGER = logging.getLogger(__name__)
PROFILE_PATH = Path(__file__).with_name("mobile_profile.json")
ENDPOINT_EU = "https://a1.tuyaeu.com/api.json"

# Fields included by the documented/reverse-engineered mobile SDK signer.
_SIGN_FIELDS = {
    "a", "v", "lat", "lon", "lang", "deviceId", "imei", "imsi",
    "appVersion", "ttid", "isH5", "h5Token", "os", "clientId",
    "postData", "time", "requestId", "n4h5", "sid", "sp", "et",
}


class NeoLightApiError(Exception):
    """Base error for NeoLight mobile API."""


class NeoLightAuthError(NeoLightApiError):
    """Login was rejected by the remote service."""


class NeoLightProfileError(NeoLightApiError):
    """Local app signing profile is missing or invalid."""


def load_profile() -> dict[str, str]:
    """Load app signing inputs from a local-only profile file."""
    if not PROFILE_PATH.is_file():
        raise NeoLightProfileError(
            "Missing mobile_profile.json. Generate it locally from the official APK; "
            "never commit this file or share it publicly."
        )
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise NeoLightProfileError("The local mobile profile is unreadable.") from err

    required = ("app_key", "app_secret", "cert_sha256", "embedded_key", "ttid")
    if any(not isinstance(profile.get(key), str) or not profile[key] for key in required):
        raise NeoLightProfileError("The local mobile profile is incomplete.")
    if len(profile["app_key"]) != 20 or len(profile["app_secret"]) != 32:
        raise NeoLightProfileError("The local mobile profile has invalid key lengths.")
    profile["signing_key"] = "_".join(
        (profile["cert_sha256"], profile["embedded_key"], profile["app_secret"])
    )
    return profile


def _mobile_hash(value: str) -> str:
    """Transform the MD5 hex digest as required by the Tuya mobile API."""
    digest = hashlib.md5(value.encode("utf-8")).hexdigest()
    return digest[8:16] + digest[0:8] + digest[24:32] + digest[16:24]


def _signature(params: dict[str, Any], signing_key: str) -> str:
    """Create the mobile-app HMAC-SHA256 signature."""
    segments: list[str] = []
    for key in sorted(params):
        value = params[key]
        if key not in _SIGN_FIELDS or value is None or str(value) == "":
            continue
        if key == "postData":
            value = _mobile_hash(str(value))
        segments.append(f"{key}={value}")
    canonical = "||".join(segments)
    return hmac.new(
        signing_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _random_device_id(length: int = 44) -> str:
    """Generate an app-style client device identifier."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _encrypt_password(password: str, public_key: str, exponent: str) -> str:
    """Encrypt MD5(password) with Tuya's ephemeral textbook-RSA public key."""
    message = hashlib.md5(password.encode("utf-8")).hexdigest().encode("ascii")
    modulus = int(public_key)
    exp = int(exponent)
    width = (modulus.bit_length() + 7) // 8
    value = int.from_bytes(message, "big")
    if value >= modulus:
        raise NeoLightAuthError("The server returned an invalid RSA public key.")
    encrypted = pow(value, exp, modulus).to_bytes(width, "big").hex()
    # Tuya's legacy enhanced-login protocol expects a 64-zero prefix.
    return "0" * 64 + encrypted


class NeoLightMobileApi:
    """Small async client for the Tuya mobile API used by the NeoLight app."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
        country_code: str,
        profile: dict[str, str],
        endpoint: str = ENDPOINT_EU,
    ) -> None:
        self._session = session
        self._username = username.strip()
        self._password = password
        self._country_code = country_code.strip()
        self._profile = profile
        self._endpoint = endpoint
        self._sid: str | None = None
        self._device_id = _random_device_id()

    async def _request(
        self,
        action: str,
        post_data: dict[str, Any] | None = None,
        *,
        version: str = "1.0",
        requires_sid: bool = True,
    ) -> dict[str, Any] | list[Any]:
        """Send one signed request without logging secrets or response payloads."""
        if requires_sid is False:
            sid = None
        else:
            sid = self._sid
            if not sid:
                raise NeoLightAuthError("No authenticated mobile API session.")

        body = json.dumps(post_data, separators=(",", ":"), ensure_ascii=False) if post_data is not None else None
        params: dict[str, Any] = {
            "a": action,
            "v": version,
            "clientId": self._profile["app_key"],
            "deviceId": self._device_id,
            "os": "Android",
            "lang": "en",
            "appVersion": "1.1.0",
            "ttid": self._profile["ttid"],
            "et": "0.0.1",
            "platform": "Android",
            "requestId": str(uuid.uuid4()),
            "time": str(int(time.time())),
        }
        if sid:
            params["sid"] = sid
        if body is not None:
            params["postData"] = body
        params["sign"] = _signature(params, self._profile["signing_key"])

        form = {"postData": body} if body is not None else None
        try:
            async with self._session.post(
                self._endpoint,
                params=params,
                data=form,
                timeout=20,
            ) as response:
                if response.status >= 500:
                    raise NeoLightApiError(f"Tuya mobile API returned HTTP {response.status}.")
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, json.JSONDecodeError) as err:
                    raise NeoLightApiError("Tuya mobile API returned a non-JSON response.") from err
        except (ClientError, TimeoutError) as err:
            raise NeoLightApiError("Could not connect to the NeoLight cloud endpoint.") from err

        if not isinstance(payload, dict):
            raise NeoLightApiError("Unexpected response from the NeoLight cloud endpoint.")
        if payload.get("success") is not True:
            code = str(payload.get("errorCode", "UNKNOWN"))
            message = str(payload.get("errorMsg", "Cloud request failed"))
            if code in {"USER_PASSWD_WRONG", "USER_NOT_EXIST", "USER_ACCOUNT_NOT_EXIST"}:
                raise NeoLightAuthError("The account identifier or password was rejected.")
            raise NeoLightApiError(f"Cloud request failed ({code}): {message}")
        result = payload.get("result")
        if not isinstance(result, (dict, list)):
            raise NeoLightApiError("Cloud response did not contain a result object.")
        return result

    async def login_email(self) -> None:
        """Perform Tuya's enhanced email/password login sequence."""
        token_result = await self._request(
            "tuya.m.user.email.token.create",
            {"countryCode": self._country_code, "email": self._username},
            requires_sid=False,
        )
        if not isinstance(token_result, dict):
            raise NeoLightAuthError("Unexpected login-token response.")
        try:
            encrypted_password = _encrypt_password(
                self._password,
                str(token_result["publicKey"]),
                str(token_result["exponent"]),
            )
            token = str(token_result["token"])
        except (KeyError, ValueError, TypeError) as err:
            raise NeoLightAuthError("Cloud login token response is incomplete.") from err

        login_result = await self._request(
            "tuya.m.user.email.password.login",
            {
                "countryCode": self._country_code,
                "email": self._username,
                "passwd": encrypted_password,
                "ifencrypt": 1,
                "options": {"group": 1},
                "token": token,
            },
            requires_sid=False,
        )
        if not isinstance(login_result, dict) or not login_result.get("sid"):
            raise NeoLightAuthError("Cloud login did not return a session.")
        self._sid = str(login_result["sid"])
        domain = login_result.get("domain")
        if isinstance(domain, dict) and domain.get("mobileApiUrl"):
            host = str(domain["mobileApiUrl"]).rstrip("/")
            if host.startswith("https://"):
                self._endpoint = host if host.endswith("/api.json") else host + "/api.json"

    async def get_homes(self) -> list[Any]:
        """Return locations/homes visible to the signed-in account."""
        result = await self._request("tuya.m.location.list")
        if not isinstance(result, list):
            raise NeoLightApiError("Unexpected home-list response.")
        return result

    async def get_devices(self, home_id: str) -> list[Any]:
        """Return device list for one home."""
        result = await self._request("tuya.m.my.group.device.list", version="1.0")
        if not isinstance(result, list):
            raise NeoLightApiError("Unexpected device-list response.")
        return result

    @property
    def session_id(self) -> str | None:
        """Return the current session ID for the active config flow."""
        return self._sid
