# NeoLight MEZZO HD WF — Home Assistant

Custom Home Assistant integration research for the NeoLight MEZZO HD WF video intercom.

## Initial scope

The first milestone is to identify and implement the app-specific cloud authentication flow and device discovery. Remote door unlock, video streaming, and two-way audio are later milestones and are not implemented yet.

## Current status

This repository is at the research/scaffolding stage. The Android app package indicates a ThingSmart/ThingClips-derived camera stack, but the exact NeoLight cloud environment, authentication endpoints, and device-discovery protocol still need to be verified. Compatibility with the public Tuya or Smart Life login flow must not be assumed.

## Planned milestones

1. Reverse-engineer the official app's cloud environment and sign-in sequence.
2. Implement secure config flow and token handling.
3. Implement device discovery with redacted diagnostics.
4. Investigate camera session setup and P2P connectivity.
5. Investigate two-way audio and remote unlock, with explicit safety checks.

## Security

Do not commit passwords, access tokens, device identifiers, local keys, or unredacted network captures. Credentials should be stored through Home Assistant's config-entry mechanism.
