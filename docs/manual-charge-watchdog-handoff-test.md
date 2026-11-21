# v0.3.10 — Manual charging ownership handoff (attended safety test)

## Confirmed root cause

The user observed that pressing Comfort Cool appeared to stop a running manual
charge. A Geely charging-controller notification said:

> Charging stopped and verified: Charging resumed after verified stop; enforcing cancellation

That exact message is emitted by the **automatic controller's five-minute
post-STOP watchdog**, not by the climate code. A previous scheduled charge had
been stopped and verified; a new authorised manual charge started during its
watch window. The old automatic watchdog saw charging again, mistook it for
a cancelled session's delayed rebound, and sent **Geely switch.turn_off**.

## Code fix

- Manual START now transfers ownership while holding the manual and automatic
  controller locks, cancelling the *prior automatic stop watchdog* only after
  positive manual start preflight and a check that no automatic stop is pending.
- Automatic watchdog independently recognises **manual.owned** as a valid new
  session and releases its previous watch without issuing OFF.
- An unauthorised rebound with **no manual owner** must still cause an OFF
  request; public charging mode still blocks Geely commands.
- Failed/unplugged manual starts do **not** cancel the prior watch.
- This does not modify actual Cool/Warm commands; a separate physical
  test must establish that Geely accepts manual climate while AC charging.

## Installation

1. **Wait until charging has stopped** and independently verify the vehicle
   is not drawing power. Never restart HA during a charging session.
2. Back up HA or your installed custom component.
3. In HACS update **Geely Smart Charge & Climate** to **v0.3.10**.
4. Restart Home Assistant. The automatic charging switch will default OFF.
5. Check old charging automations remain disabled. At home, Public Charging
   Mode should be OFF and Emergency STOP released.

## Test A — prior automatic STOP followed by genuine manual charge

Perform only while present, watching both vehicle and charger:

1. Use a small scheduled top-up to a reachable sub-100% target, and confirm
   Geely starts, then stops at target. Observe **STOP_REQUESTED → STOPPED**.
2. **Within five minutes** of that verified stop, press Manual charge →
   **Start chosen target**, selecting a **new target above current SoC**.
   Wait until the preceding automatic STOP really is verified before trying.
3. Expect the new manual charge to be authorised, charging power to rise,
   and the **automatic charging controller NOT to send another OFF**.
4. Leave charging for a short supervised interval; check no new notification
   with text "Charging resumed after verified stop; enforcing cancellation".
5. Press **Stop manual**, verify power falls to zero and status becomes
   STOPPED only after valid post-command Geely telemetry. Don't reactivate
   the automatic schedule unintentionally via Resume schedule.

## Test B — Comfort Cool during a legitimate manual charge

1. Repeat the approved manual charging start with a target above current SoC.
2. Once actual charging power is stable, press **Comfort Cool**.
3. Compare physical charging current/power and state **before and after**;
   Geely cloud telemetry can be delayed. Confirm seat and cabin commands
   independently.
4. If charging stops, capture the Manual charging status message, Automatic
   charging decision, Geely charging switch, Geely power, and optional Tesla
   power. If another OFF command was issued, inspect HA traces/logbook.
5. Press **Climate + seats OFF** after evaluating, then **Stop manual**
   to end the charging test safely.

## Interpretation

- No new automatic-watchdog notification and charging continues means the
  *known controller ownership bug* is likely resolved.
- No watchdog notification but actual charging stops when climate activates
  means investigate the **Geely API or vehicle** interaction separately.
- A new watchdog notification or unsolicited OFF means the fix failed:
  stop testing, disable automatic charging and control the vehicle directly.

## Limitations and rollback

The release is **not yet physically validated**, and automatic climate
schedules and restart recovery are not enabled. Prior v0.3.9 source:
`f41a85dc28baa876c7dbad44c74a5fc4ece3b5a8`, but it contains the known
ownership bug; rollback should be used only with auto and manual integration
charging disabled until the issue is resolved.
