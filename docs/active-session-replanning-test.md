# v0.3.7 — live schedule changes can defer charging (attended test)

In v0.3.6, a scheduled start was latched: switching from a 100% target to
a small top-up updated the displayed target but the vehicle kept charging
even when the revised window was an hour away.

**v0.3.7 behaviour:** An intentional edit to the active departure day's
battery target or ready-by time recalculates the start. If charging is no
longer needed yet, the controller requests and verifies a STOP. It then
**automatically resumes when the revised charging window opens**, provided
Active mode and the usual safety interlocks remain in force. A normal change
in vehicle battery percentage or charging power does not interrupt an
already started session. If the new target is already reached, the controller
stops for target completion. 100% completion is still vehicle managed.

## Installation

1. Save your usual weekly schedule values before temporary testing.
2. With charging stopped and Automatic charging mode Off, install v0.3.7
   from HACS and restart Home Assistant.
3. On the generated Geely EV Control Centre (Test) dashboard, confirm
   the new integration is loaded; Off is expected after a restart.
4. Confirm legacy controllers and old full-charge override are disabled,
   Public Charging Mode is OFF for this supervised home test,
   Emergency Stop OFF, Geely plug ON, Geely charging OFF.

## Test A — start immediately, then defer when target lowered

1. Enable only the correct **ready-by day**. Use a future local ready-by
   time about 60–90 minutes ahead and a 100% target while current SoC is
   clearly below 100%, so the computed start is already due.
2. Select Monitor to inspect the START decision (no command), then
   Active while physically supervising. Expect STARTING -> CHARGING
   and charging power around the normal vehicle rate.
3. Change **that same schedule** to a small top-up, for example current
   SoC + 2%, while preserving the ready-by time.
4. When the recalculated start is in the future, expect:
   - Latest Decision target and ready-by update
   - STOP_REQUESTED with reason "Schedule revised; charging not yet needed"
   - Geely charging switch OFF, power near zero, followed by STOPPED
   - WAITING, without a premature restart
5. You do **not** have to wait for the actual start time to test the rest
   of the controls: set the ready-by time closer until the revised start
   becomes due. The controller should issue a new START without needing
   Off -> Active again.
6. Verify the battery is still below target, Geely starts, then confirm
   it stops at target. After testing set controller Off and confirm 0 kW.

## Test B — no unnecessary stop when still needed

Repeat a short attended session. Move the target or ready-by time so the
recomputed window is *already open*. Expect the live target/deadline to
update while status remains CHARGING and **no new switch OFF/ON commands**.

Changing only Cool/Warm comfort preferences should refresh diagnostics
without disrupting charging; automatic climate commands remain disabled.

## Testing boundaries, reporting and recovery

- These are attended live tests; **never leave Active running unattended**.
- Public Charging Mode ON blocks integration charging commands. You must
  enable it *before* public charging; it is not a STOP control.
- An in-progress stop verification must finish before any deferred auto-resume.
- No automatic restart is authorised after Home Assistant restart until the
  user explicitly enables Active again.
- If power doesn't drop to near zero after STOP_REQUESTED, select Off and
  stop charging directly through Geely if necessary.
- Report the current battery %, scheduled target, ready-by time, Latest
  Decision status/reason, actual Geely power and whether a deferred restart
  occurred after the newly computed start became due.
- Restore original schedule values after testing.

To rollback, restore the v0.3.6 custom integration sources from commit
`97dbbe9ac36b506331565a019cf9f7401fd68a33` and restart HA.
