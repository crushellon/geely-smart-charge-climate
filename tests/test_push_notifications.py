"""Real mobile Companion App notifier: iPhone dispatch and deduplicated events."""
import ast
import asyncio
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
module = ast.parse((ROOT / "push_notifications.py").read_text())
nodes = [
    n for n in module.body
    if isinstance(n, (ast.ClassDef, ast.FunctionDef)) or
    isinstance(n, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id in (
            "DEFAULT_NOTIFY_SERVICE", "MAX_RECENT_EVENTS"
        ) for target in n.targets
    )
]
warnings = []
now = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
env = {
    "datetime": datetime, "timezone": timezone, "isfinite": isfinite,
    "dt_util": SimpleNamespace(
        utcnow=lambda: now, as_local=lambda dt: dt.astimezone(timezone.utc)
    ),
    "DEFAULT_USABLE_CAPACITY_KWH": 68.39,
    "_LOGGER": SimpleNamespace(warning=lambda *args: warnings.append(args)),
    "persistent_notification": SimpleNamespace(
        async_create=lambda *args, **kwargs: warnings.append((args, kwargs))
    ),
}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "push_notifications.py", "exec"), env)
Notifier = env["VehiclePushNotifications"]


class FakeServices:
    def __init__(self):
        self.calls = []
        self.available = True
        self.fail = False

    def has_service(self, domain, service):
        return self.available and domain == "notify" and service == "mobile_app_tims_iphone"

    async def async_call(self, domain, service, data, blocking):
        self.calls.append((domain, service, data, blocking))
        if self.fail:
            raise RuntimeError("Phone push service failed")


class NotificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        warnings.clear()
        self.services = FakeServices()
        self.entry = SimpleNamespace(options={})
        self.telemetry_time = now
        self.states = SimpleNamespace(get=lambda entity: SimpleNamespace(
            state="6.5",
            last_reported=self.telemetry_time,
        ))
        self.runtime = SimpleNamespace(
            hass=SimpleNamespace(
                services=self.services, states=self.states,
                async_create_task=asyncio.create_task
            ),
            entry=self.entry,
            charging_power="sensor.power",
            charging_switch="switch.car",
            wallbox_power="sensor.tesla_wall_connector_total_power",
            battery="sensor.soc",
            owned=False, started_at=None, active_target=None,
            session_start_soc=None, stop_requested_at=None,
            auto=SimpleNamespace(
                owned=False, owned_deadline=None, stop_requested_at=None,
                owned_target=None, owned_day=None, session_start_soc=None,
                started_at=now
            ),
            vehicle_activity=lambda: ("STOPPED", 0.0),
            _wallbox_kw=lambda: None,
            _raw=lambda e: "41" if e == "sensor.soc" else "off",
            _save_options=lambda **kw: self.entry.options.update(kw),
        )
        self.notifier = Notifier(self.runtime)

    async def flush(self):
        for _ in range(4):
            await asyncio.sleep(0)

    async def test_stale_wallbox_cannot_confirm_geely_charge_start(self):
        self.runtime.wallbox_power = "sensor.tesla_wall_connector_total_power"
        self.runtime._wallbox_kw = lambda: 6.5
        self.states.get = lambda entity: SimpleNamespace(
            state="6.5" if entity == self.runtime.wallbox_power else "0",
            last_reported=self.telemetry_time,
        )
        self.assertFalse(self.notifier._fresh_vehicle_feedback(now))

    async def test_calls_real_iphone_mobile_app_service_not_inbox(self):
        self.assertTrue(self.notifier.emit(
            "session:1", "Geely started", "41% to 100% by 07:00"
        ))
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)
        domain, service, data, blocking = self.services.calls[0]
        self.assertEqual((domain, service), ("notify", "mobile_app_tims_iphone"))
        self.assertEqual(data["title"], "Geely started")
        self.assertEqual(data["message"], "41% to 100% by 07:00")
        self.assertTrue(blocking)
        self.assertFalse(warnings)

    async def test_notification_deduplicates_across_timer_and_restart(self):
        self.notifier.emit("monday:2026-11-23:start", "START", "message")
        self.notifier.emit("monday:2026-11-23:start", "START", "message")
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)
        recovered = Notifier(self.runtime)
        self.assertFalse(recovered.emit(
            "monday:2026-11-23:start", "START", "message"
        ))
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)

    async def test_missing_iphone_service_logs_failure_not_fake_success(self):
        self.services.available = False
        self.notifier.emit("first", "Geely", "message")
        await self.flush()
        self.assertEqual(self.services.calls, [])
        self.assertTrue(warnings)
        self.assertNotIn("first", self.entry.options.get("push_delivered_ids", []))
        self.assertFalse(self.notifier.emit("first", "Geely", "message"))
        await self.flush()
        self.assertEqual(len(warnings), 1)  # inbox warning recorded by fake

    async def test_dispatcher_accepts_explicit_notify_dot_service_option(self):
        self.entry.options["phone_notification_service"] = (
            "notify.mobile_app_tims_iphone"
        )
        self.notifier.emit("manual:off", "Manual OFF", "stopped")
        await self.flush()
        self.assertEqual(self.services.calls[0][1], "mobile_app_tims_iphone")

    async def test_actual_positive_power_triggers_one_real_start(self):
        started = datetime(2026, 11, 22, 9, tzinfo=timezone.utc)
        self.runtime.owned = True
        self.runtime.started_at = started
        self.runtime.session_start_soc = 41
        self.runtime.active_target = 80
        self.runtime.vehicle_activity = lambda: ("CHARGING", 6.6)
        self.notifier.observe_charging()
        self.notifier.observe_charging()
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)
        message = self.services.calls[0][2]["message"]
        self.assertIn("41%", message)
        self.assertIn("80%", message)

    async def test_command_without_positive_power_is_not_confirmed_start(self):
        self.runtime.owned = True
        self.runtime.started_at = now
        self.runtime.active_target = 80
        self.runtime.vehicle_activity = lambda: ("CHARGING_REPORTED", 0)
        self.notifier.observe_charging()
        await self.flush()
        self.assertEqual(self.services.calls, [])
        self.runtime.vehicle_activity = lambda: ("CHARGING", 6.6)
        self.notifier.observe_charging()
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)

    async def test_stale_power_readback_cannot_generate_false_start(self):
        self.runtime.owned = True
        self.runtime.started_at = now
        self.runtime.active_target = 80
        self.runtime.vehicle_activity = lambda: ("CHARGING", 6.6)
        self.telemetry_time = now.replace(hour=8)
        self.notifier.observe_charging()
        await self.flush()
        self.assertEqual(self.services.calls, [])
        self.telemetry_time = now
        self.notifier.observe_charging()
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)

    async def test_auto_start_includes_monday_target_ready_by_and_soc(self):
        self.runtime.auto.owned = True
        self.runtime.auto.owned_day = "monday"
        self.runtime.auto.owned_target = 100
        self.runtime.auto.session_start_soc = 41
        self.runtime.auto.owned_deadline = datetime(
            2026, 11, 23, 7, 0, tzinfo=timezone.utc
        )
        self.runtime.vehicle_activity = lambda: ("CHARGING", 6.5)
        self.notifier.observe_charging()
        await self.flush()
        message = self.services.calls[0][2]["message"]
        self.assertIn("Monday", message)
        self.assertIn("41%", message)
        self.assertIn("100%", message)
        self.assertIn("Ready by", message)

    async def test_soc_kwh_is_estimate_and_no_false_meter_accuracy(self):
        self.assertAlmostEqual(env["battery_energy"](40, 80), 27.4, places=1)
        self.assertIsNone(env["battery_energy"](None, 80))
        self.assertIsNone(env["battery_energy"](80, 40))
        self.notifier.charging_ended(
            automatic=True, session_id="Monday 2026-11-23",
            start_soc=40, end_soc=78, target=80, status="STOPPED",
            reason="Scheduled ready-by deadline reached",
        )
        await self.flush()
        message = self.services.calls[0][2]["message"]
        self.assertIn("Target not reached", message)
        self.assertIn("~26.0 kWh added", message)
        self.assertLess(len(message), 135)

    async def test_99_percent_geely_balance_does_not_claim_verified_100(self):
        self.notifier.charging_ended(
            automatic=True, session_id="Mon:100",
            start_soc=41, end_soc=99, target=100, status="COMPLETED",
            reason="Geely ended its balancing session",
        )
        await self.flush()
        message = self.services.calls[0][2]["message"]
        self.assertIn("100% target not verified", message)
        self.assertNotIn("Target reached", message)

    async def test_control_toggles_are_pushed_once_only_when_changed(self):
        self.entry.options["automatic_charging_enabled"] = True
        self.entry.options["emergency_stop"] = True
        self.entry.options["weekly_schedule"] = {
            "monday": {"enabled": True}
        }
        self.notifier.check_control_changes()
        await self.flush()
        messages = [x[2]["message"] for x in self.services.calls]
        self.assertEqual(len(messages), 3)
        self.assertTrue(any("Emergency STOP set ON" in x for x in messages))
        self.assertTrue(any("Monday charging schedule set ON" in x for x in messages))
        self.notifier.check_control_changes()
        await self.flush()
        self.assertEqual(len(self.services.calls), 3)

    async def test_climate_start_and_stop_differ_in_reported_confirmations(self):
        settings = {
            "temperature": 16, "driver_seat": "Vent High",
            "passenger_seat": "Vent High", "steering_heat": False
        }
        self.notifier.climate_event(
            key="linked:monday:2026-11-23", action="on",
            kind="linked", setting=settings,
            vehicle_state="off", success=True
        )
        self.notifier.climate_event(
            key="linked:monday:2026-11-23", action="off",
            kind="linked", vehicle_state="off", success=True
        )
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)
        self.assertIn("feedback pending", self.services.calls[0][2]["message"])


    async def test_normal_80_finish_single_push_and_no_false_geely_attribution(self):
        for status in ("STOPPED", "COMPLETED"):
            self.notifier.charging_ended(
                automatic=True, session_id="normal-80", start_soc=42,
                end_soc=80, target=80, status=status,
                reason="Verified charging stopped: Scheduled battery target reached",
            )
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)
        notice = self.services.calls[0][2]
        self.assertIn("finished", notice["title"])
        self.assertIn("42% → 80%", notice["message"])
        self.assertNotIn("verified", notice["message"].lower())
        self.assertNotIn("Ended by Geely", notice["message"])

    async def test_unconfirmed_public_release_is_not_completion(self):
        self.notifier.charging_ended(
            automatic=True, session_id="released", start_soc=42,
            end_soc=80, target=80, status="BLOCKED",
            reason="Public mode enabled; session released",
        )
        await self.flush()
        self.assertEqual(len(self.services.calls), 0)

    async def test_100_percent_finish_is_short_and_identifies_geely(self):
        self.notifier.charging_ended(
            automatic=True, session_id="Mon100", start_soc=42, end_soc=100,
            target=100, status="COMPLETED",
            reason="Geely ended the full charge balancing session",
        )
        await self.flush()
        notice = self.services.calls[0][2]
        self.assertIn("42% → 100%", notice["message"])
        self.assertIn("Target reached", notice["message"])
        self.assertIn("Ended by Geely", notice["message"])
        self.assertLess(len(notice["message"]), 135)

    async def test_scheduled_climate_off_failure_alerts_once(self):
        for _ in range(2):
            self.notifier.climate_event(
                key="Monday", action="off", kind="linked",
                vehicle_state="heat_cool", success=False,
            )
        await self.flush()
        self.assertEqual(len(self.services.calls), 1)
        self.assertIn("OFF not confirmed", self.services.calls[0][2]["message"])


if __name__ == "__main__":
    unittest.main()
