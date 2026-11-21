# Automatic home charging — controlled test sequence (v0.3.0)

The integration now has three separate modes under **Charging & Schedule**:

- **Off** — default after installation, reload or Home Assistant restart;
  does not issue automatic charging commands.
- **Monitor** — calculates whether home charging should START, WAIT, remain
  AUTHORISED, or STOP; records the explanation but sends no command.
- **Active** — allows scheduled home charging to start, and stops verified
  unauthorised charging after a 30-second authorisation check. It also stops
  owned scheduled sessions at targets below 100%, verifies switch OFF and power
  near zero, and retries failed stop confirmations.

**This is still a supervised test release. Do not enable unattended/overnight
charging yet.** The mode intentionally reverts to Off after a restart, and an
interrupted session may need manual intervention. Climate remains simulation-only.

## Prerequisites

1. The old EV charging controller and all old charge-command automations must
   remain disabled. `input_boolean.ev_controller_enabled` and
   `binary_sensor.ev_legacy_charging_controllers_active` should report off.
2. The old manual full-charge helper should also report off. Emergency stop
   and public charging mode should be off for a home charging start.
3. Geely battery %, charging state and charging power must be available.
4. The car must be physically plugged into the home wallbox and both
   `binary_sensor.my_geely_ex5_4034_charger_plug` (or vehicle-specific equivalent)
   and `binary_sensor.tesla_wall_connector_vehicle_connected` must report on
   before automatic commands are authorised.
5. Keep manual live testing disarmed while using automatic Active mode.

If Tesla Wall Connector presence cannot be confirmed, the controller reports
UNKNOWN and sends no automatic commands. This named sensor is an EX5 test
installation prerequisite, not a requirement of a future generic integration.

## First test — Monitor

1. Set the **Automatic charging mode** dropdown to **Monitor**.
2. Observe **Automatic charging decision** and its `decision`, `reason`,
   `home_confirmed`, `ready_by`, `scheduled_target` attributes.
3. Confirm a disabled week gives WAIT / no enabled schedules. Configure one
   charge day with a future ready-by time; the decision should become START
   only when the calculated charging window opens.
4. Monitor sends **no charging commands**. Do not assume the car will start.

## Second test — Active, attended

1. Keep the car parked, plugged in, and supervised.
2. Configure one near-term charge target 1% above current SOC and a realistic
   ready-by time. Ensure the planned start time is within the next hour.
3. Set Automatic charging mode to **Active**. Confirm the controller starts
   only within the calculated window and while every interlock is clear.
4. Verify the Geely switch changes ON and charging power rises.
5. When target is reached, expect STOP_REQUESTED and then a positive
   STOPPED confirmation after the car reports switch OFF and power near zero.
6. Set mode back to **Off** after the test. **Do not leave Active running
   overnight during initial testing**.

## Third test — unexpected charging guard, attended

1. Keep the car connected to the positively verified home wall connector,
   with no authorising charging window and no manual override.
2. In Monitor mode, start charging from the *vehicle's own control*.
   The decision should report STOP but no stop request should be sent.
   Manually stop this test.
3. In Active mode, repeat only while present. The status should first show
   CHECKING, then after approximately 30 seconds request STOP and verify
   Geely switch OFF plus low charging power. An HA notification records the
   detection, attempted stop and verification.
4. If any status is UNKNOWN, BLOCKED or ERROR, avoid repeating commands;
   inspect the `sensor.automatic_charging_decision` attributes and car.

## Protection rules

- Public charging mode suppresses automatic commands; losing confirmed
  home-wallbox presence never authorises a start or a stop.
- Emergency stop suppresses starts and requests a stop at a verified home
  charger, even for a session not started by this controller.
- Manually started integration sessions take priority over schedules.
- 100% scheduled charging is terminated by **Geely itself**, not by SOC
  100 or the ready-by time. Automatic Off is an explicit manual cancellation.
- Charging-rate planning uses the integration's learned effective rate when
  available, otherwise the standard initial estimate.
- On a graceful integration unload, an owned under-100% charging session
  requests a stop. Restart recovery is **not yet validated for unattended use**.
- User-facing event details are available through Home Assistant persistent
  notifications, the audit sensor, and the `geely_smart_charge_decision`
  event. Dedicated phone notifications are not configured automatically.

No vehicle speed sensors are read.
