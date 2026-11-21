# v0.3.9 — original four-tab EV Control Centre and real manual controls

**Do not install while Geely is actively charging.** Wait until Geely has
terminated the current session and actual charging power has fallen to zero,
or deliberately stop and independently verify the car is no longer charging.
HACS updates require a Home Assistant restart and can interrupt controller
state. This version is still experimental.

## Install

1. Save your existing charging schedule and take a backup of HA/Geely custom
   integration. Your original user-created YAML dashboard is not overwritten.
2. In HACS select **Geely Smart Charge & Climate → Update** to v0.3.9.
3. Restart Home Assistant after the vehicle has finished charging.
4. Open the **Geely EV Control Centre** sidebar entry. Generated four-page
   test dashboards migrate in place; customized dashboards are preserved.
5. Check **EV Control / Comfort Settings / Climate Scheduler / EX5 Stats**.
   The left side of EV Control is the vehicle summary, safety, manual charging
   and manual climate. The right side is the full seven-day charge schedule.
   This is based on the original dashboard design.
6. Verify the vehicle-specific Geely battery, charging switch, plug and
   charging power appear correctly. Tesla Wall Connector power is optional
   display data only, never required by the controller.

## Visual and read-only telemetry checks — no vehicle commands

- **EV Control:** No armed-test controls, Start test or Monitor/Active selector.
  Expect Automatic charging enabled, Public charging mode, Emergency STOP and
  release, manual target and buttons, manual climate, seven weekday deadlines.
- Switch **Automatic charging enabled OFF** while simply checking the layout.
  It will be OFF after restart even if it was on before.
- **Power discrepancy:** If Geely says 0 kW while a separately connected wallbox
  reports power, the summary can use the wallbox reading with its source
  labelled. Both measurements appear separately under Charging telemetry.
  Do not treat a Geely switch ON as verified charging power.
- **Comfort Settings:** Cool/Warm expandable profiles, temperature, seats,
  steering heating, lead/hold. Preference changes are only configuration.
- **Climate Scheduler:** Seven independent weekly slots. The UI MUST say
  simulation only. No automatic cabin commands should be issued.
- **EX5 Stats:** Battery, range, tyre/12V/vehicle telemetry and history, with
  optional charger history. No speed or climate-command buttons.

## Manual charging test — supervised, after existing charge ends

1. Confirm the old charging-command automations are disabled, the car is
   plugged in at home, Public Charging Mode OFF, Emergency Stop released,
   Geely charging switch OFF and power near zero.
2. In **Manual charge**, select a target 1–2% above current SoC. Press
   **Start chosen target** and confirm the action. Expect a real Geely START.
   Automatic charging is paused while the manual session is running.
3. Check actual Geely power or wallbox power and battery percentage.
4. Press **Stop manual**. Expect STOP_REQUESTED while verification occurs,
   then STOPPED **only after fresh Geely OFF/low-power reports and at least
   30 seconds**. Observe for another five minutes to detect delayed re-start.
   If physical charging continues, use Geely's own stop immediately.
5. Test **Resume schedule** after stop confirmation. It explicitly enables
   automatic charging, so it may schedule/start charging if due. You can
   disable the automatic switch again. **Do not leave Active unattended.**
6. Quick 80% and Quick 100% are direct manual-start shortcuts. Do not test
   them while another controller owns charging; wait for a safe stopped state.

## Manual climate test — separately, while parked

1. Only if the matching Geely climate entity is available, set **Cool**
   temperature and seat settings under **Comfort Settings**.
2. Press **Comfort Cool**. Check vehicle cabin temperature, driver/passenger
   ventilation, and steering-wheel heating in Geely. The Manual climate
   status sensor shows REQUESTED when services have been called—not proof
   the vehicle applied them.
3. Try **Comfort Warm**, then **Custom temperature ON**, and finish with
   **Climate + seats OFF**. Verify each physically. If unavailable, the
   status will say UNAVAILABLE. Existing original EVCC climate automations
   should be disabled when assessing these new manual buttons.
4. Linked climate and independent climate schedules still do not issue
   commands; their switches only save planned settings.

## Emergency stop and public charging safety

- **Emergency STOP** latches the integration emergency interlock and requests
  Geely OFF; Release emergency stop does not itself resume charging.
- **Public Charging Mode ON** intentionally suppresses ALL integration
  charging commands; it is NOT a stop control at a public charger.
- If any discrepancy between actual car power and dashboard, use the
  vehicle/Geely direct controls, leave automatic charging disabled, and
  report the Geely charging switch, power, Tesla power (if fitted), status,
  and Stop verification attributes.

## Report back

Send screenshots of EV Control and Comfort Settings, then report:
- Whether the original four-tab layout renders correctly
- Whether optional Tesla wallbox power appears alongside Geely power
- Results of the supervised manual start/stop and manual Cool/Warm buttons
- Any missing/unavailable entities, HA error messages or unexpected charging

## Known limitations / rollback

- Automatic charging switch is **not restart-persistent** in this version.
  A restart intentionally disarms it until recovery is implemented.
- Automated linked climate and seven independent climate slots are
  **configuration/simulation only**.
- Cloud telemetry may be stale. Do not equate a button request with physical
  confirmation.
- To rollback, use the v0.3.8 source at commit
  `822b31a244595fd5442e3410504376fd330d9061`, restore the backed-up
  integration files and restart HA only while the car is not charging.
  If unsure, keep automatic charging disabled and control Geely directly.
