# v0.3.12 — Finished dashboard and honest charging state after upgrade

## Why this release exists

Previous versions kept **automatic mode** and **manual owner** as distinct
states. v0.3.11 added persistent user preference and session records, but
upgrades from v0.3.10 could not reconstruct the prior in-memory manual
session. The car could physically be charging while the new Manual charging
status displayed IDLE. A user could also see the automatic switch OFF because
the previous version never persisted that preference.

This version fixes the state display and protects a real, pre-existing charge.

## Product dashboard

The generated Geely EV Control Centre still has exactly these four tabs,
with the original two-column arrangement and the real controls only:

1. **EV Control**: battery/range/charging summary; Automatic charging enabled,
   Public charging mode, Charging session and plug; Emergency STOP/release;
   Manual target and Start chosen target / Stop manual / Quick 80% / Quick
   100% / Resume schedule; manual Cool/Warm/custom temperature/climate OFF;
   and all seven vehicle-ready departure-day schedules.
2. **Comfort Settings**: shared lead/hold and expandable Cool/Warm cabin,
   seats and steering profiles.
3. **Climate Scheduler**: one normal Current climate status card with master
   enable and next session, plus seven independent ready-by appointments.
4. **EX5 Stats**: battery/range, vehicle readings, tyre sensors, optional
   charger power, and battery/charging history charts.

No test buttons, arming selectors, Monitor/Active toggle, simulation status
panel or controller developer information on the main dashboard. Detailed
technical status remains available in HA Developer Tools → States.

## Source of truth

- **Vehicle charging status** is based on Geely charging power or Geely
  switch; optional Tesla Wall Connector power can corroborate activity when
  Geely cloud telemetry is late. The wallbox is entirely optional and
  read-only. Status may be CHARGING, CHARGING_REPORTED (switch ON, but power
  not verified), STOPPED or UNKNOWN.
- **Manual charging status** indicates the manual controller's own session;
  if the vehicle is physically charging but no owner record survives, it
  reports CHARGING_UNATTRIBUTED, not IDLE and not a fabricated manual target.
- **Automatic charging decision** remains the controller's decision. It
  distinguishes an independently observed charge as EXTERNAL and will not
  issue a stop against a charge it did not start or deliberately stop.
- Geely STOP verification now refuses to claim stopped if optional Tesla
  wallbox power remains above 0.25 kW, regardless of delayed Geely OFF/zero.
  This is corroboration only; no Tesla installation is required.

## Charging ownership and upgrade behaviour

- A manual charge running from a version that didn't persist its owner
  cannot be attributed to a particular manual target. It is observed
  read-only and left alone rather than being incorrectly stopped.
- **Start chosen target/Quick 80/Quick 100** require an eligible stopped
  vehicle; they cannot take over an already-charging unknown session.
- **Stop manual** is a genuine explicit user request and can stop an
  observed charge at home even when this running process did not start it.
  Public Charging Mode prevents this action as before. Verify physical
  charging power ceased.
- A reload or Home Assistant restart is NOT a stop command for an
  integration-owned charge. Owner and pending STOP are persisted where
  supported, so the new instance observes Geely before continuing. At
  sub-100%, lengthy HA downtime may still cause overshoot; reliable
  stop-at-target requires Home Assistant to be running.
- The **Automatic charging enabled** switch reflects the saved preference.
  It stays OFF if previously saved OFF. If an older version never saved the
  preference, there is no trustworthy way to infer it; set it ON once if
  that is your intention. It then persists over HA restarts.
- Manual charging temporarily takes precedence over automatic scheduling.
  After a verified manual stop/completion, automatic control resumes only
  if the saved preference is ON. An explicitly paused scheduled session can
  be restarted using the real **Resume schedule** button even if automatic
  charging is already enabled.
- Emergency Stop still blocks unsafe starts and release does not allow
  a new charge until any outstanding STOP has been verified.
- Vehicle-managed 100% completion and live scheduled climate functionality
  are preserved from v0.3.11.

## Installation

1. **Wait until the current charge has completed**, or verify physical zero
   power before starting the integration update. Avoid an update/restart in
   the middle of a charging session when possible.
2. Back up Home Assistant and your HACS custom component.
3. Update Geely Smart Charge & Climate to **v0.3.12** in HACS; restart HA.
4. Open the existing **Geely EV Control Centre** sidebar item. The integration
   refreshes known generated dashboards in place, but leaves custom edits
   and separately created dashboards untouched.
5. Check only the regular product controls. In **Developer Tools → States**,
   search for the newly available **Vehicle charging status** and the
   existing **Manual charging status** and **Automatic charging decision**.
   Inspect their attributes for power source, owner and active target.
6. If Automatic charging enabled is OFF, **decide explicitly** whether to
   turn it ON. Do not expect a previous unsaved Off/Active developer mode
   to be restored retroactively.

## Inspect actual features, not test buttons

For any future issue, record the state and attributes of:
- Vehicle charging status: physical charging observation and source
- Manual charging status: manual owner/target and message
- Automatic charging decision: policy, target, next start, ownership and
  stop verification
- Scheduled climate status: independent/linked session and finish time

Compare the Tesla app or vehicle's actual charging power with these
observations when Geely telemetry is late. Use **Settings → System → Logs**
and Home Assistant History to diagnose command/state timing. No special
testing controls are necessary.

## Rollback and caution

The previous v0.3.11 release remains available in GitHub, but its
migration/IDLE issue and unload-time STOP behaviour are known. If this
update malfunctions, disable automatic charging and scheduled climate,
use Geely's direct controls, and restore a Home Assistant backup or
reinstall the previous version when the car is stopped. Do not run the
old EVCC controller alongside the integration.

Automated tests cover application logic, dashboard generation and state
classifications; no code-only test can verify physical vehicle behaviour.
