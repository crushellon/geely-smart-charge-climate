# v0.2.0 — Attended live manual charging trial

This version makes real Geely charging ON/OFF calls **only** when explicitly
armed and a user presses **Start test** or **Stop test**. No scheduled or
climate commands are sent. The test does not control the Tesla Wall Connector.

## Prerequisites

- Park at home and connect the charger. Confirm the Geely's charger plug
  entity shows `on`, the Geely charging switch is `off`, and the optional
  charging-power sensor reads approximately 0 kW.
- Disable the **existing** EV charging controller before the trial. On the
  reference installation, set `input_boolean.ev_controller_enabled` to
  `off` and confirm `binary_sensor.ev_legacy_charging_controllers_active`
  is `off`. If any older automation can still command charging, disable it
  first. Do not disable unrelated automations.
- Confirm `input_boolean.ev_manual_full_charge`,
  `input_boolean.ev_public_charging_mode`, and
  `input_boolean.ev_emergency_stop` are all `off`. Missing legacy helpers
  are allowed on a clean installation; unavailable helpers block the trial.
- Keep the Geely vehicle connected and supervise the first short charge.
  Cloud/API delays are possible. Do not leave an unproven controller running
  unattended.

## Start with a short charge

1. In **Geely EV Control Centre (Test) → Charging & Schedule**, find
   **Live manual charging test**.
2. Set **Test battery target** to the current battery SOC + 1 percentage point
   (e.g. 72% → 73%). This is a *manual* test target, not a schedule.
3. Switch **Arm live test** on. Arming alone does not send any vehicle command.
4. Press **Start test** and accept the confirmation.
5. Check that Geely charging changes to ON and power begins flowing.
6. The controller should request OFF after the SOC reaches your test target.
   Its status remains `STOP_REQUESTED` until the car reports that it stopped.
   A failure to confirm after retries reports `ERROR`; check the car.
7. **Stop test** stops only a session this integration started. Turning off
   **Arm live test** also requests a stop for its owned session. The original
   emergency-stop helper remains an interlock.

## Fail-safe behavior and limitations

- **OFF by default** after installation, HA restart or integration reload.
- Missing plug data, unavailable battery/power, already-running charging,
  active legacy controls, public charging or emergency-stop state block starts.
- When an owned session reaches a target **below 100%**, the controller sends
  OFF and requires observed OFF / low power before reporting STOPPED.
- A 100% target has **vehicle-managed termination** and no automatic HA
  stop at SOC 100 or at the scheduled deadline; a user's explicit Stop
  or emergency stop can still cancel their test session.
- The live test does **not** manage scheduled charging or climate. Existing
  charging schedules are advisory only in this version.
- If HA or its host crashes or loses connectivity mid-charge, automatic
  monitoring is not guaranteed. **Do not leave the first sessions unattended.**
  Check charging directly in the car or Geely Connect and stop it there if needed.
- HACS upgrades/restarts during a sub-100% owned session request stop on a
  graceful unload, but only the vehicle can ultimately confirm cessation.

## Information to collect

Record `sensor.live_test_status` (especially the `message` attribute),
Geely battery %, charging switch state, plug state, and charging-power reading.
Report the sequence of values to diagnose any Geely cloud delays.
