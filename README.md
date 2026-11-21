# Geely Smart Charge & Climate

An early **experimental integration** for Home Assistant, designed for the **Geely EX5** using community Geely Connect telemetry. Other Geely models have not been verified.

**Safety (experimental):** The proven manual start/stop test remains available. The automatic controller offers **Off / Monitor / Active** modes. Off is the default after every restart. Monitor makes read-only authorisation decisions; Active can issue guarded scheduled starts and stops using **Geely Connect only**. **This is for attended testing, not yet unattended charging.** Never run alongside another active charging controller. Read [the automatic test checklist](docs/automatic-charging-test.md) before enabling Active.

**Public charging responsibility:** Turn **Public charging mode ON before connecting to any public charger**, and turn it OFF when returning to normal automatic charging. The integration does not detect home location or public charging automatically. When ON, automatic charging starts, unexpected-charge stops and manual charging commands from this integration are suppressed. The native switch persists across Home Assistant restarts. Existing `input_boolean.ev_public_charging_mode` installations are still honoured as an additional interlock, so both must be OFF to resume normal charging. The optional Tesla Wall Connector is never required for core control.

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
