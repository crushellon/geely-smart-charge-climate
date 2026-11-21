"""Registry-grounded Geely entity discovery and validation.

Match naming conventions (including the tested EX5 entity IDs), but only
suggest entities after verifying common Geely Connect config-entry ownership.
Never silently select from two vehicles.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_BATTERY_ENTITY, CONF_CHARGING_POWER, CONF_CHARGING_SWITCH
from .matching import role_and_stem, unique_vehicle_mapping

DOMAINS = {
    CONF_BATTERY_ENTITY: "sensor",
    CONF_CHARGING_SWITCH: "switch",
    CONF_CHARGING_POWER: "sensor",
}


def _geely_entry_id(hass: HomeAssistant, registered) -> str | None:
    """Confirm Geely registry ownership, not just a coincidental entity name."""
    entry_id = registered.config_entry_id
    if not entry_id:
        return None
    entry = hass.config_entries.async_get_entry(entry_id)
    integration_domain = entry.domain.lower() if entry else ""
    platform = (registered.platform or "").lower()
    if "geely" not in integration_domain and "geely" not in platform:
        return None
    return entry_id


def suggested_entities(hass: HomeAssistant) -> dict[str, str]:
    """Suggest an EX5-style entity group only when unambiguous.

    Each member must belong to the same Geely Connect config entry. Entity
    names remain editable in the setup wizard; this is never a silent bind.
    """
    registry = er.async_get(hass)
    by_entry: dict[str, list[str]] = {}
    for entity in registry.entities.values():
        if entity.disabled_by is not None:
            continue
        owner = _geely_entry_id(hass, entity)
        if owner is None or role_and_stem(entity.entity_id) is None:
            continue
        by_entry.setdefault(owner, []).append(entity.entity_id)
    candidates = [
        matched for names in by_entry.values()
        if (matched := unique_vehicle_mapping(names))
    ]
    return candidates[0] if len(candidates) == 1 else {}


def validate_sources(hass: HomeAssistant, values: dict) -> str | None:
    """Require enabled, same-vehicle Geely entities with valid domains."""
    registry = er.async_get(hass)
    owners: set[str] = set()
    selected: list[str] = []
    for role, domain in DOMAINS.items():
        entity_id = values.get(role)
        if not entity_id:
            continue
        if not entity_id.startswith(f"{domain}."):
            return "invalid_entity"
        registered = registry.async_get(entity_id)
        if registered is None or registered.disabled_by is not None:
            return "invalid_entity"
        owner = _geely_entry_id(hass, registered)
        if owner is None:
            return "not_geely"
        owners.add(owner)
        selected.append(entity_id)
    if len(owners) != 1:
        return "different_vehicles"

    # Registered sources must be from one vehicle, not two under one account.
    # Device IDs are stronger evidence when present; otherwise compare stems.
    selected_registrations = [registry.async_get(e) for e in selected]
    device_ids = {item.device_id for item in selected_registrations if item.device_id}
    if len(device_ids) > 1:
        return "different_vehicles"
    stems = {
        pair[1] for entity_id in selected
        if (pair := role_and_stem(entity_id)) is not None
    }
    if len(stems) > 1:
        return "different_vehicles"

    battery = hass.states.get(values[CONF_BATTERY_ENTITY])
    if battery and battery.state not in ("unknown", "unavailable"):
        try:
            percent = float(battery.state)
        except (ValueError, TypeError):
            return "invalid_battery"
        if not 0 <= percent <= 100:
            return "invalid_battery"
    return None


def discover_plug_entity(hass: HomeAssistant, battery_entity: str) -> str | None:
    """Find one real plug sensor on the same Geely device/config entry.

    Uses the battery entity's vehicle-specific stem as an exact match. Existing
    entries need no migration or reconfiguration, and no guessing is allowed.
    """
    registry = er.async_get(hass)
    battery = registry.async_get(battery_entity)
    if battery is None or battery.disabled_by is not None:
        return None
    owner = _geely_entry_id(hass, battery)
    if owner is None:
        return None
    if not battery_entity.startswith("sensor.") or not battery_entity.endswith("_battery"):
        return None
    stem = battery_entity[len("sensor."):-len("_battery")]
    if not stem:
        return None
    expected = f"binary_sensor.{stem}_charger_plug"
    plug = registry.async_get(expected)
    if plug is None or plug.disabled_by is not None:
        return None
    if _geely_entry_id(hass, plug) != owner:
        return None
    if battery.device_id and plug.device_id and battery.device_id != plug.device_id:
        return None
    return plug.entity_id
