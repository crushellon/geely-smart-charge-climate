# Geely Smart Charge & Climate

An early **experimental integration** for Home Assistant, designed for the **Geely EX5** using community Geely Connect telemetry. Other Geely models have not been verified.

**Current build (v0.3.18 — concise charging completion and quiet verified automatic climate shutdown; vehicle validation ongoing):** Automatic charging is a persistent user setting, no developer Off/Monitor/Active or arm-test controls are exposed. The controller restores scheduled-charge ownership and completion history after Home Assistant restart rather than issuing a blind START. A manual charge temporarily pauses the automatic controller and restores the previously enabled preference after its confirmed end; releasing Emergency Stop restores that preference only if it was enabled. Charging-linked Cool/Warm runs whenever the specific EV Control departure day's comfort is enabled alongside its charging schedule. The separate Independent climate schedules enabled switch controls only the seven appointments on Climate Scheduler. Both functions retain manual climate priority and saved session ownership. **This is still a pre-release: verify restart recovery and climate on your own vehicle before relying on unattended operation.** Disable old charging and automatic climate controllers before testing. See [the v0.3.11 integration test plan](docs/persistent-auto-live-climate-test.md).

**Public charging responsibility:** Turn **Public charging mode ON before connecting to any public charger**, and turn it OFF when returning to normal automatic charging. The integration does not detect home location or public charging automatically. When ON, automatic charging starts, unexpected-charge stops and manual charging commands from this integration are suppressed. The native switch persists across Home Assistant restarts. Existing `input_boolean.ev_public_charging_mode` installations are still honoured as an additional interlock, so both must be OFF to resume normal charging. The optional Tesla Wall Connector is never required for core control.

## Short notifications and silent climate shutdown (v0.3.18)

EX5 scheduled overnight 100% charging and automatic start push were observed
working on 23 Nov 2026. Phone charge-finish messages now place battery change,
target result, estimated SoC-based kWh and Geely/deadline attribution in a
short lock-screen-friendly format. Detailed end reasons remain in controller
state/history.

Successful automatic climate shutdown (linked, independent or manual 30-minute
timeout) is quiet. The controller retains a 90-second persisted verification
window and warns if climate still does not report OFF, including after a
restart. Failed OFF service commands notify immediately. Explicit manual OFF
button notifications remain in place. No vehicle charging commands change.

## Startup charge enforcement and thread safety (v0.3.17)

**Automatic charging enabled + Public Charging Mode OFF:** A charge not owned
by a restored manual or automatic session is checked against the same normal
charging policy even during the first 120 seconds after an integration reload.
A genuinely unexpected home charge enters **CHECKING**, then requests
**STOP_REQUESTED** after the existing 30-second grace period. Geely OFF and
freshly reported power must subsequently confirm **STOPPED**. No blind
stop or start is issued merely because Home Assistant has restarted.

A previously created EXTERNAL marker is cleared when automatic control is
enabled so it cannot silently block enforcement. If **Automatic charging is
disabled**, unknown existing charging is observed without vehicle commands.
**Public Charging Mode** remains the explicit exemption for public charging.
Persisted integration-owned manual/automatic charge sessions still recover
their saved targets and ownership across reloads.

Fixed synchronous sensor event/periodic handlers that Home Assistant had
executed from worker threads, causing repeated exceptions from
`async_write_ha_state`. The scheduled manual-comfort expiry callback is also
marked for event-loop execution so its async task is scheduled safely.

**After installation:** Under Developer Tools → States, inspect **Automatic
charging decision**, **Manual charging status**, **Vehicle charging status**,
and **Observer status**. In Active mode an unattributed charge outside the
window should progress through CHECKING → STOP_REQUESTED → STOPPED, subject to
real Geely response. The **Vehicle charging status** sensor now also exposes
`unattributed_charge_policy`. Confirm thread-safety errors stop appearing
in Settings → System → Logs.

**Safety:** This is still experimental code. Use the vehicle to stop a
charging session that Home Assistant fails to stop. Do not use public chargers
with Public Charging Mode OFF.

## Real iPhone push notifications (v0.3.16)

The integration now sends **real phone push notifications** using the
existing Home Assistant Companion App service
`notify.mobile_app_tims_iphone`, in addition to Home Assistant's
historical controller log/inbox records. It does **not** require any
new dashboard buttons, cards, test controls or external apps.

- **Automatic charging started:** after freshly reported charging power
  (not merely the ON command), with battery start %, requested target
  and the correct departure calendar day/ready-by time.
- **Automatic charging finished/stopped:** actual ending battery %,
  target achieved or not achieved, stop reason/deadline, and
  **estimated battery energy in kWh** from SoC change × 68.39 kWh.
  This is *not* a wall-meter or charger-energy measurement.
- **Manual Start chosen target / Quick 80 / Quick 100:** start push after
  vehicle state actually reports charging. Manual STOP, retries,
  confirmed stop and failure warnings get separate push messages.
- **Real on/off controls:** automatic enabled, emergency latch/release,
  Public Charging Mode, departure-day schedules, daily linked comfort,
  independent climate schedule master/slots and comfort steering heating.
  Purely visual Show Settings expanders never push.
- **Manual Cool/Warm/Custom/OFF:** requested profile, cabin temperature,
  seats and steering plus 30-minute auto-OFF expiration. Timeout success
  and failure both push.
- **Charging-linked and independent climate schedules:** one start and
  one stop push per occurrence with configured settings and reported
  Geely climate feedback, distinguishing a confirmed state from an
  accepted cloud command.

Recent push event IDs persist across HA restarts to suppress duplicate
15-second polling alerts. If the phone notify service is missing, the
integration logs a warning and displays a **failure** notification in
Home Assistant; it never mislabels that as a delivered iPhone push.

Use the normal dashboard and HA Developer Tools → States/History to
observe actual control states. Confirm the iPhone is receiving pushes
before relying on them for unattended charging alerts.

See [v0.3.16 iPhone push setup and validation](docs/iphone-push-notifications.md).

## Manual comfort 30-minute auto-OFF (v0.3.15)

The finished **Comfort Cool**, **Comfort Warm** and **Custom temperature
ON** buttons on EV Control now have an **automatic 30-minute maximum
session**. Pressing any one starts a fresh 30-minute deadline. At expiry,
Home Assistant sends the same Geely actions as **Climate + seats OFF**:
cabin OFF, both driver/passenger seat heat/vent OFF, and steering heat OFF.
The existing OFF button still allows an immediate stop.

Manual ownership is then released so future **charging-linked and
independent climate appointments** can run normally. The manually
superseded occurrence stays suppressed so it cannot immediately turn
the car on again. No climate timer, developer control or extra button
was added to the user's four-tab dashboard.

The absolute expiry is **persisted through HA restart**; after a restart
it cannot be extended accidentally. On startup, an old legacy MANUAL
override with no deadline is expired and stopped rather than blocking
all future scheduled climate. Actual service requests use an exact
Home Assistant deadline callback plus 15-second periodic fallback.
If an OFF request fails, the controller retries up to three times
one minute apart and leaves a visible error in existing HA States.
Cloud service acknowledgment is not proof of the physical vehicle
state and should be verified on the EX5.

Inspect the existing **Manual climate status** sensor attributes:
`manual_comfort_active`, `auto_off_after_minutes` (30),
`manual_comfort_expires_at`, `manual_comfort_seconds_remaining`,
and `manual_comfort_timeout_error`. **No charging switch commands**
are issued by the manual comfort timer.

See [the v0.3.15 manual comfort auto-OFF guide](docs/manual-comfort-30-minute-auto-off.md).

## Separate charging-linked and independent climate controls (v0.3.14)

In earlier versions the **Scheduled climate enabled** switch on the Climate
Scheduler tab inadvertently blocked both independent appointments and the
charging-linked Cool/Warm preferences already enabled for a departure day.
That meant Monday's EV Control comfort could show ON but diagnostic attributes
still said `linked_comfort_commands_enabled: false`.

**Charging-linked comfort is now controlled solely by the normal EV Control
charging-day appointment and its Cabin comfort enabled / Cool or Warm
settings.** It requires Automatic charging enabled and the relevant charging
day enabled, but it does not need the independent climate master switch.
Manual climate overrides, Emergency Stop and Public Charging Mode continue
to take precedence.

The existing master switch now displays **Independent climate schedules
enabled** and controls **only** the seven slots on Climate Scheduler. It
retains the same unique ID, stored setting and dashboard placement, so no
replacement controls or migration steps are necessary. Existing independent
slots remain inactive while that switch is OFF.

For example, Monday 23 November 2026 with a 07:00 vehicle-ready time,
20-minute linked lead, 30-minute hold, and Comfort Cool at 16°C with Vent High
on both seats should send cabin commands at **06:40** and finish at **07:30**,
even if all independent climate appointments are OFF. The charging target
itself is unchanged. The normal dashboard and Developer Tools → States can
verify the result; no test buttons are involved.

See [v0.3.14 linked comfort fix](docs/separate-linked-independent-climate.md).
The software test suite verifies the logical separation; actual cloud
activation and physical climate response still require EX5 validation.

## Strict ready-by charging cutoff (v0.3.13)

- **50–99% scheduled charges stop at the exact ready-by deadline**, even
  if the car has not reached the requested battery percentage. The previous
  three-hour overrun has been removed. Target completion can still stop
  earlier. The outcome is recorded as **expired** rather than completed.
- **100% scheduled charges remain Geely-terminated** when a real charging
  session was confirmed before ready-by. This includes balancing after
  100% is displayed. A missed departure **cannot start later**; unplugging
  after the deadline ends that session's exception. A configured Geely
  or optional Tesla power sensor provides confirmation; if no charging-power
  sensor exists, Geely's ON state is used before the cutoff.
- A **new plug-in outside all valid charging windows** no longer inherits
  the unknown-owner protection from earlier HA upgrades. Automatic control
  checks unexpected charging and requests STOP after its existing short
  debounce, with verified stop confirmation. A legitimate new charge within
  an open schedule window can be adopted without a second START command.
- A charge **already underway at Home Assistant startup** with an unknown
  owner remains protected from blind cancellation until its actual origin
  can be established. Manual charge, Public Charging Mode and Emergency
  Stop retain priority.
- **No dashboard changes, test buttons or new modes.** The same original
  four-tab product remains the only control UI.

See [the v0.3.13 ready-by rule and verification guide](docs/strict-ready-by-hard-stop.md).
This controller logic is covered by automated regressions but still
requires real Geely cloud/vehicle verification.

## Production dashboard and vehicle-state recovery (v0.3.12)

The integration-generated dashboard now mirrors the original **EV Control,
Comfort Settings, Climate Scheduler, EX5 Stats** design using only the intended
real vehicle controls. The developer status and simulation panels are not
displayed. Obsolete developer arm/test button and mode-selector classes have
been removed. Existing normal entities retain stable unique IDs.

**An observed charge is not necessarily an integration-owned charge.**
On an upgrade from versions without persisted manual ownership, the EX5 can be
charging while a new process has no record of the original manual target.
Instead of incorrectly showing IDLE, the product now exposes:
- **Vehicle charging status** (CHARGING, CHARGING_REPORTED, STOPPED, UNKNOWN),
  source and owner attribution in Home Assistant States.
- **Manual charging status** showing CHARGING_UNATTRIBUTED where vehicle
  activity exists but the current controller cannot verify the manual owner.
- **Automatic charging decision** showing EXTERNAL when an existing charge
  is observed but not owned by the active schedule. It will not issue a
  surprise OFF command against that unowned session.

At home, an explicit **Stop manual** button still requests a guarded real
stop for an observed session, even when its original software owner was
lost on upgrade. A new Start chosen target/Quick 80/100 cannot commandeer
a charge that is already underway; first stop and verify if appropriate.

**Home Assistant reload/restart no longer automatically turns OFF an owned
charge.** The persistent manual and automatic session markers are adopted
by observation on restart, including saved pending stop requests. The
custom manual target slider is now saved in config entry options. The
**Resume schedule** button can rearm a paused charge even if the persistent
Automatic charging enabled switch is already ON.

The optional Tesla Wall Connector is always read-only and never required
by the controller. When available, positive wallbox power can confirm
observed charging while Geely cloud telemetry lags, and can prevent a
false STOPPED confirmation while real power is still flowing.

**Existing automatic preference:** v0.3.11 and later remember ON/OFF; an
older ephemeral mode cannot be retroactively reconstructed. An OFF saved
preference remains OFF until you deliberately turn it ON; then it persists.
The integration does not silently turn itself ON after an upgrade.

See [v0.3.12 dashboard/upgrade guide](docs/finished-dashboard-existing-charge-migration.md)
for the exact user-facing layout and how to inspect actual features through
Developer Tools → States, without any testing buttons.

## Persistent charging and real scheduled climate (v0.3.11)

- **Automatic charging enabled is remembered.** The state survives HA updates
  and restarts once set to ON in the production dashboard. On fresh installs
  and migrations where this intent was never saved, it defaults OFF until the
  user explicitly enables it. Public Charging Mode and Emergency Stop still
  suppress vehicle commands; the user's underlying preference is retained.
- After any manual Start chosen target / Quick 80% / Quick 100% session ends
  and Geely's stop is confirmed, the automatic schedule resumes if the saved
  preference is enabled. **Manual Stop does not permanently turn scheduling
  off.** If the user switched automatic charging OFF, it stays OFF.
- After Emergency Stop is released, previously enabled scheduling can resume,
  but only when the pending stop has been verified. The emergency interlock
  never triggers a blind START itself.
- HA restart restores manual/automatic session markers without issuing a
  duplicate charging START. Completion history is persisted across restarts.
  The controller observes Geely status with a recovery grace period before
  deciding what to do. Geely termination at 100% is still vehicle-managed.
- **Charging-linked preconditioning** starts ahead of the same ready-by
  deadline for the day's Cool/Warm profile and ends after the selected hold
  interval. It does not require active charging to be underway at that moment.
  Public mode suppresses linked climate; no Tesla hardware is needed.
- **Seven independent climate sessions** issue Geely temperature, seat
  heating/ventilation and steering-wheel commands at their configured lead
  time, regardless of charging or plug state; the vehicle is switched back
  off at each scheduled end. Independent slots can share days, and active
  sessions are retained across overlapping windows.
- A manually pressed climate command supersedes the current scheduled
  occurrence. The previous occurrence is suppressed so it cannot immediately
  override the manual request. Manual climate remains in priority mode until
  Climate + seats OFF is pressed, after which future appointments can run.
- On upgrade from simulation-only climate, the persistent **Scheduled climate enabled**
  master switch defaults OFF so previous experimental slots cannot activate
  the car unexpectedly. Enable it intentionally when ready to use live climate.
- Every climate occurrence and charging owner transition is persisted to
  avoid repetitive cloud commands after HA restarts. Diagnostic sensors show
  live state and errors. Unavailable Geely climate entities are reported rather
  than assumed successful.
- The old developer arm-test buttons and Off/Monitor/Active selector are no
  longer registered as supported controls on new integration reloads.
  Existing orphaned entities can be removed from HA's entity registry.

**Note:** The v0.3.9 and earlier release sections below document historical
stages, not the feature status of v0.3.11. The new live climate implementation
has passed offline regression tests but requires physical testing before
unattended use. [Installation and test instructions](docs/persistent-auto-live-climate-test.md).

## Manual charging owner handoff fix (v0.3.10)

A real EX5 test revealed an overlap between the automatic charging controller's
five-minute **post-stop rebound watchdog** and a new explicitly authorised
**manual charging session**. The watchdog could mistake the manual START for a
late restart of its previously stopped scheduled charge and send an unwanted
Geely OFF command. The resulting notification explicitly said "Charging
resumed after verified stop; enforcing cancellation."

Manual charge START now cancels the prior automatic watch **only after**
passing the live safety checks, while holding the controller lock and confirming
no automatic stop is pending. The automatic watchdog also independently
recognises an authorised manual owner and must not stop it. If no manual
session owns the vehicle, late charging after a verified stop still gets
enforced. This avoids weakening the unattended delayed-start safeguard.

**Comfort Cool did not issue the charging STOP directly.** Vehicle/API climate
behaviour while charging still needs physical verification; the corrected
control path is not yet live tested. Follow the
[v0.3.10 supervised handoff and climate test](docs/manual-charge-watchdog-handoff-test.md).
Do not restart HA while charging.

## Four-tab EV Control Centre (v0.3.9)

The HACS-provisioned dashboard now follows the original screenshot design,
using built-in Home Assistant cards:

- **EV Control:** Geely battery/range/charge summary, Automatic charging enabled,
  Public Charging Mode, independent emergency STOP/release, manual target preview
  and Start/Stop/Quick 80%/Quick 100%/Resume schedule, direct Cool/Warm/custom/off
  cabin controls, and the seven-day **vehicle ready-at** charging schedule.
- **Comfort Settings:** Expandable Cool/Warm temperatures, seat heating/
  ventilation, steering wheel settings, and shared charge-linked lead/hold time.
- **Climate Scheduler:** Seven independent live cabin appointments; enabling
  one schedules Geely climate, seat and steering commands.
- **EX5 Stats:** Read-only gauges, range, energy efficiency, tyre measurements,
  vehicle health, battery/charging history. An optional Tesla Wall Connector
  may contribute **display-only** power, never charging authorisation.

Manual charge buttons initiate charging directly through Geely Connect.
**Start manual temporarily pauses automatic control, which resumes when
the manual charge finishes if the saved Automatic charging setting is ON.** If an
automatic scheduled session is already active, stop/verify it before issuing
manual Start; the new manual action will refuse overlapping control.
The manual Stop path uses post-command Geely telemetry, 30-second settling,
and a five-minute watch for delayed charging.

Manual Cool/Warm, custom temperature and climate + seats OFF now submit
direct Geely climate commands to the matching vehicle climate, seat and
steering entities when present; these are **new, not yet live-tested** and
are separate from automated comfort schedules. Status means commands were
submitted, not independently verified by the car. Do not run the original
EVCC climate reconciler concurrently when testing these buttons.

The new **Emergency STOP** latches an integration-owned emergency interlock
and requests an Off command, including when no charging schedule is owned.
Release does **not** automatically enable charging. Public Charging Mode
still suppresses all integration charging commands, including emergency Off
requests; turn it on for public charging and use the vehicle's own controls
for public-session stopping.

The old armed-test entities are no longer displayed but remain present
for development compatibility. A known, unmodified generated four-tab test
dashboard is migrated on restart. Manually customized and separate dashboards
are preserved. The existing sidebar entry is renamed without deleting
its URL or recreating the dashboard.

**Important:** v0.3.11 restores the automatic preference and executes live
scheduled climate. Both require user validation. See
[the current v0.3.11 test plan](docs/persistent-auto-live-climate-test.md).

## Live schedule edits (v0.3.5)

While an automatic charging session is running, editing its **battery target** or
**ready-by time** now updates the active controller rather than only the simulated
planner. Reducing the target to the current reported battery percentage (or below)
requests a real stop immediately. Disabling the active day's schedule also requests
a stop. Completed sessions are not restarted simply by editing their ready-by time.

The **Automatic charging decision** status now refreshes for schedule changes
and exposes the current target/deadline plus charging-linked comfort configuration
(profile, temperature, seats, steering wheel and lead/hold timing). Comfort edits
are **configuration and diagnostics only**; scheduled climate vehicle commands
are still disabled in this experimental version.

For the exact supervised tests and rollback guidance, see
[Live schedule edit test plan](docs/live-schedule-edit-test.md).

## Scheduled charge resume and completion (v0.3.6)

A charging session is **complete only when the requested target has actually
been reached**. A user cancellation or Geely charging ending before target
must no longer be labelled COMPLETED. An unfinished session is paused rather
than automatically restarted in a rapid loop.

A **new user request** may resume that same departure day: increase the
scheduled battery target, disable then re-enable its schedule, or deliberately
return to **Active** from Off/Monitor after stop verification (temporary
developer UI). Re-arming with unknown SoC or when already at target is blocked.
Changing the clock time alone does not automatically restart a completed
charge. All normal 100% termination remains managed by the vehicle.

The final product is intended to have a dedicated **Resume schedule** control,
not the developer Off/Monitor/Active selector. This release is still for
attended testing; see the [session-resume test checklist](docs/session-completion-rearm-test.md).

## Replanning a running charge (v0.3.7)

If a user **edits the active day's battery target or ready-by time**, the
controller now recalculates when charging needs to begin. If the new plan
would start later than now, an already-running charge is stopped and
verified, then automatically resumes when its **revised start window** opens.
This is not considered final completion or a manual cancellation.
Ordinary battery-percentage updates do **not** pause a running charge;
otherwise charging could oscillate on each new SoC reading. If the newly
chosen target is already reached, it stops immediately instead.

The special 100% rule still applies: Geely manages normal full-charge
balancing and termination. Public Charging Mode always suppresses automatic
charging commands. This remains an **attended-test** release with the
temporary Off / Monitor / Active selector; scheduled cabin commands remain
disabled. See [the v0.3.7 live replanning test](docs/active-session-replanning-test.md).

## Geely STOP verification hardening (v0.3.8)

**Safety-critical fix:** If a charge is started and Controller mode is
changed to **Off** immediately afterward, Geely may report delayed vehicle
state updates. Previous versions could claim STOPPED on stale telemetry,
then miss a late charging start while Off.

Stop verification now requires a **30-second settling period**, two
affirmative low-power/OFF observations, and fresh Geely switch/power reports
since the OFF command. A five-minute post-stop watchdog can reassert OFF
if charging reappears after verified cancellation, even in Off mode.
If fresh confirmation never arrives, the state remains unverified rather
than claiming the charger has stopped. A separate **Stop verification**
diagnostic is shown in the generated test dashboard.

This remains an **attended-test integration**: the controller cannot
guarantee Geely cloud state matches actual vehicle power, and should
not be left unattended. Public Charging Mode still suppresses commands.
Follow the [v0.3.8 live stop test](docs/delayed-start-stop-verification-test.md)
and stop directly through the vehicle whenever status and actual power disagree.

## HACS setup and updates (custom repository)

1. In Home Assistant, open **HACS**, then its menu **Custom repositories**.
2. Add `https://github.com/crushellon/geely-smart-charge-climate` as category **Integration**.
3. Open the Geely Smart Charge & Climate listing in HACS and select **Download**.
4. Restart Home Assistant to load new Python code.
5. In **Settings → Devices & Services**, use the existing Geely Smart Charge & Climate configuration if you already set it up; otherwise add it.
6. Future published changes on the tracked branch can show as **Update** in HACS and Home Assistant's updates interface. **Restart Home Assistant after a Python integration update.**

Do **not** remove Geely Connect or your working EV automations when transitioning an existing manually installed copy to HACS management. Back up the existing custom component folder first.

The initial tracked version must be installed from HACS once; copying ZIP files directly does not enroll a repository into HACS update tracking.

## Configuration

The setup wizard suggests matching EX5 sensors, including battery state, charging switch, and optional **Geely** charging power. The Geely plug sensor must also be discoverable for automatic starts; missing plug confirmation blocks a start. External charger telemetry is optional. It uses a standard 7 kW single-phase charger rating by default and calculates initial battery-side estimates internally. Charging-rate learning collects reliable SOC changes and saves recent samples.

After adding the integration, use the generated **Geely EV Control Centre** dashboard. Its EV Control, Comfort Settings, Climate Scheduler and EX5 Stats tabs use native Home Assistant cards, matching the earlier EV Control Centre. All seven charging days and independent climate slots start disabled on a new installation. Enable automatic charging explicitly on EV Control; enabled climate slots now operate the vehicle when due.

The integration exposes read-only `Observer status`, `Simulation decision`, `Next climate session`, `Live test status`, and `Automatic charging decision` sensors. Any simulated `START`, `WAIT` or `STOP_AT_TARGET` value is a recommendation **only**, not proof that a command has been sent. A 100% target always uses vehicle-managed termination in the simulator and in the attended live test (unless the user explicitly requests a stop or an emergency interlock is activated).

## Development status

This is an **EX5-focused pre-release** under active testing, not yet a finished unattended charging controller. Normal manual charging buttons request real Geely vehicle actions; the automatic charging switch must be turned on separately for schedules. Off/Monitor/Active remain only internal developer states. **The saved automatic preference is restored on restart.** No Tesla or other smart charger is required; the user-operated public charging switch defines when automatic charging must be suppressed. HA notifications record decisions during Active mode. Check the [development documentation](docs/read-only-milestone.md) and [repository issues](https://github.com/crushellon/geely-smart-charge-climate/issues).

Run offline checks using `python -m unittest discover -s tests -v`.
