# Changelog

All notable changes to the **NeoLight MEZZO** Home Assistant integration are documented in this file.

## [0.5.1] - 2026-10-20

### Fixes & Reliability
- **Built-in Signing Profile Fallback:** Restored the official mobile signing profile as a built-in default when `mobile_profile.json` is absent, allowing zero-config onboarding.
- **Signing Profile Validation:** Added strict validation for required profile fields, raising a descriptive `NeoLightProfileError` instead of cryptic API error codes.
- **Device Registry Consistency:** Aligned sensor `DeviceInfo` with the integration's shared device-registry identity, fixing scattered entities in Home Assistant.
- **MQTT Credential Refresh:** Automatically restarts the Tuya MQTT client with refreshed credentials upon cloud-session re-authentication.
- **Caller Photo Race-Condition Fix:** Prefetches caller snapshots at ring time and employs a generation counter to prevent older concurrent downloads from overwriting newer rings.
- **Lock Relock Timer Cleanup:** Cancels previous relock handles on rapid unlock calls and properly unregisters timers on entity removal.

### Cleanup & Performance
- **Removed Unused Platform:** Removed the redundant `button.py` platform module (door/gate unlocking is managed by `LockEntity`).
- **Removed Unused Dependency:** Dropped `aiomqtt` from requirements (`paho-mqtt` is used exclusively).
- **Reduced Cloud Polling Overhead:** Increased background poll interval from 4s to 12s to protect against Tuya rate-limits while keeping real-time MQTT push active.
- **Cleaned Diagnostic Tracing:** Removed no-op diagnostic serialization and file appending to `/config/NeoLite.log`.
- **Version Synchronization:** Aligned reported runtime version with `manifest.json` (`0.5.1`).

### Packaging & UI
- **Brand Artwork:** Included official integration branding under `custom_components/neolight_mezzo/brand/` (`icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`).
- **Translations:** Added full localized strings for English, Ukrainian (`uk`), and Russian (`ru`).
- **Documentation:** Updated README with detailed installation guides, entity mappings, and logging recommendations.

---

## [0.5.0] - 2026-10-18

- Disabled creating/appending to `/config/NeoLite.log` to prevent unbounded disk growth; operational warnings and errors remain in standard Home Assistant logs.
- Documented `Door`, `Gate`, doorbell, and caller-photo entities.
- Maintained the debug repeat-ring behavior as baseline.

---

## [0.4.0] - 2026-10-17

- Real-time Tuya MQTT client push listener (`m1.tuyaeu.com:8883`).
- Doorbell ring notifications with binary sensor and event bus dispatch.
- High-resolution caller photo camera entity with disk caching.
- Electric strike lock entities with 5-second auto-relocking.
- Diagnostic sensors for cloud connectivity and firmware data points.
