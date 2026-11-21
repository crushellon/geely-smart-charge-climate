# Planned Home Assistant architecture

## Modules

1. Home Assistant `config_flow`: select Geely vehicle / required entities, optional charger power and connection sensors, battery capacity, expected effective rate. Use options flow for later changes.
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
- Public charging disables home-session starts/recovery; must not stop remote public charging.
- Explicitly completed 100% session is never restarted by missing power.
- Non-100 targets use intentional stop and verify power cessation, with guarded reporting if telemetry stale.
- Missing/stale SoC cannot authorize new charging, and missing plug state cannot be silently treated as plugged in.
- Restart reconstructs intent conservatively; never assumes ongoing power proves permission to charge.
- Command rate limits, timeouts, retry bounds, idempotency, and vehicle API concurrency handling.
- If optional smart charger is absent, fault detection uses conservative Geely-only signals.
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
