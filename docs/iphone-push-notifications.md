# v0.3.16 — Real iPhone push notifications for all EV controls

## Delivery

The integration uses **Home Assistant's iPhone Companion App push service**:
`notify.mobile_app_tims_iphone`. That is the same service previously used
by the owner's working automations. This calls the actual `notify` service
with `title` and `message` — **not** just
`persistent_notification.async_create` (Home Assistant inbox).

The default service can be overridden through the integration config entry
option `phone_notification_service` if the Companion App ever renames it.
The normal four-tab dashboard is **unchanged** and no test controls are
added. Events are deduplicated and recent delivered IDs persist over a
Home Assistant restart to prevent repeated notification floods.

If the service is missing/declines a push, a warning appears in Home
Assistant notifications and logs. It is not falsely recorded as sent;
the same event is not attempted on every 15-second controller tick.

## Automatic charging notifications

**Charging START** is pushed after Geely/Tesla actually reports fresh
positive charging power (or fresh Geely switch ON where power telemetry
is unavailable), not just when HA sends the start service request.

It includes:
- source battery percentage (captured when charging was authorised)
- current observed battery percentage
- target 80%, 100% or the configured value
- ready-by **calendar day and time**, not the start-night label

Example format:
> Geely automatic charging started — Monday automatic charging power confirmed
> at 41%. Started at 41%; target 100%. Ready by Mon 23 Nov, 07:00 AM.

**Charging FINISHED** is pushed when Geely reports ended/completed or
the automatic controller verifies its own stop. It includes actual end SoC,
whether the target was achieved, original target and deadline, reason
(target, deadline, interruption or safety request), and an **estimated**
battery kWh gained from the SoC difference × 68.39 kWh usable capacity.
This is an estimate of energy stored, **not** measured charger/grid kWh.
When SoC was not available, energy is reported as unavailable.

For a 50–99% scheduled charge that reaches its **ready-by hard stop**
below target, the message explicitly says **Target not reached**.

Unexpected charging, stop requests, automatic interruptions, and
unconfirmed stop failures also generate actionable phone warnings.
Manual or emergency intervention against an unattributed session
generates a separate verified-stop push when actual STOP evidence arrives.

## Manual charge and cabin comfort

- **Start chosen target / Quick 80% / Quick 100%**:
  notification after charging is actually observed, with starting SoC and
  requested target. A blocked start is reported as blocked.
- **Stop manual**: sends a STOP-requested notification followed by
  STOPPED or interrupted/complete notification once Geely feedback
  confirms it, with start/end SoC and estimated kWh. Any retry failure
  or unconfirmed STOP is pushed as a warning. Public Charging Mode
  blocks an integration STOP and says so rather than claiming success.
- **Comfort Cool / Warm / Custom**: reports the selected preset,
  temperature and seats/steering where configured, along with the
  existing automatic 30-minute OFF expiry. Geely's cloud acceptance is
  distinguished from *vehicle-reported* climate state.
- **Climate + seats OFF**: reports command acceptance/readback.
- **Manual comfort 30-minute timeout**: pushes once on OFF commands being
  accepted for cabin, seats and steering; pushes a failure if OFF is
  unconfirmed after the maximum three attempts.

## Switches, safety and schedules

Any persisted real ON/OFF change is pushed once, including:
- Automatic charging enabled/disabled
- Emergency STOP engaged/released (latch change is not falsely labelled
  as physically stopped before charging confirmation)
- Public Charging Mode ON/OFF
- Each charging departure day ON/OFF
- Each day's charging-linked cabin comfort ON/OFF
- Seven independent climate slots ON/OFF
- Independent climate schedules master ON/OFF
- The Cool/Warm and climate-slot steering heat options ON/OFF

Visual-only Show Cool/Warm Settings expanders and every transient sensor
tick do **not** generate phone spam. The unchanged dashboard remains the
normal user interface.

## Scheduled climate events

Every independent or charging-linked session sends a notification after
the actual Geely climate/seat request sequence succeeds, with temperature,
driver/passenger seat settings, steering choice, and ready-by time.

At its configured end, it sends a separate OFF-event notification and
labels the result as vehicle-reported OFF or OFF requested/feedback pending.
Cloud acknowledgement does not guarantee that the physical cabin has
turned off.

## Live acceptance without new test controls

1. Install **v0.3.16** via HACS, restart Home Assistant **when the EX5
   is not actively charging**, and verify iPhone notification permissions
   for the Home Assistant Companion App remain ON.
2. Turn **Automatic charging enabled** OFF and then ON using the existing
   EV Control switch while the car is not charging. You should receive
   actual iPhone push notifications for each change. Leave the intended
   weekly schedule ON afterward.
3. Let the next normal charging schedule start. Verify the start push has
   the right departure date/time, current SoC and target. A start command
   alone must not be labelled as confirmed charging.
4. After actual Geely stop/completion, verify end SoC, reached/not reached,
   and the explicitly **estimated battery kWh**.
5. Use one existing manual comfort button while parked. Confirm push
   describes the comfort action; after 30 minutes verify OFF and its push.
6. Let a real linked or independent climate schedule occur and confirm
   its start/stop pushes using the normal dashboard and **Developer
   Tools → States** (no special testing buttons).
7. If iPhone pushes do not arrive, check **Settings → System → Logs**
   for `Geely iPhone notification` and the persistent-notification
   warning. Confirm `notify.mobile_app_tims_iphone` is still present
   in HA's Developer Tools → Actions service list. In-app HA notifications
   alone do **not** prove phone delivery.

**Scope:** Automated tests validate HA service calls, event deduplication,
message content, sensor freshness, schedule/manual notifications, and
error fallback. Real iPhone delivery and Geely cloud state lag must be
confirmed on the user's Home Assistant installation.
