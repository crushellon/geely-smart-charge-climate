"""Constants for the passive Geely charge preview."""

DOMAIN = "geely_smart_charge_climate"
CONF_BATTERY_ENTITY = "battery_entity"
CONF_CHARGING_SWITCH = "charging_switch"
CONF_CHARGING_POWER = "charging_power"
CONF_CHARGER_RATED_KW = "charger_rated_kw"
DEFAULT_CHARGER_RATED_KW = 7.0
DEFAULT_EFFECTIVE_KW = 6.5
INITIAL_EFFICIENCY = DEFAULT_EFFECTIVE_KW / DEFAULT_CHARGER_RATED_KW
DEFAULT_USABLE_CAPACITY_KWH = 68.39  # EX5 preview only
