# Geely Smart Charge & Climate — development starter

> **Development-only. DO NOT install into Home Assistant.** This repository is the first extraction of the charging-planning logic into Python. It does not contain a working custom integration, configuration flow, or charging commands.

## Compatibility statement (proposed)

Designed for and owner-tested on a Geely EX5 with the community Geely Connect integration. Other Geely models may work if the necessary entities are exposed; compatibility is unverified. This repository's Python port has **not yet been vehicle-tested**.

## Design decisions

- Geely Connect: mandatory source of vehicle status and control. Check supported versions and entities during setup.
- Smart wall charger: optional, used for independently corroborating connection and power when present.
- Charging estimate: initially uses expected effective kW and usable battery kWh; learns percentage points/hour from sufficiently long, uninterrupted battery-percent gains.
- 100%: **vehicle-managed termination**. Do not stop, restart, or interpret the natural stop as a failed charge merely because reported power falls to zero.
- Below 100%: controller-managed completion, subject to verified state and safety checks.
- Single authority for issuing charging commands; separate observation/simulation mode while migrating.
- Never publish user-specific device IDs, mobile notification addresses, tokens or Home Assistant configuration files.

## Run first offline tests

```sh
python -m unittest discover -s tests -v
```

Only Python standard library required.

## What's included

- `src/geely_smart_charge_climate/planner.py`: pure calculations; no integration or device commands.
- `tests/test_planner.py`: test cases including vehicle-managed 100% and learned charging-rate fallback.
- `docs/architecture.md`: future integration architecture, outstanding safety requirements and staged delivery plan.
- `reference/README.md`: source reference policy; deliberately excludes private configuration.

## Next milestone

Build the Home Assistant config flow and **read-only** Geely adapter using entity selectors and strict capability checks. Add the session state machine and simulated charging-command tests *before* enabling any live charge commands. Maintain the original YAML installation untouched until a deliberate migration with rollback.
