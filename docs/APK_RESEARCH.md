# NeoLight APK research notes

Artifact: user-provided NeoLight 1.1.0 XAPK; extracted application package com.neolight.neo.apk.

## Confirmed findings

- The app bundles the com.thingclips.smart / ThingSmart SDK family.
- assets/thing_plugin_config.json lists TUNIRTSPMediaManager and TUNIAIStreamManager.
- assets/thing_uni_plugins/TUNIIPCCameraManager.json exposes camera operations including obtainCameraConfig, publishDps, and cloud playback/configuration operations.
- The package contains encrypted/binary SDK domain resources under assets/thing_domains_v1/regions and assets/thing_domains_v1/pins; these are not readable host lists as-is.
- A quick scan of plaintext URL strings did not reveal a NeoLight-specific login host. The visible thing.miniapp.com URL is for the embedded mini-app framework, not evidence of the account API host.

## Not yet verified

The effective cloud hostname/IP, NeoLight app key/secret or other app parameters, account region, exact authentication requests/signatures, and device-list API have not been established. The SDK family alone does not prove that public Smart Life credentials or Tuya's public Open API will work.

## Safe next steps

1. Trace the official app's login requests on the user's own Android device, ideally through a local HTTPS debugging proxy or Android log capture, with passwords, tokens, cookies, phone/email, and device IDs redacted before sharing.
2. Identify the SDK's app configuration and selected domain/region from the APK and runtime initialization.
3. Implement the matching auth flow and token refresh only after endpoint, signing rules, and response schema are verified.
4. Test the integration from the user's own Home Assistant instance. The user enters credentials locally; credentials must never be sent in chat or committed to GitHub.

## SDK references

- https://tuya.github.io/tuya-home-android-sdk-api-reference/index.html
- https://tuya.github.io/tuya-home-android-sdk-api-reference/com/thingclips/smart/android/user/api/package-summary.html
- https://developer.tuya.com/en/docs/cubeprivate-cloud/architecture?id=Kcmghp5d2p5wd
