"""DataUpdateCoordinator and real-time doorbell event manager for NeoLight MEZZO."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    NeoLightApiError,
    NeoLightAuthError,
    NeoLightMobileApi,
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
    "traceid", "attachpic", "encryptkey",
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
        if lowered in {"schema", "schemaext", "skill", "skills"} and value.startswith(("[", "{")):
            try:
                return _sanitize_diag_value(json.loads(value), "")
            except (ValueError, TypeError):
                pass
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
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


def _summarize_device_for_diag(dev: dict[str, Any]) -> str:
    """Serialize the raw device record with secrets redacted and DP values retained."""
    record = _sanitize_diag_value(dev)
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
    """Poll current home/device metadata and stream real-time doorbell rings."""

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
        self._doorbell_ring_states: dict[str, dict[str, Any]] = {}
        self._cached_snapshots: dict[str, bytes] = {}
        self._last_seen_msg_time: dict[str, int] = {}
        self._mqtt_client: Any = None
        self._poll_task: Any = None
        self._streamers: dict[str, Any] = {}

        self._device_local_keys: dict[str, str] = {}
        self._default_snapshot_bytes: bytes | None = None
        self._snapshot_path = hass.config.path(".storage", "neolight_mezzo_snapshot.jpg")
        self._init_default_snapshot()

    def _init_default_snapshot(self) -> None:
        """Load persisted or bundled snapshot if available."""
        try:
            persisted = Path(self._snapshot_path)
            if persisted.is_file():
                self._default_snapshot_bytes = persisted.read_bytes()
                return
            bundled = Path(__file__).parent / "default_snapshot.jpg"
            if bundled.is_file():
                self._default_snapshot_bytes = bundled.read_bytes()
        except Exception as err:
            _LOGGER.debug("Could not read default snapshot: %s", err)

    def get_cached_snapshot(self, device_id: str) -> bytes | None:
        """Return the latest cached snapshot image bytes."""
        return self._cached_snapshots.get(device_id) or self._default_snapshot_bytes

    def set_cached_snapshot(self, device_id: str, image_bytes: bytes) -> None:
        """Cache the latest snapshot image bytes and persist to disk."""
        if image_bytes:
            self._cached_snapshots[device_id] = image_bytes
            self._default_snapshot_bytes = image_bytes

            def _save() -> None:
                try:
                    p = Path(self._snapshot_path)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(image_bytes)
                except Exception:
                    pass

            self.hass.async_add_executor_job(_save)

    def get_doorbell_ring_state(self, device_id: str) -> dict[str, Any]:
        """Return the current ringing state and last event info for a device."""
        return self._doorbell_ring_states.get(device_id, {})

    def trigger_doorbell_ring(
        self,
        device_id: str,
        event_payload: dict[str, Any],
        source: str = "cloud_message",
    ) -> None:
        """Trigger an active doorbell ringing event and schedule its auto-reset."""
        ts = event_payload.get("time") or int(datetime.now(timezone.utc).timestamp())
        iso_str = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        msg_text = str(
            event_payload.get("msgContent")
            or event_payload.get("message")
            or "Someone is ringing the doorbell"
        )
        pic_url = str(event_payload.get("attachPics") or "")

        self._doorbell_ring_states[device_id] = {
            "is_ringing": True,
            "timestamp": ts,
            "time_iso": iso_str,
            "message": msg_text,
            "picture_url": pic_url,
            "source": source,
        }

        self.hass.bus.async_fire(
            "neolight_mezzo_doorbell_ring",
            {
                "device_id": device_id,
                "timestamp": ts,
                "time_iso": iso_str,
                "message": msg_text,
                "picture_url": pic_url,
                "source": source,
            },
        )
        self.hass.async_create_task(
            self._diag(f"DOORBELL_RING_TRIGGERED devId={device_id} source={source} time={iso_str}")
        )
        self.async_update_listeners()

        def _reset_ring() -> None:
            state = self._doorbell_ring_states.get(device_id)
            if state and state.get("is_ringing"):
                state["is_ringing"] = False
                self.hass.async_create_task(
                    self._diag(f"DOORBELL_RING_RESET devId={device_id}")
                )
                self.async_update_listeners()

        self.hass.loop.call_later(30, _reset_ring)

    async def async_unlock_door(self, device_id: str, door_channel: int = 1) -> dict[str, Any]:
        """Unlock door 1 (DP 241), door 2 (DP 242), or accessory lock (DP 148)."""
        if not self.client:
            raise UpdateFailed("NeoLight cloud client is not connected.")
        dp_map = {
            1: "241",  # Door 1 Unlock
            2: "242",  # Door 2 Unlock
            3: "148",  # Accessory Lock
            4: "232",  # IPC Lock 2
        }
        dp_id = dp_map.get(door_channel, "241")
        await self._diag(f"DOOR_UNLOCK_COMMAND devId={device_id} channel={door_channel} dp={dp_id}")
        try:
            res = await self.client.publish_dps(device_id, {dp_id: True}, diag_fn=self._diag)
            await self._diag(f"DOOR_UNLOCK_RESULT devId={device_id} result={res}")
            return res
        except Exception as err:
            await self._diag(f"DOOR_UNLOCK_EXCEPTION devId={device_id} err={err!r}")
            raise

    async def start_doorbell_listener(self) -> None:
        """Start both MQTT push listener and fast cloud message poller."""
        if self.client:
            try:
                from .mqtt_client import TuyaMqttClient
                creds = self.client.get_mqtt_credentials()

                def _on_mqtt_msg(topic: str, data: dict[str, Any]) -> None:
                    devices = self.data.get("devices", []) if self.data else []
                    for dev in devices:
                        dev_id = str(dev.get("id") or "")
                        data_str = str(data).casefold()
                        if dev_id and (dev_id in data_str or "doorbell" in data_str or "ring" in data_str):
                            self.trigger_doorbell_ring(dev_id, data, source="mqtt")

                def _on_mqtt_log(msg: str) -> None:
                    self.hass.async_create_task(self._diag(msg))

                self._mqtt_client = TuyaMqttClient(creds, _on_mqtt_msg, _on_mqtt_log)
                self._mqtt_client.start(self.hass.loop)
            except Exception as err:
                await self._diag(f"MQTT_INIT_FAILED error={err}")

        if self._poll_task is None or self._poll_task.done():
            self._poll_task = self.hass.async_create_background_task(
                self._async_poll_doorbell_loop(), "neolight_mezzo_doorbell_poll"
            )

    async def stop_doorbell_listener(self) -> None:
        """Stop background doorbell monitoring tasks."""
        if self._mqtt_client:
            try:
                self._mqtt_client.stop()
            except Exception:
                pass
            self._mqtt_client = None
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            self._poll_task = None

    async def _async_poll_doorbell_loop(self) -> None:
        """Periodically check the cloud message center for new doorbell ring alerts."""
        await self._diag("DOORBELL_POLL_LOOP_STARTED interval=4s")
        while True:
            try:
                await asyncio.sleep(4)
                if not self.client:
                    await self._diag("DOORBELL_POLL_NO_CLIENT")
                    continue
                devices = self.data.get("devices", []) if self.data else []
                if not devices:
                    await self._diag("DOORBELL_POLL_NO_DEVICES")
                    continue
                for dev in devices:
                    dev_id = str(dev.get("id") or "")
                    if not dev_id:
                        continue
                    msg = await self.client.get_latest_doorbell_message(dev_id)
                    if not isinstance(msg, dict):
                        await self._diag(f"DOORBELL_POLL_MSG_NONE devId={dev_id}")
                        continue
                    msg_time = int(msg.get("time") or 0)
                    if msg_time <= 0:
                        await self._diag(f"DOORBELL_POLL_MSG_NO_TIME devId={dev_id}")
                        continue

                    last_seen = self._last_seen_msg_time.get(dev_id)
                    if last_seen is None:
                        self._last_seen_msg_time[dev_id] = msg_time
                        iso_str = datetime.fromtimestamp(msg_time, tz=timezone.utc).isoformat()
                        msg_text = str(
                            msg.get("msgContent")
                            or msg.get("message")
                            or "Someone is ringing the doorbell"
                        )
                        pic_url = str(msg.get("attachPics") or "")
                        self._doorbell_ring_states[dev_id] = {
                            "is_ringing": False,
                            "timestamp": msg_time,
                            "time_iso": iso_str,
                            "message": msg_text,
                            "picture_url": pic_url,
                            "source": "history",
                        }
                        now_ts = int(datetime.now(timezone.utc).timestamp())
                        await self._diag(
                            f"DOORBELL_INITIAL_MSG devId={dev_id} msg_time={msg_time} age_sec={now_ts - msg_time}"
                        )
                        if (now_ts - msg_time) < 60:
                            self.trigger_doorbell_ring(dev_id, msg, source="cloud_message_initial")
                        else:
                            self.async_update_listeners()
                    elif msg_time > last_seen:
                        self._last_seen_msg_time[dev_id] = msg_time
                        await self._diag(
                            f"DOORBELL_NEW_RING_DETECTED devId={dev_id} msg_time={msg_time}"
                        )
                        self.trigger_doorbell_ring(dev_id, msg, source="cloud_message")
            except asyncio.CancelledError:
                break
            except Exception as err:
                await self._diag(f"DOORBELL_POLL_ERROR error={type(err).__name__} detail={err!r}")
                _LOGGER.error("Doorbell poll loop error: %s", err)

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

    async def _new_client(self) -> Any:
        """Build a client without blocking Home Assistant's event loop on disk I/O."""
        from .api import NeoLightMobileApi, load_profile
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
        try:
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
        except Exception as err:
            import traceback
            tb = traceback.format_exc().replace("\n", " -> ")
            await self._diag(f"AUTH_FAILED error={type(err).__name__}: {err} tb={tb}")
            raise

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
                            if device_id and raw_dev.get("localKey"):
                                self._device_local_keys[str(device_id)] = str(raw_dev["localKey"])

                    _LOGGER.debug(
                        "NeoLight: cloud returned %d devices for one home.",
                        len(devices_by_home[str(home_id)]),
                    )
                except NeoLightAuthError:
                    raise
                except NeoLightApiError:
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
            await self._diag(f"FAILED phase={phase} exception={type(err).__name__} detail={err!r}")
            raise UpdateFailed(f"NeoLight configuration or local mobile profile is invalid: {err}") from err
        except Exception as err:
            import traceback
            tb = traceback.format_exc().replace("\n", " -> ")
            await self._diag(f"COORDINATOR_UPDATE_FAILED phase={phase} error={type(err).__name__}: {err} tb={tb}")
            raise UpdateFailed(f"NeoLight cloud update failed during {phase}: {err}") from err
