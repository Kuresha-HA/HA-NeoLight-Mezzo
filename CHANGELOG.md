# Changelog

## 0.5.1 — profile fallback, MQTT refresh, caller-photo race fix

### Fixes and reliability
- Restored the built-in default mobile signing profile as a fallback when `mobile_profile.json` is absent.
- Added validation for missing or invalid signing-profile fields, raising a clear `NeoLightProfileError`.
- Aligned sensor `DeviceInfo` with the device-registry identity used by other platforms.
- Restart MQTT with refreshed credentials after cloud-session re-authentication.
- Prefetch caller photos at ring time.
- Prevent an older concurrent caller-photo download from replacing a newer photo.

### Cleanup
- Removed the unused button platform module and `aiomqtt` requirement.
- Removed no-op diagnostic payload serialization.
- Synchronized the reported integration version with `manifest.json` (0.5.1).

### Packaging and documentation
- Added brand artwork to the integration package: `icon.png`, `icon@2x.png`, `logo.png`, and `logo@2x.png`.
- Updated the README and documented installation/update notes.

## 0.5.0
- Stopped creating/appending to `NeoLite.log`; high-volume diagnostic traces are disabled while operational warnings and errors remain in Home Assistant logs.
- Updated documentation for the current `Door`, `Gate`, doorbell, and caller-photo entities.
- Kept the debug7-icons repeat-ring behavior as the release baseline.
