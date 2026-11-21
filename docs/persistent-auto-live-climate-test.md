# v0.3.11 — persistent charging and live climate: supervised test plan

## What this release changes

The user's screenshot-based four-tab EV Control Centre remains the normal UI.
The old Off / Monitor / Active selector and armed test buttons are no longer
registered as supported controls. The **Automatic charging enabled** switch is
the saved user preference and survives a restart. It pauses during an owned
manual charge and resumes after the manual charge ends, while Public Charging
Mode or Emergency Stop suppress vehicle commands. Charging sessions and
completion records are saved to avoid duplicate START after restarts.

**Charging-linked Cool/Warm** and **seven independent climate slots** now
send real Geely climate, seat and steering commands at start, followed by
climate/seat/wheel OFF at the scheduled end. Independent climate requires
neither a charge cable nor a charging schedule. Manual climate takes
priority over the current automatic appointment.

No Tesla Wall Connector connection is required for any vehicle command.
Optional wallbox telemetry is **display-only**.

## Install safely

1. Save your current charging/comfort schedule, and back up Home Assistant.
2. Ensure there is no ongoing charge and the car is actually at 0 kW, or wait
   until Geely finishes the current session before updating/restarting HA.
3. Confirm the *old* EVCC charging and automatic climate automations and
   scripts are disabled. Do not run two climate schedulers at once.
4. In HACS select **Geely Smart Charge & Climate → Update v0.3.11**.
   Restart Home Assistant.
5. Open **Geely EV Control Centre**, check the original four tabs and
   **Live climate scheduler** status on Climate Scheduler.
6. **Automatic charging enabled defaults OFF only if no previous persistent
   preference exists** (as on an upgrade from v0.3.10). Turn it ON once if
   you want automatic scheduling. The setting is thereafter remembered.
7. Check Emergency Stop is released and Public Charging Mode OFF *only for
   home charging*. At a public charger, turn Public Charging Mode ON *before*
   charging; never use it as a stop button.

## Test 1 — Saved automatic state survives a restart (no active charge)

1. With a suitable future scheduled ready-by deadline, Automatic charging
   enabled ON, and the vehicle not currently charging, confirm the
   automatic controller reports **WAITING**.
2. Restart Home Assistant while there is **no active vehicle charge**.
3. Check the Automatic charging enabled switch is still ON and the current
   controller returns to WAITING/appropriate policy, rather than Off.
4. Check no unexpected start or stop was sent and the schedule's correct
   local ready-by date and time are retained.
5. Turn Automatic charging enabled OFF deliberately, restart again and verify
   it stays OFF.

If this works, re-enable ON for the remaining tests.

## Test 2 — Manual charge and automatic resumption

1. In EV Control enable automatic charging. Confirm there is **no already
   owned scheduled session**.
2. Set Manual target 1–2% above the current SoC, and press
   **Start chosen target** or Quick 80/Quick 100 when safe to do so.
3. Check actual Geely/charger power; scheduled automatic control should
   temporarily pause, but its **Automatic charging enabled preference**
   should remain ON.
4. Let a short sub-100% manual charge reach its target OR press **Stop manual**.
   Expect STOP_REQUESTED, then fresh OFF/low-power reports and STOPPED.
5. Verify the automatic controller returns to schedule control automatically,
   **without pressing Resume schedule** and without a watchdog issuing an
   unwanted OFF for the new session. A scheduled charge may start if its
   window is due and battery is below target.
6. Repeat with automatic preference deliberately OFF: completing/stopping
   manual charge must **not** turn it ON.

## Test 3 — Emergency Stop and release

1. With automatic preference ON and **not at a public charger**, press
   Emergency STOP. Verify Geely STOP and the emergency latch.
2. The saved automatic preference stays ON but no new vehicle START may occur
   while the emergency latch is engaged.
3. Release emergency only after any pending charging STOP is verified.
4. Expect schedule control to resume when safe; release does not issue an
   unconditional START. If target is already complete, it must not restart.

## Test 4 — Independent climate (does not need plugged-in charging)

1. Park the car safely with Geely Connect available. Turn off any original
   climate automations controlling the same entities.
2. On Climate Scheduler, enable **one slot only** with the correct weekday
   and a ready-by time a few minutes in the future. Set lead to 2 minutes,
   hold to 2 minutes, cabin temperature (e.g. 22 °C), driver/passenger seats
   and steering to safe desired settings.
3. Before lead begins, expect **WAITING/IDLE** and no climate commands.
4. At ready-by minus lead, expect **STARTING → RUNNING** on Live climate
   scheduler. Inspect the real Geely climate, seats and steering settings.
5. At ready-by plus hold, expect a climate OFF command and seats/wheel OFF.
   Verify physically. Do not confuse the manual climate status with the
   separate scheduled climate status.
6. Disable the slot when finished. Verify there is no repetitive START
   within the same calendar occurrence.

## Test 5 — Charging-linked Cool/Warm

1. Set the correct **vehicle-ready day** (not charging-start night) and
   ready-by clock on EV Control. Enable that day's charging schedule and
   **Cabin comfort enabled**. Select Cool or Warm in Comfort Settings.
2. On Comfort Settings choose lead and hold, for example lead 3 minutes,
   hold 3 minutes.
3. Ensure Automatic charging enabled is ON. The linked climate schedule
   must run at the calculated start and finish independently of whether
   charging is flowing at that exact instant.
4. Validate seat heat/vent and steering wheel according to the chosen
   profile; at the end, validate climate/seat/steering Off.
5. If your ready-by time crosses midnight, configure the **departure day**,
   and check climate starts the previous calendar day if required.

## Test 6 — Climate while manual charge is actively flowing

After previous tests succeed, start one short manual charge and verify actual
power, then press Comfort Cool. The earlier controller ownership bug was fixed
in v0.3.10, but physical Geely cloud behavior needs independent confirmation.
Charging should not be cancelled by the automatic controller's prior watchdog.
Record actual power before and after and the Manual charging status.

Manual climate controls intentionally take priority and suppress the current
scheduled occurrence until the user presses **Climate + seats OFF**.
Future appointments can then run.

## Test 7 — Restart during charging (later, only after above checks)

A previously active manual or scheduled charge has a saved owner record.
On restart, the new controller should **observe** vehicle switch/power and SoC
instead of blindly sending another START. The automatic enabled preference
remains ON. Do this only during a supervised session, after validating the
safer restart-while-WAITING test. Expect a short recovery period.

## Troubleshooting and rollback

If Geely charging and dashboard disagree, use actual wallbox or vehicle
power as the deciding observation. Cloud telemetry can be stale.
If charging won't stop, use Geely/vehicle's direct controls and disable
automatic charging. If climate won't turn off, use Geely climate controls.
Do not repeatedly toggle overlapping start/stop buttons.

Report the screen's **Automatic charging decision**, **Manual charging
status**, **Scheduled climate status**, current target/SoC, actual power,
public/emergency settings, and the exact ready-by/lead/hold times.

To rollback, restore the pre-release **v0.3.10 GitHub main commit** and
Home Assistant backup. For a code rollback or error, keep automatic control
OFF and climate slots disabled until the car is safely stopped. Historical
code has known watchdog bugs and should not be used for unattended control.

**Safety scope:** Automated tests validate code state machines, not the
Geely cloud or the actual vehicle. The app is still a pre-release until
physical results establish stop confirmation, restart recovery and
preconditioning reliably.
