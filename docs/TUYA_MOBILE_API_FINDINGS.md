# Tuya mobile API findings for NeoLight

Date: 2026-10-13

## New finding: the APK's Tuya signing material is statically recoverable

The installed NeoLight base APK contains the usual ThingSmart/ThingClips SDK build configuration and `assets/t_s.bmp`. The app signing certificate is also embedded in the APK signature. The Tuya mobile-API signing key can therefore be derived locally from the APK; it is not a user password or per-account token.

**Operational security:** derived key material must remain local and must never be committed, pasted into issues, or logged. No key values are recorded in this repository.

Reference implementations / reverse-engineering notes:
- https://github.com/nalajcie/tuya-sign-hacking
- https://github.com/TuyaAPI/cloud
- https://github.com/FlagX/ha-ledvance-tuya-resync-localkey/blob/535d0e2732414d39a18a0254297ce59874b2cc0a/pyscript_modules/tuya/api.py

## Request signature shape

The Tuya mobile API endpoint observed for EU apps is `https://a1.tuyaeu.com/api.json`. The app's PCAP confirms TLS to this host, but not the URL path or request body.

The established mobile API signing scheme uses:
- sorted request parameters and a fixed allowlist of fields;
- canonical segments joined with literal `||`;
- `postData` represented by a transformed MD5 digest of its JSON string;
- HMAC-SHA256 over the canonical string using the derived mobile-app signing key;
- lower-case hex digest in the reference implementation (the implementation in the target SDK must be validated against a known-good request).

Typical signed fields include `a`, `v`, `lang`, `deviceId`, `appVersion`, `ttid`, `os`, `clientId`, `postData`, `time`, `requestId`, `sid`, and `et`. Actual field values and the exact allowlist must match the SDK/app version.

## Login flow

Public reverse-engineered implementations identify the enhanced email login flow:
1. Request a one-time login token / ephemeral RSA public key with action `tuya.m.user.email.token.create`.
2. Encrypt MD5(password) with the returned RSA public key using the SDK-compatible no-padding mode.
3. Submit `tuya.m.user.email.password.login` with country/region, email, encrypted password, token and enhanced-login flags.
4. Respect any API host returned by the login response; the session may be tied to that host.

This is evidence for the email-login path only. NeoLight's SDK also exposes `loginWithPhonePassword(countryCode, phone, password, callback)`; the corresponding mobile API action/token action and the exact encrypted payload for phone login still need to be confirmed before implementing it. Do not assume email login is valid for the user's account type.

## Device discovery actions found in the SDK ecosystem

The Tuya mobile API has historically used actions such as `tuya.m.location.list`, `tuya.m.my.group.device.list`, and `tuya.m.device.get` to enumerate locations, devices and device details. These should only be used after a validated login and only after confirming they return the NeoLight user's namespace.

## Remote unlock: static evidence, not enabled

A public decompilation of the ThingClips SDK exposes the following workflow details:
- DP `ipc_db_bind_lock` represents binding a door lock to an IPC/doorbell.
- Remote unlock request DP is `unlock_request`.
- Remote unlock result DP is `remote_result`.
- The SDK business layer uses mobile API action `thing.m.device.lock.remote.host.unlock` with `srcDevId` and `destDevId`.
- Supporting lock discovery calls include `thing.m.device.bindable.lock.list` and `thing.m.device.bound.lock.list`.

Source: https://github.com/Mvdodiya001/reverse/tree/4adbf68a1f60cb76cb14ad166f8da36879f56e4f

This is generic SDK evidence from a public decompilation, not confirmation that the NeoLight MEZZO installation uses the same workflow or that a given device ID maps to the lock. No unlock command should be sent until account/device discovery and lock binding are verified. The user's first milestone remains cloud authentication and device discovery; video/audio and unlocking remain later milestones.

## Immediate engineering next step

Implement and test the mobile API signer in isolation with a local-only secret store, then verify the correct phone/email login action and EU host using a sanitized success/failure result. Only after successful login should the Home Assistant config flow store credentials/tokens and create device entities. Never add APK-derived keys or user credentials to the repository.
