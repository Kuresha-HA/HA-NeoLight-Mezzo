# JADX extraction checklist

The current analysis container has the DEX files extracted but no JADX/decompiler binary, and cannot download external tools. To continue with method-level analysis, export decompiled Java/Kotlin sources from the official NeoLight APK locally.

## Open and export

1. Download JADX GUI from the official releases page: https://github.com/skylot/jadx/releases
2. Open the NeoLight APK (package `com.neolight.neo`) in JADX GUI.
3. Let all DEX files finish loading.
4. Use the global text search (not only class-name search) for the exact terms below.
5. Export all sources if practical, or provide the individual decompiled classes listed below. Do not include any account database, preferences, cookies, session tokens, or personal account data.

## Required search targets, in priority order

### Authentication / app initialization
- `loginWithPhonePassword`
- `loginWithEmail`
- `loginWithTicket`
- `TuyaHomeSdk.init` / `ThingHomeSdk.init` / SDK initialization classes
- `THING_SMART_APPKEY`, `mAppSecret`, `getRegion`, `queryDomain`
- `a1.tuyaeu.com`, `api.json`

For each result, capture the method body and the containing class. We need to know the call site and how the SDK is configured; method names alone are not enough.

### Device discovery
- implementation/call sites for `getDeviceIdList`, `getDeviceListByDevIds`, `getDeviceInfo`
- any code mapping the signed-in user to homes/rooms/devices

### Remote unlock (do not invoke)
- `com.thingclips.smart.ipc.camera.doorbellpanel.model.DoorbellRemoteUnlockModel`
- `com.thingclips.smart.camera.panelimpl.doorbell.business.DoorbellRemoteUnlockBusiness`
- `com.thingclips.smart.camera.devicecontrol.operate.dp.DpRemoteUnlock`
- `DpRemoteUnlockRequest`, `DpRemoteUnlockResult`, `DpRemoteUnlockMonitor`

We are inspecting source only. Do not trigger any unlock request during testing.

### P2P/video/audio (later milestone)
- `ThingP2PConnectionParams`
- `TUNIIPCCameraManager`
- the call sites of `obtainCameraConfig`, `createMediaDevice`, and `isSupportedTalk`

## What to return

Preferred: a ZIP of JADX's exported source tree, with private account/session data excluded. If the export is too large, send text exports of the matching methods/classes and the SDK initialization/configuration class. Do not send passwords, bearer tokens, cookies, private keys, or unredacted PCAP payloads.
