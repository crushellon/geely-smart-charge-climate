# v0.3.5 — live schedule edit, status and comfort regression test

This is an **attended test release**. Do not leave automatic Active mode
running unattended. Do not test public charging with Public Charging Mode OFF.

## Before testing

1. Update the custom integration through HACS and restart Home Assistant.
2. On the integration's **Charging & Schedule** tab, verify **Automatic
   charging mode = Off** and the car is physically not charging.
3. Verify the old charging automations, old full-charge override and legacy
   controller are disabled. Public Charging Mode must be OFF **only while
   testing at home**. Emergency Stop must be OFF.
4. Check that the correct Geely plug sensor is ON and the Geely charging
   switch is OFF; battery percentage must be available.
5. Temporarily disable other charging schedule days. Save your usual values
   so you can restore them afterward.

## Test A — live target edit, including immediate stop

1. On the new integration test dashboard, choose the **actual day the car
   should be ready** (not the night charging starts).
2. Enable this day. Set ready-by to around 20 minutes in the future and
   target 2–3 percentage points above the current battery reading. Use a
   deadline that has not already passed. For times after midnight, use the
   **next calendar day**.
3. Select **Monitor** first. Check the Latest Decision target, ready-by
   time, and lack of real commands. Then, while present, select **Active**.
4. Confirm Geely switch ON, power rising if available, Latest Decision
   **CHARGING**, active target matching the scheduled target.
5. While charging, move the **target slider to the current battery %** (at
   or above 50%). Expect the displayed active target to change immediately
   and the controller to send STOP_REQUESTED, followed by STOPPED when Geely
   reports OFF and low power where supported. A target reduced below the
   current SoC should behave the same.
6. Ensure power has stopped physically. Put controller back to **Off**.

## Test B — schedule time and comfort editing

Use a fresh attended session in Active mode. While charging, edit the
ready-by clock time (on the **same calendar day**), and check the Latest
Decision **Current ready by** changes immediately with no duplicate START.
Switch **Cabin comfort enabled** ON, change Cool/Warm profile and change
its temperature, driver and passenger seat settings, steering heat,
lead time and hold time in **Comfort Settings**. The Latest Decision values
should update as soon as the options are saved.

**Climate is still configuration-only:** the integration must not issue
cabin-climate or seat commands from these edits yet.

Test disabling the active schedule: it should request an immediate STOP,
then verify Geely OFF. Changing the target after STOP_REQUESTED must not
cancel the pending stop or restart the session.

## Invariants and reporting

- If target = 100%, normal completion remains **vehicle managed** and the
  controller does not stop solely on seeing 100%.
- Public Charging Mode ON suppresses charging commands. Never use it as a
  manual stop when testing; choose Off and verify the vehicle stopped.
- A scheduled session already completed/cancelled for the same departure
  calendar date must not restart merely because a slider or ready-by clock
  is edited.
- If Geely remains charging when you expect STOP, use direct vehicle control,
  and report the status, target and actual power.
- If any field remains stale, report the entity attributes **active_target**,
  **scheduled_target**, **active_ready_by**, **ready_by**, **owns_automatic_session**,
  and the linked_comfort_* attributes from **Automatic charging decision**.
- Restore your original weekly charging schedule and comfort settings after
  testing. Leave Active Off until unattended use is separately proven.
