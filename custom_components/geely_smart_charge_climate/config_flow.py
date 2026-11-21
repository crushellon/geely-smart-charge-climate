"""Read-only entity discovery and validation setup wizard."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CHARGING_POWER,
    CONF_CHARGING_SWITCH,
    DOMAIN,
)
from .discovery import suggested_entities, validate_sources


class GeelySmartChargeClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up a Geely observer, without issuing device commands."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Suggest Geely entities; verify same integration ownership."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors = {}
        if user_input is not None:
            problem = validate_sources(self.hass, user_input)
            if problem is None:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Geely Smart Charge & Climate (monitor only)",
                    data=user_input,
                )
            errors["base"] = problem

        defaults = suggested_entities(self.hass)
        # On retry, preserve the user's selections rather than overriding them.
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
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
