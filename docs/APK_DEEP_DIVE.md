# NeoLight APK deep dive (2026-10-13)

APK analyzed: NeoLight 1.1.0 (`com.neolight.neo`), with primary DEX files extracted to a local analysis workspace. This note records static evidence only; it does not claim a working independent cloud client.

## Confirmed application/SDK surface

### Authentication and account

- The APK bundles the Tuya/ThingClips login SDK.
- `assets/thing_uni_plugins/TUNILoginManager.json` exposes `onTicketSuccess` and `logout`; it does not expose a plain username/password login method through this JS bridge.
- `TUNIUserInfoManager.json` exposes `getUserInfo`, including `regionCode`, `timezoneId`, and `isTemporaryUser`.
- DEX strings include `/api.json`, `loginWithPhonePassword`, and login/password UI labels. `/api.json` is a generic Tuya SDK API endpoint marker, not sufficient to identify the concrete login method, request signing, or parameters.
- The captured app traffic confirms DNS for `a1.tuyaeu.com` and HTTPS to `a1.tuyaeu.com:443`, plus TLS to `m1.tuyaeu.com:8883`. The TLS payload is encrypted; no URL path, JSON body, account token, or signing key was recovered from PCAPdroid.

### Device enumeration and state

`assets/thing_uni_plugins/TUNIHomeDeviceListManager.json` exposes:
- `getDeviceIdList` (with `ownerId`, `roomId`, `devId`; returns `devIds`)
- `getRoomList`, `getGroupIdList`, `getShareDeviceIdList`, `getShareGroupIdList`
- `getDeviceIdsInRoom`, `getDeviceIdListWithDevId`
- home-device add/remove listeners

`assets/thing_uni_plugins/TUNIDeviceControlManager.json` exposes:
- `getDeviceInfo` and `getDeviceListByDevIds`
- `getProductInfo` (including product schema and DP metadata)
- `publishDps`, `publishCommands`, `publishDpsWithPipeType`, `queryDps`
- `onDpDataChange`, `onDeviceOnlineStatusUpdate`, and MQTT message/listener methods

This gives us the likely SDK-level route for discovery and DP schema inspection, but does not reveal a stable public HTTP API for a standalone Home Assistant client.

### Camera, P2P, and talkback

`assets/thing_uni_plugins/TUNIIPCCameraManager.json` exposes:
- `obtainCameraConfig`
- `createMediaDevice`, `destroyMediaDevice`
- `connect`, `disConnect`, `isConnected`, `isConnecting`
- `isSupportedTalk`, `getCurrentSupportedTalkMode`, `wakeUpDoorBell`
- `enableAudioAEC`, `enableAudioAGC`, `enableAudioNS`
- `publishDps`

The APK DEX contains camera/P2P classes and the `ThingP2PConnectionParams` class. The XAPK includes a native ABI split (`config.armeabi_v7a.apk`); the media/P2P implementation is therefore partly native. A normal Python Home Assistant integration cannot simply invoke the Android SDK or its `.so` libraries.

### Doorbell remote unlock

The DEX contains these concrete classes/symbols:
- `com.thingclips.smart.ipc.camera.doorbellpanel.activity.DoorbellRemoteUnlockActivity`
- `com.thingclips.smart.ipc.camera.doorbellpanel.model.DoorbellRemoteUnlockModel`
- `com.thingclips.smart.camera.panelimpl.doorbell.business.DoorbellRemoteUnlockBusiness`
- `com.thingclips.smart.camera.devicecontrol.operate.dp.DpRemoteUnlock`
- `DpRemoteUnlockRequest`, `DpRemoteUnlockResult`, `DpRemoteUnlockMonitor`, `DpRemoteUnlockBluetooth`
- event/message labels `IPC_DOORBELL_REMOTE_UNLOCK`, `IPC_DOORBELL_REMOTE_UNLOCK_REQUEST`, `IPC_DOORBELL_REMOTE_UNLOCK_RESULT`, `MSG_REMOTE_UNLOCK_REQUEST`, `MSG_REMOTE_UNLOCK_RESULT`
- strings `sendRemoteUnlockCloseRequest`, `isSupportRemoteUnlockRequest`, `isSupportRemoteUnlockResult`, and `isSupportRemoteUnlockMonitor`

This proves the bundled SDK has a dedicated remote-unlock workflow. It does **not** yet establish the actual DP code/value, required request fields, whether the installed MEZZO model exposes this feature through the same path, or the confirmation semantics. Do not send test unlock commands until the request schema and device capability have been established.

### JS bridge API descriptions

The `assets/thing_uni_plugins/*.json` files describe bridge names and argument/return shapes, not the full implementation. Particularly useful files:
- `TUNIHomeDeviceListManager.json`
- `TUNIDeviceControlManager.json`
- `TUNIIPCCameraManager.json`
- `TUNIIPCDoorbellManager.json`
- `TUNILoginManager.json`
- `TUNIUserInfoManager.json`
- `TUNIAPIRequestManager.json`

`TUNIIPCDoorbellManager.json` includes `acceptDoorbellCall`, `refuseDoorbellCall`, and `hangupDoorbellCall`, each taking `messageId`. These are call-control methods, not the door-unlock command itself.

## Engineering conclusions

1. The next productive static-analysis step is to decompile `classes5.dex` and `classes6.dex` with JADX and inspect the `DoorbellRemoteUnlockModel/Business`, `DpRemoteUnlock*`, login SDK, and `ThingP2PConnectionParams` implementations.
2. For a Home Assistant integration, prioritize an independently supported cloud API/SDK or documented LAN interface. Reimplementing the Android camera/P2P stack is a separate, substantially harder task.
3. Treat account credentials and session tokens as secrets; never add captured values to this repository.
4. Keep the current integration scaffold explicit about unimplemented authentication until the actual auth exchange is understood and tested.