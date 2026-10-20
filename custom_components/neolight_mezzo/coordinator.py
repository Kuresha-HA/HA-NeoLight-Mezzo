"""DataUpdateCoordinator and real-time doorbell event manager for NeoLight MEZZO."""

from __future__ import annotations

import asyncio
import contextlib
import aiohttp
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any

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
DOORBELL_POLL_INTERVAL = 12


_SECRET_KEY_PARTS = (
    "localkey", "sid", "password", "passwd", "token", "secret",
    "authorization", "privatekey", "authkey", "credential", "psk",
    "signkey", "signingkey", "aeskey", "icepassword", "sessionid",
    "traceid", "attachpic", "encryptkey",
)
_SECRET_KEY_NAMES = {"auth", "key", "sign", "signature"}



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
        self._doorbell_ring_states: dict[str, dict[str, Any]] = {}
        self._ring_reset_handles: dict[str, asyncio.TimerHandle] = {}
        self._cached_snapshots: dict[str, bytes] = {}
        self._snapshot_prefetch_generation: dict[str, int] = {}
        self._last_seen_msg_time: dict[str, int] = {}
        self._mqtt_client: Any = None
        self._poll_task: Any = None
        self._streamers: dict[str, Any] = {}

        self._device_local_keys: dict[str, str] = {}
        self._default_snapshot_bytes: bytes | None = None
        self._snapshot_path = hass.config.path(".storage", "neolight_mezzo_snapshot.jpg")

    async def _async_init_snapshots(self) -> None:
        """Load default and per-device cached snapshots outside the event loop."""
        def _load() -> tuple[bytes | None, dict[str, bytes]]:
            default = None
            cache: dict[str, bytes] = {}
            bundled = Path(__file__).parent / "default_snapshot.jpg"
            try:
                if bundled.is_file():
                    default = bundled.read_bytes()
                storage = Path(self.hass.config.path(".storage"))
                for item in storage.glob("neolight_mezzo_snapshot_*.jpg"):
                    device_id = item.stem.removeprefix("neolight_mezzo_snapshot_")
                    try:
                        cache[device_id] = item.read_bytes()
                    except OSError:
                        pass
            except OSError:
                pass
            return default, cache
        self._default_snapshot_bytes, self._cached_snapshots = await self.hass.async_add_executor_job(_load)

    def get_cached_snapshot(self, device_id: str) -> bytes | None:
        """Return the latest cached snapshot image bytes."""
        return self._cached_snapshots.get(device_id) or self._default_snapshot_bytes

    def set_cached_snapshot(self, device_id: str, image_bytes: bytes) -> None:
        """Cache the latest snapshot image bytes and persist to disk."""
        if image_bytes:
            self._cached_snapshots[device_id] = image_bytes
            def _save() -> None:
                try:
                    p = Path(self.hass.config.path(".storage", f"neolight_mezzo_snapshot_{device_id}.jpg"))
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(image_bytes)
                except OSError:
                    pass
            self.hass.async_create_task(self.hass.async_add_executor_job(_save))

    async def _async_prefetch_snapshot(self, device_id: str, pic_url: str, generation: int) -> None:
        """Fetch caller image immediately, without allowing older requests to overwrite newer rings."""
        if not pic_url or not pic_url.startswith(("http://", "https://")):
            return
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(pic_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return
                image_bytes = await response.read()
            is_jpeg = image_bytes.startswith(b"\xff\xd8\xff")
            is_png = image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            if not image_bytes or not (is_jpeg or is_png):
                _LOGGER.debug("Caller snapshot response was not a JPEG/PNG for device %s", device_id)
                return
            if self._snapshot_prefetch_generation.get(device_id) != generation:
                return
            self.set_cached_snapshot(device_id, image_bytes)
            self.async_update_listeners()
        except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, OSError) as err:
            _LOGGER.debug("Could not prefetch caller snapshot for %s: %s", device_id, type(err).__name__)

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
        try:
            ts = int(event_payload.get("time") or int(datetime.now(timezone.utc).timestamp()))
            if ts > 10_000_000_000:
                ts //= 1000
        except (TypeError, ValueError):
            ts = int(datetime.now(timezone.utc).timestamp())
        previous = self._doorbell_ring_states.get(device_id, {})
        old_ts = int(previous.get("timestamp") or 0)
        msg_text = str(
            event_payload.get("msgContent")
            or event_payload.get("message")
            or "Someone is ringing the doorbell"
        )
        pic_url = str(event_payload.get("attachPics") or "")
        self._last_seen_msg_time[device_id] = max(self._last_seen_msg_time.get(device_id, 0), ts)

        # Suppress duplicate delivery of the same message, not a new press just
        # because the previous ring is still active. A different timestamp or
        # picture URL means a new event and must be registered immediately.
        old_pic_url = str(previous.get("picture_url") or "")
        same_event = (
            ts == old_ts
            and (
                pic_url == old_pic_url
                or (not pic_url and not old_pic_url)
            )
            and msg_text == str(previous.get("message") or "")
        )
        if same_event:
            return

        iso_str = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        self._doorbell_ring_states[device_id] = {
            "is_ringing": True,
            "timestamp": ts,
            "time_iso": iso_str,
            "message": msg_text,
            "picture_url": pic_url,
            "source": source,
        }
        if pic_url:
            generation = self._snapshot_prefetch_generation.get(device_id, 0) + 1
            self._snapshot_prefetch_generation[device_id] = generation
            self.hass.async_create_task(
                self._async_prefetch_snapshot(device_id, pic_url, generation)
            )

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
                self._ring_reset_handles.pop(device_id, None)
                self.async_update_listeners()

        previous_handle = self._ring_reset_handles.pop(device_id, None)
        if previous_handle:
            previous_handle.cancel()
        self._ring_reset_handles[device_id] = self.hass.loop.call_later(30, _reset_ring)

    async def async_unlock_door(self, device_id: str, door_channel: int = 1) -> dict[str, Any]:
        """Unlock the main door (DP 148) or gate (DP 232)."""
        if not self.client:
            raise UpdateFailed("NeoLight cloud client is not connected.")
        dp_map = {1: "148", 2: "232"}
        dp_id = dp_map.get(door_channel, "148")
        await self._diag(f"DOOR_UNLOCK_COMMAND devId={device_id} channel={door_channel} dp={dp_id}")
        try:
            res = await self.client.publish_dps(device_id, {dp_id: True}, diag_fn=self._diag)
            await self._diag(f"DOOR_UNLOCK_RESULT devId={device_id} result={res}")
            return res
        except Exception as err:
            await self._diag(f"DOOR_UNLOCK_EXCEPTION devId={device_id} err={err!r}")
            raise

    async def _async_restart_mqtt_client(self) -> None:
        """Restart MQTT with credentials from the current cloud session."""
        if self._mqtt_client:
            with contextlib.suppress(Exception):
                await self.hass.async_add_executor_job(self._mqtt_client.stop)
            self._mqtt_client = None
        if not self.client:
            return
        try:
            from .mqtt_client import TuyaMqttClient
            creds = self.client.get_mqtt_credentials()

            def _on_mqtt_msg(topic: str, data: dict[str, Any]) -> None:
                devices = self.data.get("devices", []) if self.data else []
                if not isinstance(data, dict):
                    return
                payload = data.get("data") if isinstance(data.get("data"), dict) else data
                dev_id = next((str(payload.get(k)) for k in ("devId", "cid", "msgSrcId", "deviceId") if payload.get(k)), "")
                if not dev_id and len(devices) == 1:
                    dev_id = str(devices[0].get("id") or "")
                if not dev_id or not any(str(d.get("id") or "") == dev_id for d in devices):
                    return
                code = str(payload.get("msgCode") or payload.get("command") or payload.get("cmd") or "").casefold()
                dps = payload.get("dps") if isinstance(payload.get("dps"), dict) else {}
                explicit = code in {"ipc_doorbell", "ac_doorbell", "doorbell", "doorbell_ring", "ring"} or any(
                    str(k) in {"136", "154", "185"} and v not in (None, False, 0, "", "0", "false")
                    for k, v in dps.items()
                )
                if explicit:
                    self.trigger_doorbell_ring(dev_id, payload, source="mqtt")

            def _on_mqtt_log(msg: str) -> None:
                _LOGGER.debug("NeoLight MQTT: %s", msg)

            self._mqtt_client = TuyaMqttClient(creds, _on_mqtt_msg, _on_mqtt_log)
            await self.hass.async_add_executor_job(self._mqtt_client.start, self.hass.loop)
        except Exception as err:
            self._mqtt_client = None
            _LOGGER.warning("NeoLight MQTT initialization failed: %s", type(err).__name__)

    async def start_doorbell_listener(self) -> None:
        """Start both MQTT push listener and fast cloud message poller."""
        await self._async_restart_mqtt_client()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = self.hass.async_create_background_task(
                self._async_poll_doorbell_loop(), "neolight_mezzo_doorbell_poll"
            )

    async def stop_doorbell_listener(self) -> None:
        """Stop background doorbell monitoring tasks."""
        if self._mqtt_client:
            try:
                await self.hass.async_add_executor_job(self._mqtt_client.stop)
            except Exception:
                pass
            self._mqtt_client = None
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        for handle in self._ring_reset_handles.values():
            handle.cancel()
        self._ring_reset_handles.clear()

    async def _async_poll_doorbell_loop(self) -> None:
        """Periodically check the cloud message center for new doorbell ring alerts."""
        await self._diag("DOORBELL_POLL_LOOP_STARTED interval=12s")
        while True:
            try:
                await asyncio.sleep(DOORBELL_POLL_INTERVAL)
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
                        continue
                    msg_time = int(msg.get("time") or 0)
                    if msg_time <= 0:
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
                        if pic_url and dev_id not in self._cached_snapshots:
                            generation = self._snapshot_prefetch_generation.get(dev_id, 0) + 1
                            self._snapshot_prefetch_generation[dev_id] = generation
                            self.hass.async_create_task(
                                self._async_prefetch_snapshot(dev_id, pic_url, generation)
                            )
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
            except NeoLightAuthError:
                _LOGGER.warning("NeoLight session expired during doorbell poll; re-authenticating.")
                try:
                    await self._login()
                    await self._async_restart_mqtt_client()
                except Exception as auth_err:
                    _LOGGER.error("NeoLight re-authentication in poll loop failed: %s", type(auth_err).__name__)
                    await asyncio.sleep(DOORBELL_POLL_INTERVAL)
            except Exception as err:
                await self._diag(f"DOORBELL_POLL_ERROR error={type(err).__name__} detail={err!r}")
                _LOGGER.error("Doorbell poll loop error: %s", err)

    async def _diag(self, message: str) -> None:
        """Compatibility no-op for high-volume diagnostic calls.

        File-based diagnostic logging was removed in version 0.5.0 to prevent
        unbounded growth of /config/NeoLite.log. Operational warnings and errors
        continue to use Home Assistant's standard logger.
        """
        return

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
            await self._diag(f"AUTH_FAILED error_type={type(err).__name__}")
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
                    for raw_dev in raw_devices:
                        if isinstance(raw_dev, dict):
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
                await self._async_restart_mqtt_client()
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
