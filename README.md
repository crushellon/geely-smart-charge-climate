# Geely Smart Charge & Climate

An early **experimental integration** for Home Assistant, designed for the **Geely EX5** using community Geely Connect telemetry. Other Geely models have not been verified.

**Safety (experimental):** The proven manual start/stop test remains available. The automatic controller offers **Off / Monitor / Active** modes. Off is the default after every restart. Monitor makes read-only authorisation decisions; Active can issue guarded scheduled starts and stops using **Geely Connect only**. **This is for attended testing, not yet unattended charging.** Never run alongside another active charging controller. Read [the automatic test checklist](docs/automatic-charging-test.md) before enabling Active.

**Public charging responsibility:** Turn **Public charging mode ON before connecting to any public charger**, and turn it OFF when returning to normal automatic charging. The integration does not detect home location or public charging automatically. When ON, automatic charging starts, unexpected-charge stops and manual charging commands from this integration are suppressed. The native switch persists across Home Assistant restarts. Existing `input_boolean.ev_public_charging_mode` installations are still honoured as an additional interlock, so both must be OFF to resume normal charging. The optional Tesla Wall Connector is never required for core control.

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

After adding the integration, use the generated **Geely EV Control Centre (Test)** dashboard. Its Charging, Comfort Settings, Climate Scheduler and Vehicle Data pages use native Home Assistant cards. All seven charging days and climate slots start disabled. The charging schedule becomes live only when the automatic controller is explicitly set to Active; the seven independent climate slots remain simulation-only.

The integration exposes read-only `Observer status`, `Simulation decision`, `Next climate session`, `Live test status`, and `Automatic charging decision` sensors. Any simulated `START`, `WAIT` or `STOP_AT_TARGET` value is a recommendation **only**, not proof that a command has been sent. A 100% target always uses vehicle-managed termination in the simulator and in the attended live test (unless the user explicitly requests a stop or an emergency interlock is activated).

## Development status

This is an **EX5-focused pre-release** under active testing, not yet a finished unattended charging controller. Live charging commands require either an armed manual test or explicitly selecting Active automatic mode. **Off and Monitor never send automatic commands.** No Tesla or other smart charger is required; the user-operated public charging switch defines when automatic charging must be suppressed. HA notifications record decisions during Active mode. Check the [development documentation](docs/read-only-milestone.md) and [repository issues](https://github.com/crushellon/geely-smart-charge-climate/issues).

Run offline checks using `python -m unittest discover -s tests -v`.
