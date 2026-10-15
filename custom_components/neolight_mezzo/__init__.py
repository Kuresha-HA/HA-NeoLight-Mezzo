"""NeoLight MEZZO Home Assistant integration."""

from __future__ import annotations

from datetime import timedelta
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    NeoLightApiError,
    NeoLightAuthError,
    NeoLightMobileApi,
    load_profile,
)
from .cloud_data import normalize_snapshot
from .const import (
    CONF_COUNTRY_CODE,
    CONF_LOGIN_METHOD,
    CONF_PASSWORD,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]
UPDATE_INTERVAL = timedelta(minutes=5)


def _append_diagnostic_log(path: str, message: str) -> None:
    """Append a single sanitized diagnostic line without blocking the event loop."""
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now(timezone.utc).isoformat()} {message[:4000]}\n")


_SECRET_KEY_PARTS = (
    "localkey", "sid", "password", "passwd", "token", "secret",
    "authorization", "privatekey", "authkey", "credential", "psk",
    "signkey", "signingkey", "aeskey", "icepassword", "sessionid",
    "traceid",
)
_SECRET_KEY_NAMES = {"auth", "key", "sign", "signature"}


def _sanitize_diag_value(value: Any, key: str = "") -> Any:
    """Redact credentials while preserving useful device/DP structure."""
    lowered = key.casefold().replace("_", "")
    if (
        lowered in _SECRET_KEY_NAMES
        or lowered.endswith("signature")
        or any(part.replace("_", "") in lowered for part in _SECRET_KEY_PARTS)
    ):
        if "localkey" in lowered:
            return {"present": bool(value), "length": len(str(value)) if value else 0}
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize_diag_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_diag_value(item) for item in value]
    if isinstance(value, str):
        # Parse nested SDK JSON before chunking so schema strings are not clipped
        # and their individual fields still pass through secret redaction.
        if lowered in {"schema", "schemaext", "skill", "skills"} and value.startswith(("[", "{")):
            try:
                return _sanitize_diag_value(json.loads(value), "")
            except (ValueError, TypeError):
                pass
        # URLs may contain one-time stream/session tokens in query parameters.
        if value.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            try:
                parsed = urlsplit(value)
                if parsed.scheme and parsed.hostname:
                    host = parsed.hostname
                    if parsed.port:
                        host = f"{host}:{parsed.port}"
                    safe_query = urlencode(
                        [(name, "[REDACTED]") for name, _ in parse_qsl(parsed.query, keep_blank_values=True)]
                    )
                    return urlunsplit((parsed.scheme, host, parsed.path, safe_query, ""))
            except ValueError:
                return "[REDACTED_URL]"
        # Preserve long schema JSON strings; the caller chunks the serialized
        # result into bounded log records after sanitization.
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


def _summarize_device_for_diag(dev: dict[str, Any]) -> str:
    """Serialize the raw device record with secrets redacted and DP values retained."""
    record = _sanitize_diag_value(dev)
    # Add parsed views of commonly serialized SDK metadata for easier inspection.
    for key in ("skills", "meta", "schema", "dpCodes", "standSchemaModel"):
        raw = dev.get(key)
        if isinstance(raw, str) and raw:
            try:
                record[f"{key}_parsed"] = _sanitize_diag_value(json.loads(raw), key)
            except (ValueError, TypeError):
                record[f"{key}_parse"] = "not_json"
    if isinstance(dev.get("localKey"), str):
        record["localKey"] = {"present": True, "length": len(dev["localKey"])}
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


class NeoLightCloudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll current home/device metadata from the NeoLight cloud."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.entry = entry
        self.client: NeoLightMobileApi | None = None
        self._diagnostic_path = hass.config.path("NeoLite.log")
        self._bound_locks_probed: set[str] = set()
        self._schema_probed: set[str] = set()

    async def _diag(self, message: str) -> None:
        """Write sanitized diagnostic events to /config/NeoLite.log."""
        try:
            await self.hass.async_add_executor_job(
                _append_diagnostic_log, self._diagnostic_path, message
            )
        except OSError:
            _LOGGER.exception("Could not write NeoLight diagnostic log.")

    async def _diag_json_chunks(self, event: str, index: int, value: Any) -> None:
        """Log complete sanitized JSON payloads in bounded, reassemblable chunks."""
        serialized = json.dumps(
            _sanitize_diag_value(value), ensure_ascii=False, separators=(",", ":")
        )
        chunks = [
            serialized[pos:pos + 3000]
            for pos in range(0, len(serialized), 3000)
        ] or ["{}"]
        for part, chunk in enumerate(chunks, start=1):
            await self._diag(
                f"{event} index={index} part={part}/{len(chunks)} data={chunk}"
            )

    async def _new_client(self) -> NeoLightMobileApi:
        """Build a client without blocking Home Assistant's event loop on disk I/O."""
        data = self.entry.data
        profile = await self.hass.async_add_executor_job(load_profile)
        return NeoLightMobileApi(
            async_get_clientsession(self.hass),
            str(data[CONF_USERNAME]),
            str(data[CONF_PASSWORD]),
            str(data[CONF_COUNTRY_CODE]),
            profile,
        )

    async def _login(self) -> None:
        """Create an authenticated client for this account."""
        client = await self._new_client()
        await self._diag(f"AUTH_START method={self.entry.data.get(CONF_LOGIN_METHOD, 'email')}")
        _LOGGER.debug("NeoLight: starting cloud authentication.")
        if self.entry.data.get(CONF_LOGIN_METHOD) == "phone":
            await client.login_phone()
        else:
            await client.login_email()
        self.client = client
        await self._diag("AUTH_SUCCESS session_received=true")
        _LOGGER.debug("NeoLight: cloud authentication returned a session.")

    async def _fetch_snapshot(self) -> dict[str, Any]:
        """Fetch homes and devices using the active authenticated session."""
        assert self.client is not None
        _LOGGER.debug("NeoLight: requesting account homes.")
        homes_raw = await self.client.get_homes()
        await self._diag(f"HOMES_SUCCESS count={len(homes_raw)}")
        _LOGGER.debug("NeoLight: cloud returned %d home records.", len(homes_raw))
        devices_by_home: dict[str, list[Any]] = {}
        for home in homes_raw:
            if not isinstance(home, dict):
                continue
            home_id = home.get("groupId") or home.get("gid") or home.get("homeId")
            if home_id is not None:
                try:
                    raw_devices = await self.client.get_devices(str(home_id))
                    devices_by_home[str(home_id)] = raw_devices
                    await self._diag(f"DEVICES_SUCCESS home_id_present=true count={len(raw_devices)}")
                    for idx, raw_dev in enumerate(raw_devices):
                        if isinstance(raw_dev, dict):
                            detail = _summarize_device_for_diag(raw_dev)
                            chunks = [detail[pos:pos + 3000] for pos in range(0, len(detail), 3000)] or ["{}"]
                            for part, chunk in enumerate(chunks, start=1):
                                await self._diag(f"DEVICE_DETAIL index={idx} part={part}/{len(chunks)} data={chunk}")
                            device_id = raw_dev.get("devId") or raw_dev.get("id")
                            if device_id is not None and str(device_id) not in self._bound_locks_probed:
                                self._bound_locks_probed.add(str(device_id))
                                try:
                                    lock_result = await self.client.get_bound_locks(str(device_id))
                                    await self._diag(
                                        f"BOUND_LOCKS_RESULT index={idx} type={type(lock_result).__name__} data={json.dumps(_sanitize_diag_value(lock_result), ensure_ascii=False, separators=(',', ':'))[:3000]}"
                                    )
                                except NeoLightApiError as lock_err:
                                    await self._diag(f"BOUND_LOCKS_PROBE_FAILED index={idx} error={type(lock_err).__name__} detail={str(lock_err)[:300]}")
                            if device_id is not None and str(device_id) not in self._schema_probed:
                                self._schema_probed.add(str(device_id))
                                product_id = str(raw_dev.get("productId") or "")
                                schema_probe = await self.client.get_product_schema(
                                    str(device_id), product_id, str(home_id)
                                )
                                await self._diag_json_chunks("SCHEMA_PROBE", idx, schema_probe)
                                ipc_probe = await self.client.get_ipc_config(str(device_id))
                                await self._diag_json_chunks("IPC_CONFIG_PROBE", idx, ipc_probe)
                                stream_probe = await self.client.get_ipc_stream_probes(str(device_id))
                                await self._diag_json_chunks("IPC_STREAM_PROBE", idx, stream_probe)
                    _LOGGER.debug(
                        "NeoLight: cloud returned %d devices for one home.",
                        len(devices_by_home[str(home_id)]),
                    )
                except NeoLightAuthError:
                    # An expired session must escape so the caller can re-login.
                    raise
                except NeoLightApiError:
                    # A transient failure for one home should not mark every
                    # device sensor unavailable; retain other homes' results.
                    await self._diag("DEVICES_FAILED error=NeoLightApiError")
                    _LOGGER.warning(
                        "Could not refresh device list for one NeoLight home."
                    )
                    devices_by_home[str(home_id)] = []
        return normalize_snapshot(homes_raw, devices_by_home)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch a fresh snapshot, re-authenticating once if the session expired."""
        phase = "login"
        try:
            if self.client is None or not self.client.session_id:
                initial_session = self.entry.data.get("_initial_cloud_session")
                if isinstance(initial_session, dict):
                    self.client = await self._new_client()
                    self.client.restore_session(initial_session)
                    await self._diag(
                        f"SESSION_INFO endpoint={self.client.endpoint_host} meta={json.dumps(self.client.login_summary, ensure_ascii=False, separators=(',', ':'))[:2500]}"
                    )
                    _LOGGER.debug("NeoLight: reusing the session established during config flow.")
                else:
                    await self._login()
            phase = "fetching homes/devices"
            try:
                return await self._fetch_snapshot()
            except NeoLightAuthError:
                await self._diag("SESSION_REJECTED retrying_auth=true")
                _LOGGER.warning("NeoLight session was rejected while fetching data; logging in again.")
                phase = "re-authentication"
                await self._login()
                phase = "fetching homes/devices after re-authentication"
                return await self._fetch_snapshot()
        except NeoLightApiError as err:
            await self._diag(f"FAILED phase={phase} exception={type(err).__name__} detail={str(err)[:240]}")
            _LOGGER.error("NeoLight failed during %s: %s", phase, err)
            raise UpdateFailed(f"Unable to refresh NeoLight cloud data during {phase}: {err}") from err
        except (KeyError, OSError, ValueError) as err:
            await self._diag(f"FAILED phase={phase} exception={type(err).__name__}")
            raise UpdateFailed("NeoLight configuration or local mobile profile is invalid.") from err


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML (not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the cloud coordinator and its live diagnostic entities."""
    coordinator = NeoLightCloudCoordinator(hass, entry)
    await coordinator._diag("SETUP_START integration_version=0.3.8")
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        await coordinator._diag(f"SETUP_FAILED exception={type(err).__name__}")
        # Do not expose exception details; requests may include account-related data.
        raise ConfigEntryNotReady("Could not initialize the NeoLight cloud session.") from err

    # The session is transferred only to avoid an immediate duplicate login
    # during setup. Do not persist the short-lived token after it is in memory.
    if "_initial_cloud_session" in entry.data:
        cleaned_data = dict(entry.data)
        cleaned_data.pop("_initial_cloud_session", None)
        hass.config_entries.async_update_entry(entry, data=cleaned_data)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and release cached coordinator data."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
