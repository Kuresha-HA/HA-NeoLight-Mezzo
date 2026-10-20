"""Tuya/ThingClips mobile MQTT client for real-time doorbell ring notifications."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
from typing import Any, Callable

import paho.mqtt.client as paho_mqtt

_LOGGER = logging.getLogger(__name__)


class TuyaMqttClient:
    """Manages persistent TLS connection to Tuya Cloud MQTT broker."""

    def __init__(
        self,
        credentials: dict[str, Any],
        on_message_callback: Callable[[str, dict[str, Any]], None],
        on_log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._creds = credentials
        self._on_message = on_message_callback
        self._on_log = on_log_callback
        self._client: paho_mqtt.Client | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def _log(self, msg: str) -> None:
        """Log diagnostic message thread-safely."""
        if not self._on_log:
            return
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._on_log, msg)
        else:
            try:
                self._on_log(msg)
            except Exception:
                pass

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start the MQTT client loop in background."""
        self._loop = loop
        self._running = True
        try:
            client_id = self._creds.get("client_id", "")
            client_kwargs: dict[str, Any] = {"client_id": client_id, "protocol": paho_mqtt.MQTTv311}
            if hasattr(paho_mqtt, "CallbackAPIVersion"):
                client_kwargs["callback_api_version"] = paho_mqtt.CallbackAPIVersion.VERSION1
            self._client = paho_mqtt.Client(**client_kwargs)
            self._client.username_pw_set(
                username=self._creds.get("username", ""),
                password=self._creds.get("password", ""),
            )
            ssl_ctx = ssl.create_default_context()
            self._client.tls_set_context(ssl_ctx)

            self._client.on_connect = self._handle_connect
            self._client.on_disconnect = self._handle_disconnect
            self._client.on_message = self._handle_message

            host = self._creds.get("host", "m1.tuyaeu.com")
            port = int(self._creds.get("port", 8883))

            self._log(f"MQTT_STARTING host={host} port={port} client_id={client_id[:35]}")

            self._client.connect_async(host, port, keepalive=60)
            self._client.loop_start()
        except Exception as err:
            _LOGGER.error("Failed to start Tuya MQTT client: %s", err)
            self._log(f"MQTT_START_FAILED error={err}")

    def stop(self) -> None:
        """Stop the MQTT client loop."""
        self._running = False
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def _handle_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        """Handle MQTT connection established."""
        if rc == 0:
            topics = self._creds.get("topics", [])
            for t in topics:
                client.subscribe(t)
            safe_topics = [re.sub(r"(?i)(/mb/|/av/u/)[^/]+", r"\1[REDACTED]", str(t)) for t in topics]
            self._log(f"MQTT_CONNECTED rc={rc} subscribed_topics={safe_topics}")
        else:
            self._log(f"MQTT_CONNECT_FAILED rc={rc}")

    def _handle_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        """Handle MQTT disconnection."""
        self._log(f"MQTT_DISCONNECTED rc={rc}")

    def _handle_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handle incoming MQTT message."""
        topic = str(msg.topic)
        try:
            payload_str = msg.payload.decode("utf-8", errors="ignore")
            data = json.loads(payload_str) if payload_str.startswith("{") else {"raw": payload_str}
        except Exception:
            data = {"raw": str(msg.payload[:200])}

        safe_topic = re.sub(r"(?i)(/mb/|/av/u/)[^/]+", r"\1[REDACTED]", topic)
        self._log(f"MQTT_MSG topic={safe_topic} payload={json.dumps(_sanitize_payload(data), ensure_ascii=False)[:500]}")

        if self._loop and self._running:
            self._loop.call_soon_threadsafe(self._on_message, topic, data)


def _sanitize_payload(value: Any, key: str = "") -> Any:
    """Redact sensitive MQTT fields before diagnostic logging."""
    lowered = key.casefold().replace("_", "")
    if any(token in lowered for token in ("password", "token", "secret", "localkey", "sid", "sign", "auth", "credential", "uid", "encryptkey")):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _sanitize_payload(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(v) for v in value]
    if isinstance(value, str):
        return value[:300]
    return value
