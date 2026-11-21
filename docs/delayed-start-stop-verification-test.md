# v0.3.8 — delayed Geely start after automatic OFF (attended stop verification)

**Safety:** This fixes a failure observed on a real Geely EX5. A START
request was followed almost immediately by Controller mode Off. The
controller displayed STOPPED but Geely later reported ~6.89 kW and continued
charging. Do not trust a controller STOPPED status alone; compare actual
vehicle charging switch and Geely charging power. Until testing passes,
leave Active mode disabled and stop charging directly via Geely if necessary.

## Changes

- Stop confirmation now waits at least 30 seconds after the **first** OFF
  command, with two affirmative Geely OFF/low-power observations.
- Both configured Geely sensor states must have **fresh reports after the
  stop request**. Pre-request cached values no longer prove stopping.
- If power remains on or state feedback is stale, the controller retains
  STOP_REQUESTED/ERROR and retries OFF at most three times instead of
  claiming STOPPED.
- After a verified integration-owned stop, a five-minute watchdog observes
  Geely switch/power even if testing mode is Off. If charging resumes from
  a delayed start command, it requests another OFF.
- Explicit Public Charging Mode still suppresses ALL controller OFF commands.
  A newly authorised start clears the previous cancellation watchdog.
- The test dashboard now displays **Stop verification** separately from
  Latest Decision and simulation. The observer's Monitoring label is
  unrelated to this charging-controller safety check.

## Update

1. Verify car actually stopped by Geely's own controls; if charging persists,
   use Geely's direct stop command. Do not rely on the controller's status.
2. With automatic controller Off, update Geely Smart Charge & Climate to
   v0.3.8 in HACS; restart Home Assistant.
3. Verify charging switch OFF and Geely charging power near zero, legacy
   automations disabled, Emergency Stop OFF and Public Charging Mode OFF
   **only if charging at home**.
4. Ensure the selected Geely charging-switch/charging-power sensor are
   up to date. If telemetry is stale, do not perform a live test.

## Live test A — immediate START then OFF

1. With a charged plugged-in car and no other active charging controllers,
   enable exactly one correct ready-by day, set 100%, and a deadline that
   requires immediate charging (test supervised).
2. Set **Controller mode → Active**. Confirm a Geely START and real charging
   switch/power ON. Do not leave unattended.
3. Within a few moments, set **Controller mode → Off**.
4. Expect **STOP_REQUESTED**, not premature STOPPED. The new **Stop
   verification** field should indicate fresh telemetry/settling status.
5. Observe Geely switch OFF and power near zero. After 30+ seconds and two
   fresh corroborating reports, expect **STOPPED**, with **Stop verification:
   Watching for delayed charging**.
6. Keep observing actual switch and power for at least five minutes. If a
   delayed ON/charging >0.25 kW appears in that post-stop window, expect
   another **STOP_REQUESTED** and Geely OFF. If actual charging continues,
   **stop directly through Geely**, disable Active and report immediately.

## Live test B — no false confirmation from stale cloud data

Without triggering repeated starts, monitor for telemetry delays. If Geely
switch or charging-power readings fail to update after a stop, the controller
should remain **STOP_REQUESTED** or display **ERROR / stop unverified**,
not incorrectly declare physical STOPPED. This is a fail-safe outcome;
verify the vehicle directly.

## Report

Send screenshot or text of:
- Controller mode, Latest Decision status/reason, **Stop verification**
- Geely charge switch ON/OFF and Geely charging power (kW)
- Whether power ceased, and whether it later resumed inside five minutes
- If error: stop confirmation pending and stop attempts attributes

Do not enable unattended automatic charging. Restart still disarms the
controller and this is not yet a production-safe stop mechanism.

## Rollback

The preceding v0.3.7 sources are at commit
`2c039cf0c40d4201a46f2687642096b8adc87a33`, but that build has
the **known false-STOPPED issue**. Do not return to it for unattended
automatic charging. If v0.3.8 malfunctions, set automatic mode Off,
stop directly through Geely, and leave automatic control disabled.
