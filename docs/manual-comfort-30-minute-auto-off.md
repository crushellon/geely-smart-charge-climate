# v0.3.15 — Manual Comfort Cool/Warm/Custom: 30-minute automatic OFF

## User requirement

Manual Comfort Cool/Warm is normally pressed shortly before a drive.
The driver should **not** have to remember to press Climate + seats OFF.
A manual command must not hold `manual_climate_override` indefinitely and
prevent later scheduled departure preconditioning.

## Finished feature: no added buttons or dashboard changes

Pressing any of the **existing** EV Control buttons:
- **Comfort Cool**
- **Comfort Warm**
- **Custom temperature ON**

starts a **fresh 30-minute absolute expiry** (from the button press).
Pressing another one resets the 30-minute limit for the latest request.

At the deadline the integration issues the same Geely commands as
**Climate + seats OFF**, turning off cabin climate, both seat heat and
ventilation selectors, and heated steering wheel. Charging is untouched.
After the requests are accepted, manual climate ownership is released,
allowing later linked Cool/Warm or independent climate appointments.
The current manually superseded scheduled occurrence remains suppressed
so it cannot instantly turn climate back on.

The existing **Climate + seats OFF** button still works immediately and
cancels a running manual 30-minute timer.

## Reliability and recovery

- The absolute, timezone-aware expiry is saved to the integration config
  entry as `manual_climate_expires_at`, not reset by HA restart.
- Home Assistant schedules an exact point-in-time callback, with the
  existing 15-second periodic controller check as fallback.
- On HA restart, a still-active manual session retains the original cutoff.
  If HA was shut down past the cutoff, the integration requests OFF promptly
  upon restoring its controller.
- A manual override inherited from v0.3.14 or earlier with **no** saved
  deadline expires and requests OFF on startup, rather than blocking future
  schedules indefinitely.
- Geely cloud can fail or delay its command responses. The controller
  attempts OFF up to **three times**, spaced one minute apart when a prior
  request fails, and writes a visible error if the shutdown cannot be
  confirmed. A delayed or failed ON can still have reached Geely: the
  original auto-OFF deadline is therefore **retained**, not cancelled.
- Service acknowledgement means the HA command was submitted, **not**
  proof that cabin equipment physically turned off. Actual EX5 feedback
  must be checked. HA cannot turn off climate during a complete server
  outage, but restores the expiry once it comes back.

## Inspect real feature (no test modes)

In **Developer Tools → States → Manual climate status**, inspect the
existing sensor attributes:

- `manual_comfort_active` — true while manual climate owns the cabin
- `auto_off_after_minutes` — 30
- `manual_comfort_expires_at` — exact timestamp for automatic OFF
- `manual_comfort_seconds_remaining` — time to scheduled shutoff
- `manual_comfort_timeout_error` — most recent final failure (if any)

In **Scheduled climate status**, a manual command reports `MANUAL`;
when its 30-minute timer expires, the override should clear so next
week's/day's planned comfort can run.

## Driving precaution

This version does **not yet know whether the vehicle is moving**. An
automatic remote climate OFF request could potentially affect cabin HVAC
while you are driving. First validate auto-OFF **with the EX5 parked**,
and confirm whether the vehicle's own climate controls take precedence
once driving. Do not rely on remote HVAC during a journey for windscreen
demisting or other visibility-critical functions.

## Supervised physical acceptance

1. Install **v0.3.15** through HACS and restart Home Assistant **only when
   the car is not actively charging**.
2. Park the EX5; press the existing **Comfort Cool** button (do not alter
   charging). Check real air-conditioning and seat ventilation.
3. In Home Assistant inspect Manual climate status and its expiry timestamp.
4. If testing the 30-minute timeout, leave it alone. At the cutoff verify
   cabin, both seat settings, steering heat and manual override are OFF.
5. Repeat with Warm/Custom when convenient. Pressing another preset before
   expiry should push the deadline to 30 minutes from that later press.
6. Verify charging remains independently authorised; no climate button or
   timeout should ever send a Geely charging switch command.
7. Check scheduled climate still executes its future separate appointment.

No temporary test controls, timers, cards or new entities are added to
the original four-tab EV Control Centre dashboard.
