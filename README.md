# Geely Smart Charge & Climate

An early **experimental integration** for Home Assistant, designed for the **Geely EX5** using community Geely Connect telemetry. Other Geely models have not been verified.

**Safety (experimental):** The normal EV Control dashboard now exposes an **Automatic charging enabled** switch, not the developer Off / Monitor / Active selection. The switch is session-only: Home Assistant restart resets it to Off until safe restart recovery is implemented. When enabled, it authorises schedule-based Geely Connect charging. The underlying diagnostic modes remain available in Home Assistant's entity registry for troubleshooting only. **Do not rely on this integration for unattended departure charging yet.** Disable previous charging-command automations before using it and see [the new dashboard test checklist](docs/product-dashboard-test.md).

**Public charging responsibility:** Turn **Public charging mode ON before connecting to any public charger**, and turn it OFF when returning to normal automatic charging. The integration does not detect home location or public charging automatically. When ON, automatic charging starts, unexpected-charge stops and manual charging commands from this integration are suppressed. The native switch persists across Home Assistant restarts. Existing `input_boolean.ev_public_charging_mode` installations are still honoured as an additional interlock, so both must be OFF to resume normal charging. The optional Tesla Wall Connector is never required for core control.

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
- **Climate Scheduler:** Seven editable independent cabin appointments. They
  remain **simulation-only**; enabling one does not run climate.
- **EX5 Stats:** Read-only gauges, range, energy efficiency, tyre measurements,
  vehicle health, battery/charging history. An optional Tesla Wall Connector
  may contribute **display-only** power, never charging authorisation.

Manual charge buttons now initiate a charge directly through Geely Connect,
without exposing temporary test arming. **Start manual pauses automatic
charging until the separate Resume schedule button is pressed.** If an
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

**Important:** The automatic switch still resets to Off after a restart;
interruption recovery and automatic scheduled climate have not been
production-validated. Follow [v0.3.9 install and test steps](docs/product-dashboard-test.md)
before regular use.

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

After adding the integration, use the generated **Geely EV Control Centre** dashboard. Its EV Control, Comfort Settings, Climate Scheduler and EX5 Stats tabs use native Home Assistant cards, matching the earlier EV Control Centre. All seven charging days and independent climate slots start disabled on a new installation. Enable automatic charging explicitly on EV Control; climate slots remain simulation-only.

The integration exposes read-only `Observer status`, `Simulation decision`, `Next climate session`, `Live test status`, and `Automatic charging decision` sensors. Any simulated `START`, `WAIT` or `STOP_AT_TARGET` value is a recommendation **only**, not proof that a command has been sent. A 100% target always uses vehicle-managed termination in the simulator and in the attended live test (unless the user explicitly requests a stop or an emergency interlock is activated).

## Development status

This is an **EX5-focused pre-release** under active testing, not yet a finished unattended charging controller. Normal manual charging buttons request real Geely vehicle actions; the automatic charging switch must be turned on separately for schedules. Off/Monitor/Active remain only internal developer states. **The normal automatic control switch resets Off on restart.** No Tesla or other smart charger is required; the user-operated public charging switch defines when automatic charging must be suppressed. HA notifications record decisions during Active mode. Check the [development documentation](docs/read-only-milestone.md) and [repository issues](https://github.com/crushellon/geely-smart-charge-climate/issues).

Run offline checks using `python -m unittest discover -s tests -v`.
