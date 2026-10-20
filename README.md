# NeoLight MEZZO HD WF — Home Assistant

**Release notes:** see [CHANGELOG.md](CHANGELOG.md). Changes for each published version should also be listed in the GitHub Release notes so they are visible when Home Assistant/HACS offers an update.

Custom Home Assistant integration for the NeoLight MEZZO HD WF video intercom.

## Current development release: 0.5.1

The tested 0.5.1 package includes the following changes:

- Restored the built-in mobile signing-profile fallback when an optional local `mobile_profile.json` is not present.
- Added validation for missing or invalid signing-profile fields, with a clearer `NeoLightProfileError`.
- Aligned sensor device information with the shared device-registry identity.
- Refreshes MQTT credentials and restarts the MQTT connection after cloud-session re-authentication.
- Prefetches caller photos when a ring is detected and prevents an older concurrent download from overwriting a newer photo.
- Removed the unused button platform and the `aiomqtt` dependency; MQTT uses `paho-mqtt`.
- Removed no-op diagnostic payload serialization and synchronized the reported version with `manifest.json`.
- Added integration brand artwork: `icon.png`, `icon@2x.png`, `logo.png`, and `logo@2x.png`.
- Updated installation and troubleshooting documentation.

> **Publication status:** the repository's default branch and the published HACS release must both be updated before this version appears as an available update in HACS. The integration manifest version alone does not publish a release.

## Features

- Cloud account setup using the credentials from the NeoLight/Tuya mobile application.
- Door and gate unlock controls.
- Doorbell ringing state and last-ring information.
- Caller photo camera entity.
- Diagnostic entities for supported doorbell and device data.

## Install / setup

1. Install through HACS once a versioned GitHub release is published, or copy `custom_components/neolight_mezzo` into Home Assistant's `custom_components/` directory.
2. Restart Home Assistant.
3. Add **NeoLight MEZZO** from **Settings → Devices & services → Add integration**.
4. Sign in using the account credentials configured in the NeoLight/Tuya mobile application.

## Logging and troubleshooting

The integration does not create or append to `NeoLite.log`; high-volume diagnostic traces are disabled. Operational warnings and errors remain available in Home Assistant logs.

Open **Settings → System → Logs** and look for `custom_components.neolight_mezzo`. Do not share account passwords, session IDs, tokens, local keys, or other authentication data.

## Notes

- `Door` is the first lock; `Gate` is the gate/second lock. A separate `Door 2` entity is not created.
- `Caller photo` remains the current/latest caller-photo entity; this release does not add a ten-photo history gallery.
- The optional local signing profile is `custom_components/neolight_mezzo/mobile_profile.json`. Do not commit private credentials. The example file is `mobile_profile.example.json`.
- English, Russian, and Ukrainian translations are included under `translations/`.
