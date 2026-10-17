# NeoLight MEZZO HD WF — Home Assistant

Custom Home Assistant integration research for the NeoLight MEZZO HD WF video intercom.

## Version 0.4.0

Stable integration for NeoLight MEZZO HD WF video intercom with real-time doorbell notifications, caller snapshots, and door/gate unlock controls.

### Implemented Features:

- **Doorbell Ring Notifications:**
  - Real-time Tuya MQTT client (`m1.tuyaeu.com:8883`) push listener.
  - Fast cloud message-center polling fallback (4s interval).
  - Binary sensor (`binary_sensor.*_doorbell_ringing`) with 30-second auto-reset.
  - Timestamp sensor (`sensor.*_last_doorbell_ring`) with caller message and photo URL attributes.
  - Home Assistant event bus firing (`neolight_mezzo_doorbell_ring`).

- **Caller Photo Snapshot:**
  - Camera entity (`camera.*_caller_photo`) displaying high-resolution caller snapshots from the latest ring event.
  - Persistent disk caching (`.storage/neolight_mezzo_snapshot.jpg`) and local fallback image.

- **Lock & Gate Controls:**
  - Momentary unlock buttons: `Door 1 unlock` (DP 241), `Door 2 unlock` (DP 242), and `Gate unlock` (DP 148).
  - Lock entities: `Door 1` and `Door 2` locks with automatic 5-second relocking to secured state.
  - Direct DP publish error reporting (`DEVICE_OFFLINE`).

- **Diagnostic Sensors:**
  - `Online` status sensor.
  - `Last DP activity` timestamp sensor.
  - Raw Data Point sensors for internal firmware registers: `Accessory lock state` (DP 148), `Video channel configuration` (DP 231), `Lock 2 state` (DP 232), `Doorbell 1 call status` (DP 239), `Doorbell 2 call status` (DP 240), `Door 1/2 unlock DP states` (DP 241/242).

## Install / Setup

1. Install the repository via HACS as a custom repository, or copy `custom_components/neolight_mezzo` into your Home Assistant `custom_components/` directory.
2. The official NeoLight client profile is **already built-in** — no extra files are required to get started. (Optional: an external `mobile_profile.json` can be placed in the integration folder to override credentials if needed).
3. Restart Home Assistant.
4. Add **NeoLight MEZZO** from Settings → Devices & services.
5. Enter your NeoLight app account email, password, and country code (Ukraine: `380`).
6. Choose the login method. For phone login, enter the phone number without the country calling code, then set the country code separately.
7. Check the config-flow result and the Home Assistant log. If login fails, provide only the error code/message; do not send passwords, tokens, cookies, or request signatures.

## Research notes

- [APK research](docs/APK_RESEARCH.md)
- [APK deep dive](docs/APK_DEEP_DIVE.md)
- [Google Play APK verification](docs/GOOGLE_PLAY_APK_VERIFICATION.md)
- [Tuya mobile API findings](docs/TUYA_MOBILE_API_FINDINGS.md)
- [Follow-up SDK findings](docs/TUYA_MOBILE_API_FOLLOWUP.md)
