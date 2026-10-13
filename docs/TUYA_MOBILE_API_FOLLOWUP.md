# Follow-up: APK-derived SDK profile and concrete SDK actions

Date: 2026-10-13

## APK static profile check

A local DEX parser located `com.thingclips.sample.BuildConfig` in `classes3.dex` and verified that `THING_SMART_APPKEY`, `THING_SMART_SECRET`, and `THING_SMART_TTID` are compiled into the APK. The key and secret conform to the SDK's expected 20-character and 32-character formats. `assets/t_s.bmp` is present, and the APK signing certificate SHA-256 can be read locally. The BMP token and mobile signing key were derived locally for analysis; their values are intentionally not recorded or committed.

This establishes that the static inputs for the mobile API signature are available. It does not validate a live request or prove that the app's endpoint, action version, and parameter set are correct for NeoLight.

## Remote unlock SDK workflow, refined from public decompiled source

The ThingClips SDK's generic remote-unlock business layer contains:
- `thing.m.device.bindable.lock.list` — list bindable locks for `srcDevId`;
- `thing.m.device.bound.lock.list` — list locks already bound to `srcDevId`;
- `thing.m.device.lock.remote.host.unlock` — request remote unlock with `srcDevId` and `destDevId`;
- `thing.m.device.bind` — bind a lock, using `srcDevId` and `targetDevIds`.

The DP operators expose:
- `ipc_db_bind_lock` for the lock-binding DP;
- `unlock_request` for the remote-unlock request;
- `remote_result` for the response.

Reference: https://github.com/Mvdodiya001/reverse/tree/4adbf68a1f60cb76cb14ad166f8da36879f56e4f

These are source-level SDK findings from a separate public decompilation and must be confirmed against the NeoLight APK before any command is issued. Do not call the unlock action during cloud-authentication tests.

## Authentication status

The mobile-app signature derivation is now understood well enough to implement in isolation, but no authenticated request has yet been validated against the user's NeoLight account. The remaining unknowns are the exact login path for the account's login identifier (email vs phone), its enhanced-login action/payload, and the effective endpoint/parameters returned by the SDK. The official app's API traffic remains encrypted in the existing PCAP capture.


## DoorbellTuya comparison (2026-10-13)

Reviewed https://github.com/nihatds100/DoorbellTuya. Its authentication uses the Smart Life web-account endpoint family on regional `protect-*.ismartlife.me` hosts, not the NeoLight mobile API. The user has explicitly confirmed that NeoLight uses a separate account system and is incompatible with Smart Life. Therefore **do not implement, probe, or offer Smart Life web login as a NeoLight authentication path**. This project is useful only as general background on Tuya/ThingClips camera architecture; its authentication and account/device discovery flow are out of scope for NeoLight.

The DoorbellTuya code is licensed PolyForm Noncommercial 1.0.0 (its separately retained third-party bridge sources have their own licenses). Its camera pipeline is a Go WebRTC-to-RTSP bridge and is not directly reusable as a native Python mobile-SDK integration.

The active investigation remains the NeoLight APK's own ThingClips SDK, its mobile API request signature/metadata, the `ILLEGAL_CLIENT_ID` response, and the correct NeoLight account/device discovery flow. Do not test Smart Life endpoints or send any remote-unlock command.
