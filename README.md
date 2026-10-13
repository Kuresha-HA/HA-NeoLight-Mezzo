# NeoLight MEZZO HD WF — Home Assistant

Custom Home Assistant integration research for the NeoLight MEZZO HD WF video intercom.

## Current status — experimental 0.3.1

The official NeoLight 1.1.0 APK uses a ThingSmart/ThingClips-derived mobile cloud API. The repository now contains an initial implementation of the mobile request signer, enhanced email/password login, and discovery of homes/devices.

**This has not yet been live-validated against the NeoLight account.** The email/password login uses a documented/reverse-engineered Tuya mobile flow. Phone/password login is included using inferred legacy action names and may need adjustment. The effective API host and app-specific request parameters also require a live test.

### Local signing profile required

The app's signing material is extracted from the official APK and must be supplied locally as:

`custom_components/neolight_mezzo/mobile_profile.json`

Required fields:
- `app_key`
- `app_secret`
- `cert_sha256`
- `embedded_key`
- `ttid`

Do not commit this file, publish its contents, or include it in issue reports. The integration assembles the signing key in memory. A profile generated for the exact NeoLight APK is provided separately to the project owner; it is intentionally excluded from GitHub.

## Implemented in this research version

- Mobile API HMAC-SHA256 request signing with transformed MD5 body digest.
- Enhanced email login using a one-time RSA public key.
- Experimental phone login path using analogous but not yet confirmed action names.
- EU endpoint default (`a1.tuyaeu.com`) with support for the endpoint returned by login.
- Home/location enumeration and device-list requests, enriched with per-device detail lookups.
- App-specific TTID is now taken from the locally extracted mobile profile rather than a generic guessed value.
- Unit test covering request-body signing and device-detail enrichment.
- Diagnostic sensors that snapshot discovered device count and online state at setup.
- Passwords are entered only in Home Assistant config flow; API payloads and credentials are not logged.

## Not implemented yet

- Refreshing the login session and periodically updating discovery entities.
- Door unlock, live video, and two-way audio.

The SDK's generic remote-unlock workflow has been researched but must not be invoked until authentication and the exact device/lock mapping are verified.

## Install / test

1. Install the repository as a custom integration, or copy `custom_components/neolight_mezzo` into Home Assistant.
2. Copy the separately supplied `mobile_profile.json` into that integration folder. Keep it out of Git.
3. Restart Home Assistant.
4. Add **NeoLight MEZZO** from Settings → Devices & services.
5. Enter the account email, password, and account country calling code (Ukraine: `380`).
6. Choose the login method. For phone login, enter the phone number without the country calling code, then set the country code separately.
7. Check the config-flow result and the Home Assistant log. If login fails, provide only the error code/message; do not send passwords, tokens, cookies, or request signatures.

## Research notes

- [APK research](docs/APK_RESEARCH.md)
- [APK deep dive](docs/APK_DEEP_DIVE.md)
- [Google Play APK verification](docs/GOOGLE_PLAY_APK_VERIFICATION.md)
- [Tuya mobile API findings](docs/TUYA_MOBILE_API_FINDINGS.md)
- [Follow-up SDK findings](docs/TUYA_MOBILE_API_FOLLOWUP.md)
