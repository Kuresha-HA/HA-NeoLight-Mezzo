# Google Play APK verification and SDK capability findings

Date: 2026-10-13

## APK comparison

The APKs extracted from the logged-in Google Play installation were compared with the previously extracted NeoLight APK.

- Installed package: `com.neolight.neo`
- Installed split set: `base.apk` and `split_config.arm64_v8a.apk`
- The base APK and prior `com.neolight.neo.apk` contain the same 8,389 ZIP entries.
- All nine DEX files (`classes.dex` through `classes9.dex`) are byte-for-byte identical.
- These key SDK assets are byte-for-byte identical:
  - `assets/thing_plugin_config.json`
  - `assets/thing_uni_plugins/TUNIIPCCameraManager.json`
  - `assets/thing_uni_plugins/TUNIDeviceControlManager.json`
- The binary `AndroidManifest.xml` differs, so do not claim the complete APK files are byte-for-byte identical. The code and relevant SDK configuration inspected here are identical.

SHA-256:
- Installed `base.apk`: `b4e156e5a526a246b0daa47485d1c2b344ace40f3f0224e683f872642456d7b9`
- Previously extracted APK: `86adcaf4a8d5597f02c4e4ba290407654d372caf2f0cee4cd5916056788a4da9`

## Confirmed SDK capability declarations

The bundled Tuya/ThingSmart Uni-plugin configuration declares the following methods.

### Camera / live media: `TUNIIPCCameraManager`
- `createMediaDevice(deviceId)`
- `connect(deviceId)`, `disConnect(deviceId)`
- `isConnected(deviceId)`, `isConnecting(deviceId)`
- `obtainCameraConfig(deviceId)`
- `isSupportedTalk(deviceId, extendParam)`
- `getCurrentSupportedTalkMode(deviceId, extendParam)`
- `wakeUpDoorBell(deviceId)`
- `publishDps(deviceId, dps, mode, options)`

These are SDK bridge declarations, not proof that this particular intercom supports every feature or that the methods are callable from a standalone HA integration.

### Device state and control: `TUNIDeviceControlManager`
- `getDeviceInfo(deviceId, dps)` returns fields including device ID, product ID, category, schema, DP codes, DPS, online state and attributes.
- `getDeviceListByDevIds(deviceIds)`
- `getProductInfo(productId, productVer)`
- `publishDps(deviceId, dps, mode, pipelines, options)`
- `publishCommands(deviceId, dps, mode, pipelines, options)`
- `queryDps(deviceId, dpIds, queryType)`
- `onDpDataChange` callback exposes device ID and DPS updates.

### Doorbell call events: `TUNIIPCDoorbellManager`
- `acceptDoorbellCall(messageId)`
- `refuseDoorbellCall(messageId)`
- `hangupDoorbellCall(messageId)`
- call hang-up/cancel callbacks.

### Home/device discovery
`TUNIHomeDeviceListManager` declares `getDeviceIdList`, `getRoomList`, `getShareDeviceIdList`, and related home/room device list methods.

### MQTT / generic cloud requests
- `TUNIMQTTManager.connect(taskId, host, port, userName, password, clientId, ssl)`, plus subscribe/publish and message/state callbacks.
- `TUNIAPIRequestManager.apiRequestByAtop(api, version, postData, extData)`
- `TUNIAPIRequestManager.apiRequestByHighwayRestful(host, api, header, query, body, method)`

These are generic SDK bridge interfaces. They do not reveal the app's actual login request, signing logic, cloud credentials, or MQTT topic format.

## Remote unlock status

DEX class names confirm that the SDK includes a dedicated remote-unlock workflow:
- `DoorbellRemoteUnlockBusiness`
- `DpRemoteUnlock`
- `DpRemoteUnlockRequest`
- `DpRemoteUnlockResult`
- `DpRemoteUnlockMonitor`
- `DpRemoteUnlockBluetooth`

However, the exact device-specific DP identifier/value and the workflow's authorization requirements have not yet been recovered. Do not send speculative unlock commands to the physical device.

## Next reverse-engineering target

Use JADX to inspect call sites, not only method declarations:
1. Find usages of `IThingUser.loginWithPhonePassword` and SDK initialization/configuration.
2. Inspect `DoorbellRemoteUnlockBusiness` and the `DpRemoteUnlock*` classes to recover request/response handling.
3. Trace the app's selected device ID and call path for live view / two-way audio.
4. Keep credentials, tokens, cookies and session dumps out of the repository and chat.
