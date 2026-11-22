# v0.3.13 — Hard vehicle-ready cutoff (all scheduled charges)

## The real reported problem

The Geely EX5 was plugged in on the afternoon/evening of Sunday
22 November 2026 to be ready the next day. Instead it began charging
immediately and did not stop. The user had set a previous **9:30 AM
ready-by** appointment that morning. The old controller allowed a 50–99%
session to continue up to **three hours after ready-by**, and could retain
ownership after its deadline. Worse, v0.3.12 protected *every new observed
charge* as if it had been running before Home Assistant restarted. That
bypassed the automatic policy's outside-window STOP.

## The product contract

- **50–99%:** the vehicle stops at target percentage **or ready-by,
  whichever occurs first**. There is no extra three-hour charging window.
  The 15-minute planning buffer starts charging slightly early; it does
  not extend charging beyond the ready-by time.
- **100%:** Geely terminates and balances an *already actively charging*
  scheduled session. Positive vehicle/wallbox power **observed before
  its ready-by deadline** grants that exception; on sensor-less installations,
  Geely's ON state is the available evidence. The allowance is saved
  across an HA restart. A 100% session with no evidence of genuine
  pre-deadline charging is cancelled at the deadline. Once unplugged after
  the deadline with no power, the old 100% session is cancelled; plugging
  in again that evening cannot revive its morning authorisation.
- **New charging events:** A car starting to draw power at home outside
  every valid charging window is checked and then cancelled (normal
  30-second unexpected-charge debounce and verified Geely stop), even if
  it started immediately upon plug-in.
- **Existing charge during an HA restart:** the limited recovery safeguard
  remains. An already-flowing charge present when HA starts with no owner
  metadata is marked externally observed and protected from unsolicited
  intervention. This protection is **not** transferred to every new charge
  hours later.
- **New charging inside a legitimate active window:** if the car or
  wallbox starts charging first, the automatic controller can adopt
  its current charge (no duplicate Geely START), then enforce that
  departure day's target/ready-by as normal.
- **Public Charging Mode and Emergency Stop:** existing interlocks and
  manual charging take precedence, and Tesla Wall Connector remains
  completely optional and read-only.

## Example

An 80% charge is ready by Sunday 9:30 AM. If battery is only 78% at 9:30,
Home Assistant **requests STOP at 9:30 anyway** and verifies via Geely
telemetry. When plugged in at 6:30 PM that Sunday, this morning's session
is expired: it must not automatically charge again for the missed event.
A distinct **Monday** appointment may start later that evening when the
calculated Monday window actually opens.

For a 100% target ready at Sunday 9:30, the car may finish balancing
after that time only if charging was confirmed *before* 9:30 and the same
session remains connected. Plugging in Sunday evening does not start
or revive the missed morning 100% charge.

## What was tested

- Deadline enforced at exactly ready-by on an owned, sub-100% session
- STOP recorded as **expired**, not falsely completed
- Morning charge not restarted by an afternoon plug-in
- Delayed 100% start with no predeadline proof cancelled
- Genuine 100% flowing before cutoff continues after cutoff
- Post-cutoff unplug terminates the 100% exception
- HA restart with expired sub-100% or unconfirmed 100% session triggers
  a stop instead of a 90-second late-start grace
- An in-window charge that starts directly in the vehicle is adopted
  without a second START
- Only a pre-existing *startup* charge receives upgrade protection;
  new afternoon plug-ins do not
- The existing tests for manual handoffs, stop telemetry freshness,
  emergency/public mode and four-tab dashboard still run

## Home Assistant installation and verification

Update to **v0.3.13** in HACS **when the vehicle has safely stopped charging**,
restart Home Assistant and use only the normal dashboard. Keep legacy EV
charging automations disabled.

Set the actual *vehicle-ready calendar day* and ready-by time. Under
**Developer Tools → States**, inspect these existing entities by name:
**Automatic charging decision**, **Vehicle charging status**, **Manual charging
status**. The automatic decision attributes show target, deadline, owner,
last action and stop verification. Vehicle charging status shows Geely and
optional Tesla corroborating power. The completed session record now has
the **expired** outcome when a deadline forced a stop.

**Safety:** If power continues when Home Assistant says STOP_REQUESTED,
stop directly through the Geely car/app, turn Automatic charging OFF, and
inspect power and controller states. Automated tests cannot verify the
physical Geely cloud outcome.

**No new dashboard, test buttons, modes or controls.** The user-prescribed
four-tab dashboard and real controls are unchanged.
