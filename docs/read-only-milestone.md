# Read-only integration milestone

This branch introduces a Home Assistant custom integration skeleton, **not** the production charging controller.

## Design and safety

- Select Geely Connect battery and charging switch entities, plus optional vehicle power.
- One observer-status sensor reports source availability and values.
- No charging start/stop services, no climate commands, no scheduled automation, and no EV command calls.
- Keep the existing Home Assistant YAML charge-and-climate system running; do not run two active controllers.
- EX5 is the project's only owner-tested model; other Geely models are unverified.
- Manual entity mapping is an intermediate step before integration-aware discovery and capability checks.
- The current skeleton does not enforce installation of Geely Connect; that requirement remains for the public release.

## Developer install (not yet production-ready)

Copy `custom_components/geely_smart_charge_climate` to your Home Assistant configuration, restart, then add **Geely Smart Charge & Climate** in Settings > Devices & services. Choose only entities from the Geely Connect integration. Verify that its **Observer status** entity reads `Monitoring`. No controls are created.

Do not install until this branch is reviewed; this code has not yet been tested against a live Home Assistant runtime.
