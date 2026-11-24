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


def charger_fields(values):
    """Generic optional AC power sensor; no charger is required."""
    fields = {
        vol.Required("charger_assist_enabled", default=values.get("charger_assist_enabled", False)): bool,
        vol.Required("charger_exclusive_confirmed", default=values.get("charger_exclusive_confirmed", False)): bool,
    }
    selected = values.get("charger_power_entity")
    key = (vol.Optional("charger_power_entity", default=selected)
           if selected else vol.Optional("charger_power_entity"))
    fields[key] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power"))
    return fields


def validate_charger(hass, values):
    if not values.get("charger_assist_enabled"):
        return None
    if not values.get("charger_exclusive_confirmed"):
        return "charger_exclusive_required"
    source = values.get("charger_power_entity")
    state = hass.states.get(source) if source else None
    if state is None or state.attributes.get("unit_of_measurement") not in ("W", "kW"):
        return "charger_power_required"
    return None


class ChargerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        values = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            problem = validate_charger(self.hass, user_input)
            if problem is None:
                # Preserve all weekly schedules, profiles and session metadata.
                return self.async_create_entry(title="", data={
                    **entry.options, **user_input,
                    "charger_power_entity": user_input.get("charger_power_entity"),
                })
            errors["base"] = problem
            values.update(user_input)
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(charger_fields(values)), errors=errors
        )


class GeelySmartChargeClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Select one Geely source and the charger's nominal input power."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ChargerOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None):
        """Prefill Geely entities and a standard 7 kW charger."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors = {}
        if user_input is not None:
            problem = validate_sources(self.hass, user_input) or validate_charger(self.hass, user_input)
            if problem is None:
                rate = user_input.get(CONF_CHARGER_RATED_KW, DEFAULT_CHARGER_RATED_KW)
                if not 1 <= rate <= 22:
                    problem = "invalid_charger_rate"
            if problem is None:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Geely Smart Charge & Climate",
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
                **charger_fields(values),
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

