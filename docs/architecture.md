# Planned Home Assistant architecture

## Modules

1. Home Assistant `config_flow`: select Geely vehicle / required battery and charging entities, with optional Geely charging-power input and a rated charger-power estimate. No third-party smart charger is required. Use options flow for later changes.
2. Read-only HA adapter: normalize battery %, plug state, charge switch, power, freshness, climate and optional seat controls. Check capabilities and never assume EX5-only entities.
3. Planner: timezone-aware deadline, energy/time estimate, learned SOC gain over valid uninterrupted sessions, safety buffer and confidence.
4. Session controller: explicit states `idle`, `scheduled_wait`, `charging`, `vehicle_finishing`, `complete`, `cancelled`, `blocked`, `fault`; explicit authorization on **every command**.
5. Climate engine: separate ownership and active-window reconciliation, shared Warm/Cool and seven independent slots, seat heat/vent mutually exclusive, hold-after-deadline.
6. Diagnostics entities and logging: expose action, source, reason, last update, planning confidence and recovery attempts. Privacy-safe diagnostics.
7. Dashboard: optional install/import; never overwrite another dashboard without explicit user action.

## Safety invariants to prove in tests

- Only one charge-command authority.
- Emergency stop blocks start and recovery; release restores normal availability without resuming cancelled manual session.
- Manual override supersedes schedules until completed/cancelled.
- A persistent, explicit Public charging mode is the only automatic/public boundary; no home-location inference. When ON, suppress all new integration charging commands, retries and unexpected-charge stops. Existing legacy public-mode helper must also be honoured as a migration interlock.
- When Public charging mode is OFF, the user accepts responsibility for ensuring the car is not charging publicly; test this warning conspicuously in the dashboard and onboarding.
- Explicitly completed 100% session is never restarted by missing power.
- Non-100 targets use intentional stop and verify consecutive Geely charging-switch OFF states, corroborated by Geely power when valid; when power is missing, report the reduced confirmation strength.
- Missing/stale SoC cannot authorize new charging, and missing plug state cannot be silently treated as plugged in.
- Restart reconstructs intent conservatively; never assumes ongoing power proves permission to charge.
- Command rate limits, timeouts, retry bounds, idempotency, and vehicle API concurrency handling.
- Charging control must function with Geely Connect alone; third-party charger sensors are optional display/diagnostic enhancements only.
- If charger power and Geely disagree, show uncertainty rather than issuing rapid contradictory commands.
- If charging rate is uncertain, prefer an earlier start and clearly warn if deadline is infeasible.

## Public-release gates

1. Pure planning logic tests.
2. HA configuration and entity discovery tests.
3. Offline session-state machine / restart / emergency / public mode tests.
4. Observe-only comparison with existing working YAML system.
5. Controlled live EX5 charging and climate tests.
6. HACS/Marketplace repository validation and user-facing installation docs.
7. GitHub alpha/beta version, then public stable release.

No other model compatibility claims until separately tested.
