"""Pure helpers for associating Geely telemetry by entity-id stem.

Examples: sensor.my_geely_ex5_4034_battery and
switch.my_geely_ex5_4034_charging share the stem my_geely_ex5_4034.

These names are hints, not proof of ownership; the Home Assistant entity
and config-entry registries must additionally validate the match.
"""

import re

BATTERY = "battery_entity"
SWITCH = "charging_switch"
POWER = "charging_power"

PATTERNS = (
    (BATTERY, re.compile(r"^sensor\.(.+)_(?:battery|battery_level|soc)$")),
    (SWITCH, re.compile(r"^switch\.(.+)_charging$")),
    (POWER, re.compile(r"^sensor\.(.+)_charging_power$")),
)


def role_and_stem(entity_id: str) -> tuple[str, str] | None:
    """Recognise common Geely entity names, excluding ambiguous variants."""
    for role, pattern in PATTERNS:
        match = pattern.fullmatch(entity_id)
        if match and "geely" in match.group(1).lower():
            return role, match.group(1)
    return None


def unique_vehicle_mapping(entity_ids: list[str]) -> dict[str, str]:
    """Return all matched roles only if exactly one complete vehicle is found.

    Ambiguous duplicate entities or multiple distinct cars result in no guess.
    """
    groups: dict[str, dict[str, list[str]]] = {}
    for entity_id in entity_ids:
        result = role_and_stem(entity_id)
        if result is None:
            continue
        role, stem = result
        groups.setdefault(stem, {}).setdefault(role, []).append(entity_id)
    candidates = [
        group for group in groups.values()
        if len(group.get(BATTERY, [])) == 1 and len(group.get(SWITCH, [])) == 1
    ]
    if len(candidates) != 1:
        return {}
    group = candidates[0]
    return {role: matches[0] for role, matches in group.items() if len(matches) == 1}
