"""Geely EX5 comfort commands for manual buttons and live schedules.

Each actuator is checked before an actual service call. The owner/controller
handles manual 30-minute expiry, repeat actions and restart recovery; this
adapter only applies or turns OFF vehicle climate/seats/steering.
"""
import asyncio
import logging

from .comfort import get_value
from .comfort_display import get_seat_mode

_LOGGER = logging.getLogger(__name__)


def geely_climate_entities(battery_entity):
    """Derive Geely Connect entities from the selected vehicle sensor."""
    if (not battery_entity.startswith("sensor.")
            or not battery_entity.endswith("_battery")):
        return {}
    stem = battery_entity[len("sensor."):-len("_battery")]
    return {
        "climate": f"climate.{stem}_climate",
        "driver_heat": f"select.{stem}_seat_heat_driver",
        "passenger_heat": f"select.{stem}_seat_heat_passenger",
        "driver_vent": f"select.{stem}_seat_vent_driver",
        "passenger_vent": f"select.{stem}_seat_vent_passenger",
        "steering": f"switch.{stem}_steering_wheel_heat",
    }


class ManualClimateController:
    """Apply real manual climate; owner enforces expiry outside this adapter."""

    def __init__(self, hass, entry, notify):
        self.hass = hass
        self.entry = entry
        self.notify = notify
        self.entities = geely_climate_entities(entry.data["battery_entity"])
        self.status = "IDLE"
        self.message = "Manual cabin climate ready"
        self._lock = asyncio.Lock()

    def _reported_off(self, entity):
        state = self.hass.states.get(entity) if entity else None
        return state is not None and str(state.state).lower() == "off"

    def off_confirmed(self):
        """Every EX5 comfort actuator must report OFF, not only the cabin."""
        return bool(self.entities) and all(
            self._reported_off(entity) for entity in self.entities.values()
        )

    async def _request(self, domain, service, entity, *, skip_off=False, **data):
        state = self.hass.states.get(entity) if entity else None
        if state is None or state.state in ("unknown", "unavailable"):
            return False
        # Only skip redundant OFF commands during activation. Shutdown
        # always sends explicit OFF, even when cached telemetry says OFF.
        if skip_off and self._reported_off(entity):
            return True
        for attempt in range(3):
            try:
                await self.hass.services.async_call(
                    domain, service, {"entity_id": entity, **data}, blocking=True,
                )
            except Exception as exc:
                # This exact Geely rejection means the previous vehicle
                # request is still executing. Retry only this known transient
                # condition; do not blindly resend unrelated failures.
                if ("last request has not yet been executed" in str(exc).lower()
                        and attempt < 2):
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                _LOGGER.exception("Geely climate command failed for %s", entity)
                # Even a failed response may leave a prior request executing.
                await asyncio.sleep(3)
                return False
            # A cloud acknowledgement is not execution. Pace every write,
            # including each individual seat mode and steering command.
            await asyncio.sleep(3)
            return True
        return False

    async def _seat(self, side, setting, *, activating=False):
        heat = self.entities[f"{side}_heat"]
        vent = self.entities[f"{side}_vent"]
        mode, _, level = setting.partition(" ")
        if mode == "Heat" and level in ("Low", "Medium", "High"):
            opposite = await self._request(
                "select", "select_option", vent, option="Off", skip_off=activating
            )
            return opposite and await self._request("select", "select_option", heat, option=level)
        if mode == "Vent" and level in ("Low", "Medium", "High"):
            opposite = await self._request(
                "select", "select_option", heat, option="Off", skip_off=activating
            )
            return opposite and await self._request("select", "select_option", vent, option=level)
        left = await self._request("select", "select_option", heat, option="Off", skip_off=activating)
        right = await self._request("select", "select_option", vent, option="Off", skip_off=activating)
        # BOTH heating and ventilation must report a successful OFF
        # service request; a missing seat control is not proof of shutdown.
        return left and right

    async def apply_scheduled(self, settings):
        """Apply one approved scheduled comfort session.

        Serialises with manually requested climate so seat/steering commands
        cannot interleave. Neither method controls the charging switch.
        """
        async with self._lock:
            climate = self.entities.get("climate")
            if not climate:
                return False
            main = await self._request(
                "climate", "set_temperature", climate,
                temperature=float(settings["temperature"]), hvac_mode="heat_cool",
            )
            if not main:
                return False
            driver = await self._seat("driver", settings["driver_seat"], activating=True)
            passenger = await self._seat("passenger", settings["passenger_seat"], activating=True)
            wheel = await self._request(
                "switch", "turn_on" if settings["steering_heat"] else "turn_off",
                self.entities["steering"], skip_off=not settings["steering_heat"],
            )
            return main and driver and passenger and wheel

    async def stop_scheduled(self):
        """Turn off scheduled cabin, both seats and wheel without touching EV charging."""
        async with self._lock:
            climate = self.entities.get("climate")
            main = await self._request("climate", "turn_off", climate)
            driver = await self._seat("driver", "Off")
            passenger = await self._seat("passenger", "Off")
            wheel = await self._request("switch", "turn_off", self.entities["steering"])
            return main and driver and passenger and wheel

    async def apply(self, action):
        """Apply Cool/Warm/custom/off only when explicitly requested."""
        if action not in ("Cool", "Warm", "custom", "off"):
            raise ValueError("Unsupported manual climate action")
        async with self._lock:
            climate = self.entities.get("climate")
            if (not climate or self.hass.states.get(climate) is None):
                if action != "off":
                    self.status = "UNAVAILABLE"
                    self.message = "Geely climate entity not detected for this vehicle"
                    self.notify()
                    return False
                # Even if the main cabin entity is temporarily missing,
                # still request OFF on seat heat/vent and steering wheel.
                # The overall OFF is unconfirmed and will be retried.
            self.status = "REQUESTING"
            self.message = f"Sending manual {action} climate request"
            self.notify()
            if action == "off":
                cabin_ok = await self._request("climate", "turn_off", climate)
                driver_ok = await self._seat("driver", "Off")
                passenger_ok = await self._seat("passenger", "Off")
                wheel_ok = await self._request(
                    "switch", "turn_off", self.entities["steering"]
                )
                # Continue sending every OFF even if an earlier actuator
                # failed. The 30m owner can retry an incomplete shutdown.
                main_ok = cabin_ok and driver_ok and passenger_ok and wheel_ok
            else:
                temp = (
                    self.entry.options.get("manual_cabin_temperature", 22.0)
                    if action == "custom"
                    else get_value(self.entry.options, action.lower(), "temperature")
                )
                main_ok = await self._request(
                    "climate", "set_temperature", climate,
                    temperature=float(temp), hvac_mode="heat_cool",
                )
                if main_ok and action in ("Cool", "Warm"):
                    driver_ok = await self._seat(
                        "driver", get_seat_mode(self.entry.options, action.lower(), "driver"),
                        activating=True,
                    )
                    passenger_ok = await self._seat(
                        "passenger", get_seat_mode(self.entry.options, action.lower(), "passenger"),
                        activating=True,
                    )
                    wheel = bool(get_value(self.entry.options, action.lower(), "steering_heat"))
                    wheel_ok = await self._request(
                        "switch", "turn_on" if wheel else "turn_off",
                        self.entities["steering"], skip_off=not wheel,
                    )
                    main_ok = main_ok and driver_ok and passenger_ok and wheel_ok
            self.status = "REQUESTED" if main_ok else "ERROR"
            self.message = (
                f"Manual {action} climate commands sent; vehicle feedback pending"
                if main_ok else "Climate request failed or Geely entity unavailable"
            )
            self.notify()
            return main_ok
