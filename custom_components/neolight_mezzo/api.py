"""ThingClips mobile API client used by NeoLight MEZZO.

The request envelope is based on the ThingClips SDK protocol recovered from the
NeoLight APK and cross-checked against independent SDK analysis. Signing material
is local-only and must never be committed or logged.
"""
from __future__ import annotations

import base64
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
from urllib.parse import urlencode

from aiohttp import ClientError, ClientSession
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_LOGGER = logging.getLogger(__name__)
PROFILE_PATH = Path(__file__).with_name("mobile_profile.json")
ENDPOINT_EU = "https://a1.tuyaeu.com/api.json"
APP_PACKAGE_NAME = "com.neolight.neo"
APP_VERSION = "1.1.0"
SDK_VERSION = "6.7.1"
APP_RN_VERSION = "5.99"

# Exact ThingClips mobile-sign whitelist. Only these non-empty fields contribute
# to the canonical string. Other form fields are transport metadata, not signed.
_SIGN_FIELDS = {
    "a", "v", "lat", "lon", "lang", "deviceId", "appVersion", "ttid",
    "isH5", "h5Token", "os", "clientId", "postData", "time", "requestId",
    "et", "n4h5", "sid", "chKey", "sp",
}


class NeoLightApiError(Exception):
    """Base error for NeoLight mobile API."""


class NeoLightAuthError(NeoLightApiError):
    """Login was rejected by the remote service."""


class NeoLightProfileError(NeoLightApiError):
    """Local mobile signing profile is missing or invalid."""


class NeoLightMFAError(NeoLightAuthError):
    """The cloud requires an additional email verification step."""


def load_profile() -> dict[str, str]:
    """Load app signing inputs from a local-only profile file."""
    if not PROFILE_PATH.is_file():
        raise NeoLightProfileError(
            "Missing mobile_profile.json. Regenerate it from the official APK; "
            "never commit this file or share its contents publicly."
        )
    try:
        profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise NeoLightProfileError("The local mobile profile is unreadable.") from err

    # Older profiles used an unverified 32-character embedded_key. The SDK's
    # matrix decoder produces one 64-character hex bmp_token; reject old profiles
    # instead of silently signing every request with invalid key material.
    required = ("app_key", "app_secret", "cert_sha256", "bmp_token", "ttid")
    if any(not isinstance(profile.get(key), str) or not profile[key] for key in required):
        raise NeoLightProfileError(
            "The mobile profile is outdated: it must contain bmp_token derived "
            "from assets/t_s.bmp (64 hexadecimal characters)."
        )
    if (
        len(profile["app_key"]) != 20
        or len(profile["app_secret"]) != 32
        or len(profile["cert_sha256"]) != 95
        or len(profile["bmp_token"]) != 64
        or not all(ch in string.hexdigits for ch in profile["bmp_token"])
    ):
        raise NeoLightProfileError(
            "The mobile profile has invalid key lengths or bmp_token format."
        )
    if len(profile["cert_sha256"].split(":")) != 32:
        raise NeoLightProfileError("The APK certificate fingerprint is malformed.")
    return profile


def _mobile_hash(value: str) -> str:
    """Tuya postData digest: MD5 hex with the SDK's 8/8/8/8 block permutation."""
    digest = hashlib.md5(value.encode("utf-8")).hexdigest()
    return digest[8:16] + digest[0:8] + digest[24:32] + digest[16:24]


def _cert_colon_upper(profile: dict[str, str]) -> str:
    """Return the APK SHA-256 as 95-character colon-separated uppercase hex."""
    raw = profile["cert_sha256"].replace(":", "").strip()
    if len(raw) != 64 or any(ch not in string.hexdigits for ch in raw):
        raise NeoLightProfileError("The APK certificate fingerprint is malformed.")
    return ":".join(raw[i:i + 2] for i in range(0, 64, 2)).upper()


def _master_key_g(profile: dict[str, str]) -> bytes:
    """Assemble the SDK's master key G from package, cert, decoded BMP token, secret."""
    try:
        matrix_key = bytes.fromhex(profile["bmp_token"])
    except ValueError as err:
        raise NeoLightProfileError("The BMP token must be 64 hexadecimal characters.") from err
    return b"_".join((
        APP_PACKAGE_NAME.encode("utf-8"),
        _cert_colon_upper(profile).encode("ascii"),
        matrix_key,
        profile["app_secret"].encode("utf-8"),
    ))


def _ch_key(profile: dict[str, str]) -> str:
    """Calculate the 8-hex-character client-binding value required by ThingClips."""
    message = f"{APP_PACKAGE_NAME}_{_cert_colon_upper(profile)}".encode("utf-8")
    digest = hmac.new(profile["app_key"].encode("utf-8"), message, hashlib.sha256).hexdigest()
    # The native getChKey implementation returns hex[8:16], exactly 8 characters.
    return digest[8:16]


def _signature(params: dict[str, Any], signing_key: bytes | str) -> str:
    """Create the SDK request signature: HMAC-SHA256(master-key G, canonical params)."""
    segments: list[str] = []
    for key in sorted(params):
        value = params[key]
        if key not in _SIGN_FIELDS or value is None or str(value) == "":
            continue
        if key == "postData":
            value = _mobile_hash(str(value))
        segments.append(f"{key}={value}")
    canonical = "||".join(segments)
    key_bytes = signing_key.encode("utf-8") if isinstance(signing_key, str) else signing_key
    return hmac.new(key_bytes, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _et3_key(request_id: str, master_key: bytes, ecode: str | None = None) -> bytes:
    """Derive the 16-byte ASCII-hex AES-GCM key used for ET=3 payloads."""
    message = master_key
    if ecode:
        message += b"_" + ecode.encode("utf-8")
    digest_hex = hmac.new(request_id.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return digest_hex[:16].encode("ascii")


def _encrypt_post_data(
    post_data: str, request_id: str, master_key: bytes, ecode: str | None = None
) -> str:
    """AES-128-GCM encrypt postData; wire value is base64(nonce || ciphertext || tag)."""
    nonce = secrets.token_bytes(12)
    cipher_text_and_tag = AESGCM(_et3_key(request_id, master_key, ecode)).encrypt(
        nonce, post_data.encode("utf-8"), None
    )
    return base64.b64encode(nonce + cipher_text_and_tag).decode("ascii")


def _decrypt_et3_result(
    result: str, request_id: str, master_key: bytes, ecode: str | None = None
) -> dict[str, Any]:
    """Decrypt the accepted ET=3 response envelope without logging plaintext."""
    try:
        raw = base64.b64decode(result, validate=True)
        if len(raw) < 28:
            raise ValueError("response too short")
        plain = AESGCM(_et3_key(request_id, master_key, ecode)).decrypt(
            raw[:12], raw[12:], None
        )
        data = json.loads(plain.decode("utf-8"))
    except Exception as err:
        raise NeoLightApiError("Could not decode the encrypted NeoLight cloud response.") from err
    if not isinstance(data, dict):
        raise NeoLightApiError("Unexpected decrypted cloud response.")
    return data


def _rewrite_action(action: str) -> str:
    """ThingClips rewrites the leading 'thing' namespace to 'smartlife' on wire."""
    return "smartlife" + action[5:] if action.startswith("thing") else action


def _random_device_id(length: int = 44) -> str:
    """Generate a stable-for-this-config-flow, app-shaped lowercase hex device ID."""
    return secrets.token_hex(length // 2)


def _encrypt_password(password: str, public_key: str, exponent: str) -> str:
    """RSA/PKCS#1 v1.5 encrypt the lowercase MD5 hex of the password."""
    try:
        modulus = int(public_key)
        exp = int(exponent or "65537")
        key = rsa.RSAPublicNumbers(exp, modulus).public_key()
        digest = hashlib.md5(password.encode("utf-8")).hexdigest().encode("ascii")
        return key.encrypt(digest, padding.PKCS1v15()).hex()
    except Exception as err:
        raise NeoLightAuthError("The cloud returned an invalid RSA login key.") from err


class NeoLightMobileApi:
    """Async client for the NeoLight app's ThingClips mobile-cloud API."""

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
        self._ecode: str | None = None
        self._login_summary: dict[str, Any] = {}
        self._device_id = _random_device_id()
        self._master_key = _master_key_g(profile)
        self._ch_key = _ch_key(profile)

    async def _request(
        self,
        action: str,
        post_data: dict[str, Any] | None = None,
        *,
        version: str = "1.0",
        requires_sid: bool = True,
        extra_params: dict[str, Any] | None = None,
        ecode: str | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Send one app-faithful, signed ET=3 request with no query-string secrets."""
        sid = self._sid if requires_sid else None
        if requires_sid and not sid:
            raise NeoLightAuthError("No authenticated mobile API session.")

        request_id = str(uuid.uuid4())
        params: dict[str, Any] = {
            "a": _rewrite_action(action),
            "v": version,
            "clientId": self._profile["app_key"],
            "deviceId": self._device_id,
            "os": "Android",
            "lang": "en",
            "appVersion": APP_VERSION,
            "ttid": f"sdk_international@{self._profile['app_key']}",
            "et": "3",
            "channel": "oem",
            "platform": "Android",
            "appRnVersion": APP_RN_VERSION,
            "osSystem": "9",
            "timeZoneId": "Europe/Kyiv",
            "sdkVersion": SDK_VERSION,
            "deviceCoreVersion": SDK_VERSION,
            "cp": "gzip",
            "nd": "1",
            "bizData": json.dumps(
                {"customDomainSupport": "1", "nd": "1", "sdkInt": "28", "brand": "Android"},
                separators=(",", ":"),
            ),
            "chKey": self._ch_key,
            "requestId": request_id,
            "time": str(int(time.time())),
        }
        if sid:
            params["sid"] = sid
        if extra_params:
            params.update(extra_params)

        wire_post_data: str | None = None
        if post_data is not None:
            raw_body = json.dumps(post_data, separators=(",", ":"), ensure_ascii=False)
            wire_post_data = _encrypt_post_data(
                raw_body, request_id, self._master_key, ecode if ecode is not None else (self._ecode if requires_sid else None)
            )
        signing_params = dict(params)
        if wire_post_data is not None:
            signing_params["postData"] = wire_post_data
        params["sign"] = _signature(signing_params, self._master_key)

        # ThingClips sends all envelope fields as form data, not URL query params.
        form = {key: str(value) for key, value in params.items()}
        if wire_post_data is not None:
            form["postData"] = wire_post_data
        try:
            async with self._session.post(
                self._endpoint,
                data=urlencode(form),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "x-client-trace-id": request_id,
                },
                timeout=20,
            ) as response:
                if response.status >= 500:
                    raise NeoLightApiError(f"NeoLight cloud returned HTTP {response.status}.")
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, json.JSONDecodeError) as err:
                    raise NeoLightApiError("NeoLight cloud returned a non-JSON response.") from err
        except (ClientError, TimeoutError) as err:
            raise NeoLightApiError("Could not connect to the NeoLight cloud endpoint.") from err

        if not isinstance(payload, dict):
            raise NeoLightApiError("Unexpected response from the NeoLight cloud endpoint.")

        # Gateway-level rejects are plaintext and happen before ET=3 response
        # encryption. Preserve the actual code while never logging request material.
        if payload.get("success") is False:
            code = str(payload.get("errorCode", "UNKNOWN"))
            message = str(payload.get("errorMsg", "Cloud request failed"))
            # Sanitized diagnostics only: never log credentials, tokens, signatures,
            # encrypted payloads, or response result fields.
            _LOGGER.warning(
                "NeoLight API rejected action=%s version=%s code=%s message=%s",
                params.get("a"), version, code, message[:240],
            )
            if code in {"USER_PASSWD_WRONG", "USER_NOT_EXIST", "USER_ACCOUNT_NOT_EXIST"}:
                raise NeoLightAuthError("The account identifier or password was rejected.")
            if code == "MFA_NEED_SEND_CODE":
                raise NeoLightMFAError("NeoLight cloud requires an email verification code.")
            raise NeoLightApiError(f"Cloud request failed for action {params.get('a')} ({code}): {message}")

        if "success" not in payload and isinstance(payload.get("result"), str):
            payload = _decrypt_et3_result(
                payload["result"],
                request_id,
                self._master_key,
                ecode if ecode is not None else (self._ecode if requires_sid else None),
            )
        if payload.get("success") is not True:
            code = str(payload.get("errorCode", "UNKNOWN"))
            _LOGGER.warning(
                "NeoLight API returned unsuccessful response action=%s version=%s code=%s",
                params.get("a"), version, code,
            )
            if code == "MFA_NEED_SEND_CODE":
                raise NeoLightMFAError("NeoLight cloud requires an email verification code.")
            raise NeoLightApiError(f"Cloud request failed ({code}).")

        result = payload.get("result")
        if not isinstance(result, (dict, list)):
            raise NeoLightApiError("Cloud response did not contain a result object.")
        return result

    async def login_email(self, mfa_code: str = "") -> None:
        """Authenticate with the NeoLight account using the ThingClips ticket flow."""
        token_result = await self._request(
            "thing.m.user.username.token.get",
            {
                "countryCode": self._country_code,
                "username": self._username,
                "isUid": False,
            },
            version="2.0",
            requires_sid=False,
        )
        if not isinstance(token_result, dict):
            raise NeoLightAuthError("Unexpected login-token response.")
        try:
            encrypted_password = _encrypt_password(
                self._password,
                str(token_result["publicKey"]),
                str(token_result.get("exponent", "65537")),
            )
            token = str(token_result["token"])
        except (KeyError, ValueError, TypeError) as err:
            raise NeoLightAuthError("Cloud login-token response is incomplete.") from err

        login_result = await self._request(
            "thing.m.user.email.password.login",
            {
                "countryCode": self._country_code,
                "email": self._username,
                "passwd": encrypted_password,
                "ifencrypt": 1,
                "options": json.dumps({"group": 1, "mfaCode": mfa_code}, separators=(",", ":")),
                "token": token,
            },
            version="3.0",
            requires_sid=False,
        )
        if not isinstance(login_result, dict) or not login_result.get("sid"):
            raise NeoLightAuthError("Cloud login did not return a session.")
        self._apply_login_session(login_result)

    def _apply_login_session(self, login_result: dict[str, Any]) -> None:
        """Store session parameters and honor the API host returned by the cloud."""
        self._sid = str(login_result["sid"])
        if login_result.get("ecode"):
            self._ecode = str(login_result["ecode"])
        domain = login_result.get("domain")
        self._login_summary = {
            "login_keys": sorted(str(key) for key in login_result.keys()),
            "domain": {
                str(key): str(value)[:300]
                for key, value in domain.items()
                if isinstance(value, (str, int, float, bool))
                and any(term in str(key).casefold() for term in ("url", "host", "region", "mqtt"))
            } if isinstance(domain, dict) else None,
            "partnerIdentity": login_result.get("partnerIdentity"),
            "regionCode": login_result.get("regionCode"),
        }
        if isinstance(domain, dict) and domain.get("mobileApiUrl"):
            host = str(domain["mobileApiUrl"]).rstrip("/")
            if host.startswith("https://"):
                self._endpoint = host if host.endswith("/api.json") else host + "/api.json"

    async def login_phone(self, mfa_code: str = "") -> None:
        """Attempt the mobile-number login variant of the ThingClips ticket flow."""
        token_result = await self._request(
            "thing.m.user.username.token.get",
            {
                "countryCode": self._country_code,
                "username": self._username,
                "isUid": False,
            },
            version="2.0",
            requires_sid=False,
        )
        if not isinstance(token_result, dict):
            raise NeoLightAuthError("Unexpected phone login-token response.")
        try:
            encrypted_password = _encrypt_password(
                self._password,
                str(token_result["publicKey"]),
                str(token_result.get("exponent", "65537")),
            )
            token = str(token_result["token"])
        except (KeyError, ValueError, TypeError) as err:
            raise NeoLightAuthError("Phone login-token response is incomplete.") from err

        login_result = await self._request(
            "thing.m.user.mobile.passwd.login",
            {
                "countryCode": self._country_code,
                "mobile": self._username,
                "passwd": encrypted_password,
                "ifencrypt": 1,
                "options": json.dumps({"group": 1, "mfaCode": mfa_code}, separators=(",", ":")),
                "token": token,
            },
            version="3.0",
            requires_sid=False,
        )
        if not isinstance(login_result, dict) or not login_result.get("sid"):
            raise NeoLightAuthError("Phone login did not return a session.")
        self._apply_login_session(login_result)

    async def get_homes(self) -> list[Any]:
        """Return homes/groups visible to the signed-in NeoLight account."""
        result = await self._request(
            "m.life.home.space.list",
            version="1.0",
            ecode=self._ecode,
        )
        if not isinstance(result, list):
            raise NeoLightApiError("Unexpected home-list response.")
        return result

    async def get_devices(self, home_id: str) -> list[Any]:
        """Return device-list records for one account home/group."""
        try:
            gid: Any = int(home_id)
        except (TypeError, ValueError):
            gid = home_id
        result = await self._request(
            "m.life.my.group.device.list",
            {"gid": gid},
            version="2.2",
            ecode=self._ecode,
        )
        if not isinstance(result, list):
            raise NeoLightApiError("Unexpected device-list response.")
        return result

    def export_session(self) -> dict[str, Any]:
        """Export session metadata for handoff from config flow to setup."""
        if not self._sid:
            raise NeoLightAuthError("Cannot export an unauthenticated cloud session.")
        data: dict[str, Any] = {"sid": self._sid, "endpoint": self._endpoint, "login_summary": self._login_summary}
        if self._ecode:
            data["ecode"] = self._ecode
        return data

    def restore_session(self, session: dict[str, str]) -> None:
        """Restore a session established moments earlier by the config flow."""
        sid = session.get("sid")
        endpoint = session.get("endpoint")
        if not sid or not endpoint or not endpoint.startswith("https://"):
            raise NeoLightAuthError("The saved NeoLight cloud session is invalid.")
        self._sid = sid
        self._ecode = session.get("ecode")
        self._endpoint = endpoint
        summary = session.get("login_summary")
        self._login_summary = summary if isinstance(summary, dict) else {}

    @property
    def endpoint_host(self) -> str:
        """Return the configured API endpoint for safe diagnostics."""
        return self._endpoint

    @property
    def login_summary(self) -> dict[str, Any]:
        """Return sanitized metadata from the last login response."""
        return self._login_summary

    async def get_bound_locks(self, device_id: str) -> Any:
        """Probe the mobile API for locks bound to a device (diagnostic only)."""
        return await self._request("thing.m.device.bound.lock.list", {"srcDevId": device_id}, version="1.0")

    async def get_product_schema(
        self, device_id: str, product_id: str, home_id: str
    ) -> dict[str, Any]:
        """Fetch the confirmed read-only product schema endpoint."""
        action = "thing.m.device.ref.info.my.list"
        body = {"productIds": [product_id]} if product_id else {}
        try:
            result = await self._request(
                action, body or None, version="1.0", ecode=self._ecode
            )
            return {
                "product_id": product_id,
                "action": action,
                "version": "1.0",
                "result": result,
            }
        except NeoLightApiError as err:
            return {
                "product_id": product_id,
                "action": action,
                "version": "1.0",
                "error": type(err).__name__,
                "detail": str(err)[:240],
            }

    async def get_ipc_config(self, device_id: str) -> dict[str, Any]:
        """Probe the candidate IPC configuration endpoint; support is unverified."""
        action = "thing.m.ipc.config.get"
        try:
            result = await self._request(
                action, {"devId": device_id}, version="2.0", ecode=self._ecode
            )
            return {"action": action, "version": "2.0", "result": result}
        except NeoLightApiError as err:
            return {
                "action": action,
                "version": "2.0",
                "error": type(err).__name__,
                "detail": str(err)[:240],
            }

    async def get_ipc_stream_probes(self, device_id: str) -> dict[str, Any]:
        """Probe candidate stream URL actions without assuming RTSP/HLS support."""
        probes = (
            (
                "thing.m.ipc.stream.url.get",
                "1.0",
                {"devId": device_id, "type": "rtsp"},
            ),
            (
                "thing.m.ipc.stream.url.get",
                "1.0",
                {"devId": device_id, "type": "hls"},
            ),
            (
                "m.ipc.Values.get",
                "1.0",
                {"devId": device_id},
            ),
            (
                "thing.m.ipc.Live.stream.get",
                "1.0",
                {"devId": device_id},
            ),
        )
        results: dict[str, Any] = {"probes": {}}
        for action, version, body in probes:
            key = f"{action}@{version}:{body.get('type', 'default')}"
            try:
                results["probes"][key] = await self._request(
                    action, body, version=version, ecode=self._ecode
                )
            except NeoLightApiError as err:
                results["probes"][key] = {
                    "error": type(err).__name__,
                    "detail": str(err)[:240],
                }
        return results

    async def get_message_list(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """Probe the read-only message center list for doorbell/alarm events."""
        action = "thing.m.msg.list.by.json"
        body = {"offset": offset, "limit": limit}
        try:
            result = await self._request(
                action, body, version="1.0", ecode=self._ecode
            )
            return {"action": action, "version": "1.0", "result": result}
        except NeoLightAuthError:
            raise
        except NeoLightApiError as err:
            return {
                "action": action,
                "version": "1.0",
                "error": type(err).__name__,
                "detail": str(err)[:240],
            }

    @property
    def session_id(self) -> str | None:
        """Return the current session ID for the active config flow."""
        return self._sid
