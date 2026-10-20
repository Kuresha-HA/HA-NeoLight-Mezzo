# NeoLight MEZZO — Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Current Version](https://img.shields.io/badge/version-0.5.1-blue.svg?style=for-the-badge)](CHANGELOG.md)
[![HA Compatibility](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-green.svg?style=for-the-badge)](https://www.home-assistant.io)

Custom Home Assistant integration for the **NeoLight MEZZO HD WF** video intercom connected via the NeoLight / Tuya cloud account.

---

## Features

* **Doorbell Notifications:**
  * **Real-time push events:** Persistent TLS MQTT client connection (`m1.tuyaeu.com:8883`) for instantaneous ring events without polling latency.
  * **Cloud poller fallback:** Periodic polling fallback (12s interval) to prevent missed events if MQTT connection drops.
  * **Ringing sensor:** `binary_sensor.*_doorbell_ringing` with automatic 30-second reset.
  * **Last ring timestamp:** `sensor.*_last_doorbell_ring` with event metadata and caller photo URL.
  * **Event bus trigger:** Fires `neolight_mezzo_doorbell_ring` events into the Home Assistant event bus for automations.

* **Caller Photo Camera:**
  * `camera.*_caller_photo` displaying the high-resolution snapshot captured during doorbell press.
  * **Smart prefetching:** Caller photos are prefetched at ring time with a generation counter to prevent older requests from overwriting newer rings.
  * **Persistent local caching:** Stored per-device in `.storage/neolight_mezzo_snapshot_{device_id}.jpg` with a bundled default image fallback.

* **Electric Strike & Gate Control:**
  * `lock.*_door` (Lock 1, DP 148) and `lock.*_gate` (Lock 2, DP 232).
  * State-dependent dynamic icons (`mdi:door-closed` / `mdi:door-open` and `mdi:gate` / `mdi:gate-open`).
  * Automatic 5-second relocking back to secured state with proper timer cleanup.

* **Diagnostic Entities:**
  * `Online` status sensor (`sensor.*_online`).
  * `Last DP activity` timestamp sensor (`sensor.*_last_dp_activity`).
  * Raw Data Point sensors for firmware monitoring.

* **Security & Reliability:**
  * Official NeoLight APK signing keys built-in — no manual key extraction needed.
  * Automatic session re-authentication and MQTT credential refresh.
  * PII and credential sanitization in MQTT and diagnostic logging.
  * Full localization: **English**, **Ukrainian**, and **Russian** bundled.

---

## Installation

### Method 1: HACS (Recommended)
1. In Home Assistant, open **HACS** → **Integrations**.
2. Click the three dots in the top right corner and choose **Custom repositories**.
3. Add `https://github.com/Kuresha-HA/HA-NeoLight-Mezzo` with category **Integration**.
4. Click **Download**, select the latest release (`0.5.1`), and restart Home Assistant.

### Method 2: Manual Installation
1. Download the latest release archive `HA-NeoLight-Mezzo-0.5.1-final.zip` or clone the repository.
2. Copy the `custom_components/neolight_mezzo` folder into your Home Assistant `<config>/custom_components/` directory:
   ```text
   config/
   └── custom_components/
       └── neolight_mezzo/
           ├── brand/
           ├── translations/
           ├── manifest.json
           └── ...
   ```
3. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, navigate to **Settings** → **Devices & services** → **Add integration**.
2. Search for **NeoLight MEZZO**.
3. Fill in your credentials:
   * **Login method:** Email or Phone number.
   * **Username:** Email address or Phone number (without country code).
   * **Password:** Your NeoLight / Tuya account password.
   * **Country code:** Select or enter your country calling code (e.g. Ukraine `380`).
4. If your account has MFA/2FA enabled, submit the verification code sent to your email on the next step.

---

## Entities Overview

| Platform | Entity | Description |
| :--- | :--- | :--- |
| `lock` | `lock.*_door` | Main door electric strike relay (auto-relocks after 5s) |
| `lock` | `lock.*_gate` | Driveway gate relay (auto-relocks after 5s) |
| `binary_sensor` | `binary_sensor.*_doorbell_ringing` | Doorbell actively ringing (turns off after 30s) |
| `sensor` | `sensor.*_last_doorbell_ring` | Timestamp of the most recent ring event |
| `camera` | `camera.*_caller_photo` | Latest caller snapshot image |
| `sensor` | `sensor.*_online` | Intercom cloud connectivity state |
| `sensor` | `sensor.*_last_dp_activity` | Timestamp of last received Data Point update |

---

## Troubleshooting & Logs

High-volume diagnostic tracing to `NeoLite.log` is disabled to protect storage wear and avoid disk bloating. Operational logs are directed to Home Assistant's standard logging system.

To enable debug logging for this integration, add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.neolight_mezzo: debug
```

Inspect logs under **Settings** → **System** → **Logs**. Sensitive tokens, passwords, and private signing keys are automatically redacted.

---

## Research & Documentation

* [Changelog](CHANGELOG.md)
* [APK reverse engineering notes](docs/APK_RESEARCH.md)
* [APK deep dive](docs/APK_DEEP_DIVE.md)
* [Tuya mobile API findings](docs/TUYA_MOBILE_API_FINDINGS.md)
* [Follow-up SDK findings](docs/TUYA_MOBILE_API_FOLLOWUP.md)
