"""Explicit user-operated EX5 comfort, independent of scheduled climate.

This module only runs on a real button press. The charging-linked comfort
and independent climate schedules are still configuration/simulation only.
Every optional actuator is checked before issuing a service call.
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
    """Send only requested manual climate commands; no timer automation."""

    def __init__(self, hass, entry, notify):
        self.hass = hass
        self.entry = entry
        self.notify = notify
        self.entities = geely_climate_entities(entry.data["battery_entity"])
        self.status = "IDLE"
        self.message = "Manual cabin climate ready"
        self._lock = asyncio.Lock()

    async def _request(self, domain, service, entity, **data):
        state = self.hass.states.get(entity) if entity else None
        if state is None or state.state in ("unknown", "unavailable"):
            return False
        try:
            await self.hass.services.async_call(
                domain, service, {"entity_id": entity, **data}, blocking=True,
            )
        except Exception:
            _LOGGER.exception("Manual Geely climate command failed for %s", entity)
            return False
        return True

    async def _seat(self, side, setting):
        heat = self.entities[f"{side}_heat"]
        vent = self.entities[f"{side}_vent"]
        mode, _, level = setting.partition(" ")
        if mode == "Heat" and level in ("Low", "Medium", "High"):
            await self._request("select", "select_option", vent, option="Off")
            return await self._request("select", "select_option", heat, option=level)
        if mode == "Vent" and level in ("Low", "Medium", "High"):
            await self._request("select", "select_option", heat, option="Off")
            return await self._request("select", "select_option", vent, option=level)
        left = await self._request("select", "select_option", heat, option="Off")
        right = await self._request("select", "select_option", vent, option="Off")
        return left or right

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
            # Geely Connect sends asynchronous cloud commands. Leave a small
            # gap as in the original working package before seat commands.
            await asyncio.sleep(5)
            await self._seat("driver", settings["driver_seat"])
            await asyncio.sleep(2)
            await self._seat("passenger", settings["passenger_seat"])
            await self._request(
                "switch", "turn_on" if settings["steering_heat"] else "turn_off",
                self.entities["steering"],
            )
            return True

    async def stop_scheduled(self):
        """Turn off scheduled cabin, both seats and wheel without touching EV charging."""
        async with self._lock:
            climate = self.entities.get("climate")
            if not climate:
                return False
            main = await self._request("climate", "turn_off", climate)
            await asyncio.sleep(2)
            await self._seat("driver", "Off")
            await self._seat("passenger", "Off")
            await self._request("switch", "turn_off", self.entities["steering"])
            return main

    async def apply(self, action):
        """Apply Cool/Warm/custom/off only when explicitly requested."""
        if action not in ("Cool", "Warm", "custom", "off"):
            raise ValueError("Unsupported manual climate action")
        async with self._lock:
            climate = self.entities.get("climate")
            if (not climate or self.hass.states.get(climate) is None):
                self.status = "UNAVAILABLE"
                self.message = "Geely climate entity not detected for this vehicle"
                self.notify()
                return
            self.status = "REQUESTING"
            self.message = f"Sending manual {action} climate request"
            self.notify()
            if action == "off":
                main_ok = await self._request("climate", "turn_off", climate)
                await self._seat("driver", "Off")
                await self._seat("passenger", "Off")
                await self._request("switch", "turn_off", self.entities["steering"])
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
                    # Geely's climate command can take time to propagate. The
                    # original package staggered these separate cloud writes.
                    await asyncio.sleep(5)
                    await self._seat(
                        "driver", get_seat_mode(self.entry.options, action.lower(), "driver")
                    )
                    await asyncio.sleep(2)
                    await self._seat(
                        "passenger", get_seat_mode(self.entry.options, action.lower(), "passenger")
                    )
                    wheel = bool(get_value(self.entry.options, action.lower(), "steering_heat"))
                    await self._request(
                        "switch", "turn_on" if wheel else "turn_off",
                        self.entities["steering"],
                    )
            self.status = "REQUESTED" if main_ok else "ERROR"
            self.message = (
                f"Manual {action} climate commands sent; vehicle feedback pending"
                if main_ok else "Climate request failed or Geely entity unavailable"
            )
            self.notify()
