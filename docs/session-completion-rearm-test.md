# v0.3.6 — scheduled session completion and rearm (attended test)

This release distinguishes **completed target**, **cancelled by user/schedule**,
and **interrupted before target**. Do not leave Active charging unattended:
automatic bounded interruption recovery and restart persistence are not yet
production-ready. The Off/Monitor/Active selector is a temporary developer
test control; the finished dashboard will use normal schedule and
**Resume schedule** controls instead.

## Update

1. In HACS, update Geely Smart Charge & Climate to v0.3.6.
2. Restart Home Assistant. The automatic controller intentionally defaults to
   **Off** after startup.
3. Verify previous charge-command automations are disabled, the old
   full-charge override is Off, Public Charging Mode is **Off for this home
   test**, Emergency Stop Off, Geely plugged-in state On and Geely charging Off.

## Test 1 — cancelled 100% charge can be resumed

1. On the new test dashboard, configure one ready-by weekday (the day the
   vehicle is needed, including cross-midnight starts). Set target **100%**
   and a deadline close enough to have a calculated start time already past.
   Ensure current battery is below 100%. Disable other test days temporarily.
2. Select **Active** while supervising. Expect STARTING, CHARGING and power.
3. Select **Off**. Expect STOP_REQUESTED then STOPPED; verify Geely power
   actually falls to near zero.
4. Select **Active** again, only after STOPPED. This is the temporary
   **explicit resume** gesture. Expect a new STARTING/CHARGING because 100%
   was not achieved. The previous cancellation must not display falsely as
   COMPLETED.
5. Return to **Off** if this is only a short test, and confirm charging
   actually stops.

## Test 2 — completed 79% then new 100% request

1. Perform a short attended scheduled charge that stops at the requested
   sub-100% target (for example, 79% from 78%). Confirm STOP_REQUESTED then
   STOPPED and actual zero power.
2. Keep the scheduled weekday enabled. Change its target **upward to 100%**
   while battery is below 100%. If the window is open, expect a new
   STARTING/CHARGING command; this is a new explicit request even on the
   same departure day.
3. Moving **only the ready-by time** after reaching an unchanged target
   must **not** repeatedly restart charging. It is not a new energy request.

## Test 3 — genuine early stop must not be called COMPLETED

If Geely stops itself **below** the selected target, expect
**INTERRUPTED** followed by **PAUSED**, *not* COMPLETED.
The experimental controller must not issue repeated automatic ON commands
for the unchanged request. After examining the reason, selecting
**Off then Active** is an explicit supervised resume.

When Geely actually reaches 100% and ends charging itself, expect COMPLETED,
with no controller-issued stop merely because SoC reached 100%. A small
subsequent reported SoC drop must not create an automatic restart.

## Reporting and recovery

Report:
- Automatic charging decision status and reason
- Geely battery %, charging switch state and charging power
- Requested target and ready-by deadline
- Whether another START command was issued after a deliberate resume

If charging or stopping behaves unexpectedly, select **Off**, verify actual
Geely charging has ceased, and use Geely's own stop control if required.
Never use Public Charging Mode as a STOP button.

For rollback, restore the previous **v0.3.5 commit** from GitHub and restart
Home Assistant. Keep the prior backup of the custom integration folder.
