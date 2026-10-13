# NeoLight APK research notes

Artifact: user-provided NeoLight 1.1.0 XAPK; extracted application package `com.neolight.neo.apk`.

## Confirmed findings

- The app bundles the `com.thingclips.smart` / ThingSmart SDK family.
- `assets/thing_plugin_config.json` lists `TUNIRTSPMediaManager` and `TUNIAIStreamManager`.
- `TUNIIPCCameraManager.json` exposes camera operations including `obtainCameraConfig`, `createMediaDevice`, `connect`, `isSupportedTalk`, and `publishDps`.
- `TUNIHomeDeviceListManager.json` exposes `getDeviceIdList`, `getRoomList`, `getShareDeviceIdList`, and related home/device-list listeners.
- `TUNIDeviceControlManager.json` exposes `getDeviceInfo`, `getDeviceListByDevIds`, `getProductInfo`, `publishDps`, `publishCommands`, and `queryDps`. The device info result includes fields such as `schema`, `dps`, `dpCodes`, `productId`, `isOnline`, and `isCloudOnline`.
- `TUNIAPIRequestManager.json` exposes generic bridge methods `apiRequestByAtop` and `apiRequestByHighwayRestful`. Their presence does not identify a specific API path or request signature.
- `TUNIMQTTManager.json` exposes `connect` with host/port/userName/password/clientId/ssl fields, plus subscribe/publish and message callbacks.
- `TUNIIPCDoorbellManager.json` exposes accept/refuse/hangup call methods. These are call lifecycle controls, not the remote-unlock command itself.
- DEX strings identify a dedicated remote-unlock workflow: `DoorbellRemoteUnlockModel`, `DoorbellRemoteUnlockBusiness`, `DpRemoteUnlock`, `DpRemoteUnlockRequest`, `DpRemoteUnlockResult`, and related monitor/Bluetooth classes. This proves SDK support exists in the bundle, not that the MEZZO device supports the feature or what DP/value is required.
- DEX strings include `loginWithPhonePassword`, `loginWithPhone`, `loginWithEmail`, `loginWithTicket`, and `/api.json`. These are symbols/strings only; without decompiling call sites, they do not establish the actual login sequence, request parameters, signing, or app credentials.
- The package contains encrypted/binary SDK domain resources under `assets/thing_domains_v1/regions` and `assets/thing_domains_v1/pins`; these are not readable host lists as-is.
- PCAPdroid capture on the user's emulator showed DNS and HTTPS to `a1.tuyaeu.com:443`, and DNS/TLS to `m1.tuyaeu.com:8883`. The observed TLS payload remains encrypted; no URL path, JSON body, credentials, token, or signing key was recovered.
- A quick scan of plaintext URL strings did not reveal a NeoLight-specific login host. The visible `thing.miniapp.com` URL is for the embedded mini-app framework, not evidence of the account API host.

## Not yet verified

The effective mobile login API path, app key/secret or other app parameters, selected cloud region, exact request-signing rules, token refresh, device-list HTTP endpoints, the MEZZO remote-unlock DP/schema, and the media/P2P handshake have not been established. The SDK family alone does not prove that public Smart Life credentials or Tuya's public Open API will work.

## Current reverse-engineering limitation

The DEX files have been extracted and searched for symbols, but JADX/decompiler tooling is not installed in the current analysis container and network access is unavailable to fetch it. Consequently, method implementations/call sites have not yet been decompiled. Do not mistake DEX strings or JS bridge schemas for recovered implementation logic.

## Next steps in order

1. Obtain JADX or another DEX decompiler in the analysis environment, then inspect login SDK initialization, login call sites, app/domain configuration, and token refresh.
2. Decompile `DoorbellRemoteUnlockModel`, `DoorbellRemoteUnlockBusiness`, `DpRemoteUnlock*`, and `ThingP2PConnectionParams` to establish their real request/response structures and dependencies.
3. Verify whether the login API is usable independently from Python/Home Assistant or whether the app relies on proprietary SDK signing/attestation.
4. Implement cloud authentication and device discovery only after endpoints, signing rules, and response schemas are verified.
5. Test on the user's Home Assistant instance. Credentials must be entered locally and never sent in chat or committed to GitHub.

## SDK references

- https://tuya.github.io/tuya-home-android-sdk-api-reference/index.html
- https://tuya.github.io/tuya-home-android-sdk-api-reference/com/thingclips/smart/android/user/api/package-summary.html
- https://developer.tuya.com/en/docs/cubeprivate-cloud/architecture?id=Kcmghp5d2p5wd
