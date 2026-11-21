"""Read-only configuration wizard for Geely Smart Charge & Climate."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CHARGER_RATED_KW,
    CONF_CHARGING_POWER,
    CONF_CHARGING_SWITCH,
    DEFAULT_CHARGER_RATED_KW,
    DOMAIN,
)
from .discovery import suggested_entities, validate_sources
from .weekly_schedule import DAY_NAMES, default_schedule, validate_day


class GeelySmartChargeClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Select one Geely source and the charger's nominal input power."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Prefill Geely entities and a standard 7 kW charger."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors = {}
        if user_input is not None:
            problem = validate_sources(self.hass, user_input)
            if problem is None:
                rate = user_input.get(CONF_CHARGER_RATED_KW, DEFAULT_CHARGER_RATED_KW)
                if not 1 <= rate <= 22:
                    problem = "invalid_charger_rate"
            if problem is None:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Geely Smart Charge & Climate (monitor only)",
                    data=user_input,
                )
            errors["base"] = problem

        defaults = suggested_entities(self.hass)
        defaults[CONF_CHARGER_RATED_KW] = DEFAULT_CHARGER_RATED_KW
        values = user_input if user_input is not None else defaults

        def field(role: str, required: bool):
            if role in values:
                return (
                    vol.Required(role, default=values[role])
                    if required
                    else vol.Optional(role, default=values[role])
                )
            return vol.Required(role) if required else vol.Optional(role)

        schema = vol.Schema(
            {
                field(CONF_BATTERY_ENTITY, True): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                field(CONF_CHARGING_SWITCH, True): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                field(CONF_CHARGING_POWER, False): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_CHARGER_RATED_KW,
                    default=values.get(CONF_CHARGER_RATED_KW, DEFAULT_CHARGER_RATED_KW),
                ): vol.All(vol.Coerce(float), vol.Range(min=1, max=22)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class GeelyScheduleOptionsFlow(config_entries.OptionsFlowWithReload):
    """Edit one weekday at a time; preserve other days on each save."""

    async def async_step_init(self, user_input=None):
        """Show the seven-day schedule menu."""
        return self.async_show_menu(step_id="init", menu_options=list(DAY_NAMES))

    async def _edit_day(self, day: str, user_input=None):
        """Edit and persist one day's passive simulation configuration."""
        schedule = self.config_entry.options.get("weekly_schedule", {})
        current = {**default_schedule()[day], **schedule.get(day, {})}
        if user_input is not None:
            try:
                updated = validate_day(user_input)
            except ValueError:
                return self.async_show_form(
                    step_id=day, data_schema=self._day_schema(current),
                    errors={"base": "invalid_schedule"},
                )
            new_schedule = {**schedule, day: updated}
            return self.async_create_entry(
                data={**self.config_entry.options, "weekly_schedule": new_schedule}
            )
        return self.async_show_form(
            step_id=day, data_schema=self._day_schema(current)
        )

    @staticmethod
    def _day_schema(current):
        return vol.Schema({
            vol.Required("enabled", default=current["enabled"]): bool,
            vol.Required("target", default=current["target"]): vol.All(
                vol.Coerce(int), vol.Range(min=50, max=100)
            ),
            vol.Required("ready_time", default=current["ready_time"]): str,
        })

    async def async_step_monday(self, user_input=None):
        return await self._edit_day("monday", user_input)

    async def async_step_tuesday(self, user_input=None):
        return await self._edit_day("tuesday", user_input)

    async def async_step_wednesday(self, user_input=None):
        return await self._edit_day("wednesday", user_input)

    async def async_step_thursday(self, user_input=None):
        return await self._edit_day("thursday", user_input)

    async def async_step_friday(self, user_input=None):
        return await self._edit_day("friday", user_input)

    async def async_step_saturday(self, user_input=None):
        return await self._edit_day("saturday", user_input)

    async def async_step_sunday(self, user_input=None):
        return await self._edit_day("sunday", user_input)
