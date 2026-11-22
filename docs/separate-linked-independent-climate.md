# v0.3.14 — Charging-linked comfort is independent from climate-only appointments

## Why

Monday's charging schedule showed **Cabin comfort enabled = ON** and Cool
configured, but Automatic charging decision reported
`linked_comfort_commands_enabled: false` because an unrelated master
switch on **Climate Scheduler** was OFF.

That master switch was intended to protect seven former simulation-only
**independent climate slots** on migration. It incorrectly disabled
charging-linked Cool/Warm too.

## The final, user-prescribed interface

- **EV Control → Monday → Cabin comfort enabled** (plus Cool/Warm choice)
  authorises Monday linked cabin preconditioning when Monday charging and
  Automatic charging are enabled.
- **Comfort Settings** defines Cool and Warm temperature, driver/passenger
  seat modes, steering wheel heating and linked lead/hold.
- **Climate Scheduler → Independent climate schedules enabled** now controls
  only the seven standalone appointments on that page. It is NOT a master
  switch for charging-linked comfort.
- No developer/test buttons, new entities, tabs or replacement controls.
  The independent master retains its existing entity unique ID, persistent
  option and location on the four-tab dashboard.

## Monday example

Monday 23 November 2026: ready by 07:00, full charge 100%, linked comfort
enabled with profile Cool; Cool 16°C; both seats Vent High; lead 20 minutes,
hold 30 minutes.

- **06:40:** send climate and seat ventilation commands if allowed
- **07:00:** cabin intended to be ready (independent of 100% charge completion)
- **07:30:** scheduled climate/seat/steering OFF

This runs with **Independent climate schedules enabled = OFF**.
Individual climate appointments on the Climate Scheduler page remain OFF.

## Still applicable

- Public Charging Mode suppresses charging-linked comfort commands.
- Emergency Stop suppresses new scheduled climate and stops owned sessions.
- A manual Comfort Cool/Warm/custom command takes priority until
  Climate + seats OFF is pressed, which releases manual climate priority.
- Saved climate occurrences are not repeatedly restarted after HA restart.
- The linked calendar day is the **ready-by/departure day**, not the
  preceding charging night.
- Automatic charging and target stop rules, including the 100% vehicle-
  controlled balancing exception, remain unchanged.

## Update / validation

1. Wait until the vehicle is not actively charging before updating and
   restarting Home Assistant.
2. Install v0.3.14 using HACS and restart HA.
3. On EV Control verify Monday charging, linked comfort and Cool selection.
   Keep Independent climate schedules enabled OFF if no independent slots
   are required.
4. In Developer Tools → States inspect **Automatic charging decision**.
   With the Monday schedule and auto enable ON, its
   `linked_comfort_commands_enabled` should be `true` even while the
   independent master is OFF.
5. Inspect **Scheduled climate status** at the linked appointment. Expect
   WAITING before lead, then RUNNING during lead/hold, then cabin OFF after
   hold. Geely commands need live confirmation on the physical EX5.

If `Scheduled climate status` reports MANUAL, an earlier explicit manual
climate command has priority. Use the existing **Climate + seats OFF**
control to release it when safe; do not add test switches.

The code has automated tests for Monday 06:40–07:30, the 16°C/Vent High
profile, independent slots remaining OFF, manual priority and existing
charging integration tests. This does **not** replace the supervised physical
Geely climate check.
