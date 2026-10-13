# NeoLight MEZZO HD WF — Home Assistant

Custom Home Assistant integration research for the NeoLight MEZZO HD WF video intercom.

## Current status — experimental 0.3.7

The official NeoLight 1.1.0 APK uses a ThingSmart/ThingClips-derived mobile cloud API. The repository now contains an initial implementation of the mobile request signer, enhanced email/password login, and discovery of homes/devices.

**The corrected request format has not yet been live-validated against the NeoLight account.** The last cloud response was `ILLEGAL_CLIENT_ID`; static analysis found that the previous implementation omitted `chKey`, used the wrong postData transport/encryption, and used an unverified embedded key. Version 0.3.6 corrects those protocol details, but only a live login can confirm cloud acceptance. The account may also require an email MFA challenge, which the current config flow reports but does not yet complete.

### Local signing profile required

The app's signing material is extracted from the official APK and must be supplied locally as:

`custom_components/neolight_mezzo/mobile_profile.json`

Required fields:
- `app_key`
- `app_secret`
- `cert_sha256` (colon-separated SHA-256 fingerprint of the APK signing certificate)
- `bmp_token` (64-character hex token derived from `assets/t_s.bmp`)
- `ttid` (raw six-character SDK flavor; retained as metadata)

The previous `embedded_key` profile format was based on an unverified extraction and is no longer accepted. The current integration computes the ThingClips `chKey` and ET=3 request signature from the correct master-key layout. Regenerate the local profile from the official APK with `tools/derive_mobile_profile.py`; it reads the existing profile and writes a corrected one without printing any key material. Example:

```bash
python tools/derive_mobile_profile.py com.neolight.neo.apk mobile_profile.json mobile_profile.fixed.json
```

Copy the corrected output to `custom_components/neolight_mezzo/mobile_profile.json` on the Home Assistant installation. Keep it private: never commit it, publish its contents, or include it in issue reports.

## Implemented in this research version

- ThingClips `chKey` generation (8-character HMAC-derived client-binding value).
- ET=3 AES-GCM request-body encryption and HMAC-SHA256 request signing using the SDK master-key layout.
- Enhanced email login using the SDK ticket flow and RSA/PKCS#1 v1.5 password encryption.
- Experimental phone login path; its exact NeoLight account behavior remains unverified.
- EU endpoint default (`a1.tuyaeu.com`) with support for the endpoint returned by login.
- Home/group and device-list discovery actions based on the ThingClips mobile API.
- The wire TTID uses the SDK's `sdk_international@<app_key>` format and the wire channel is `oem`.
- Offline tests for `chKey`, master-key assembly, ET=3 encryption, RSA password encryption, and request formatting.
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
