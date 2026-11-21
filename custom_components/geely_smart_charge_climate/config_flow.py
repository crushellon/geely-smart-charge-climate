"""Initial read-only setup for Geely Smart Charge & Climate."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CHARGING_POWER,
    CONF_CHARGING_SWITCH,
    DOMAIN,
)


class GeelySmartChargeClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Allow explicit source entity selection without issuing commands."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Collect Geely battery and charging entities for observation only."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Geely Smart Charge & Climate (monitor only)",
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_BATTERY_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_CHARGING_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(CONF_CHARGING_POWER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
