"""Candidate discovery and source validation for Geely vehicle telemetry.

Entity names are only hints. Registry ownership and domains are checked at setup.
No service calls or vehicle commands are made here.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_BATTERY_ENTITY, CONF_CHARGING_POWER, CONF_CHARGING_SWITCH

# Prefer matching platform entities, but never silently bind a different vehicle.
HINTS = {
    CONF_BATTERY_ENTITY: ("_battery", "_battery_level", "_soc"),
    CONF_CHARGING_SWITCH: ("_charging",),
    CONF_CHARGING_POWER: ("_charging_power",),
}
DOMAINS = {
    CONF_BATTERY_ENTITY: "sensor",
    CONF_CHARGING_SWITCH: "switch",
    CONF_CHARGING_POWER: "sensor",
}


def suggested_entities(hass: HomeAssistant) -> dict[str, str]:
    """Suggest values only if there is exactly one unambiguous Geely group.

    This is a convenience, not a compatibility guarantee. The user confirms
    every mapping in the setup form.
    """
    registry = er.async_get(hass)
    grouped: dict[str, dict[str, list[str]]] = {}
    for entity in registry.entities.values():
        if "geely" not in entity.platform.lower() or entity.disabled_by is not None:
            continue
        if entity.config_entry_id is None:
            continue
        options = grouped.setdefault(entity.config_entry_id, {})
        for role, suffixes in HINTS.items():
            if entity.domain == DOMAINS[role] and any(
                entity.entity_id.endswith(suffix) for suffix in suffixes
            ):
                options.setdefault(role, []).append(entity.entity_id)

    valid = [
        group for group in grouped.values()
        if len(group.get(CONF_BATTERY_ENTITY, [])) == 1
        and len(group.get(CONF_CHARGING_SWITCH, [])) == 1
    ]
    if len(valid) != 1:
        return {}
    group = valid[0]
    return {
        role: values[0] for role, values in group.items() if len(values) == 1
    }


def validate_sources(hass: HomeAssistant, values: dict) -> str | None:
    """Reject missing, mismatched, or non-Geely source entities."""
    registry = er.async_get(hass)
    owners: set[str] = set()
    for role, domain in DOMAINS.items():
        entity_id = values.get(role)
        if entity_id is None:
            continue
        if not entity_id.startswith(f"{domain}."):
            return "invalid_entity"
        registered = registry.async_get(entity_id)
        if registered is None or registered.disabled_by is not None:
            return "invalid_entity"
        if "geely" not in registered.platform.lower():
            return "not_geely"
        if registered.config_entry_id is None:
            return "invalid_entity"
        owners.add(registered.config_entry_id)
    if len(owners) != 1:
        return "different_vehicles"

    battery = hass.states.get(values[CONF_BATTERY_ENTITY])
    if battery and battery.state not in ("unknown", "unavailable"):
        try:
            value = float(battery.state)
        except (ValueError, TypeError):
            return "invalid_battery"
        if not 0 <= value <= 100:
            return "invalid_battery"
    return None
