"""Grouping of the wallbox entities into sub-devices.

The wallbox is one main device ("Alfen Wallbox") with sub-devices linked to it
(``via_device``) for the schedule, the energy meter, solar & load balancing, the
network, the configuration and the diagnostics. Entities are assigned by the key
at the end of their unique ID; entity IDs are not affected.

Pure Python (no Home Assistant imports) so the rules can be unit tested.
"""

from __future__ import annotations

import re

MAIN = "main"
SCHEDULE = "schedule"
METER = "meter"
LOAD_BALANCING = "load_balancing"
NETWORK = "network"
CONFIGURATION = "configuration"
DIAGNOSTICS = "diagnostics"

# Sub-devices in the order they are listed, with their English name suffix
SUB_DEVICES: dict[str, str] = {
    SCHEDULE: "Charging schedule",
    METER: "Energy meter",
    LOAD_BALANCING: "Solar & load balancing",
    NETWORK: "Network",
    CONFIGURATION: "Configuration",
    DIAGNOSTICS: "Diagnostics",
}

# Everyday charging entities: stay on the main device
_MAIN_KEYS = frozenset(
    {
        "sensor",  # main status sensor
        "charging_status",
        "charging_limited_by",
        "charging_restricted",
        "charge_control",
        "charging",
        "max_charging_power",
        "solar_charging_power",
        "grid_power",
        "green_share",
        "session_green_share",
        "insights_transactions",
        "history_last_session",
        "export_charging_history",
        "enable_boost_mode",
        "stop_boost_mode",
        "pause_charging",
        "resume_charging",
        "auth_login",
        "auth_logout",
    }
)

_DIAGNOSTIC_KEYS = frozenset(
    {
        "uptime",
        "last_modify_datetime",
        "system_date_time",
        "system_date_light_savings",
        "bootups",
        "boot_reason",
        "charging_box_identifier",
        "model",
        "object_id",
        "number_of_socket",
        "firmware_version",
        "bootloader_version",
        "charge_point_vendor",
        "platform_type",
        "main_start_max_current",
        "https_api_login_status",
        "reboot_wallbox",
        "wallbox_force_update",
        "force_fetch_transaction",
        "clear_transaction",
    }
)

# (pattern, group), first match wins; matched against the lower-case key
_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), group)
    for pattern, group in (
        (r"^(status|active_power_total|meter_reading|custom_tag)_socket_\d$", MAIN),
        (r"^(session|history)_", MAIN),
        (r"^(schedule_|charging_schedule|charging_window)", SCHEDULE),
        (r"^(add_schedule_slot|replace_schedule_slots|clear_schedule_days)$", SCHEDULE),
        (r"^(refresh_charging_schedule|clear_charging_profiles)$", SCHEDULE),
        (r"^(voltage|current|frequency)_[a-z0-9]+_socket_\d$|^frequency_socket_\d$", METER),
        (r"^current_total_socket_\d$", METER),
        (r"^(smart_meter_|p1_measurements_|lb_|alb_|solar_power$)", LOAD_BALANCING),
        (r"^(active_load_balancing|load_balancing_protocol)$", LOAD_BALANCING),
        (r"^main_(static|active)_lb_", LOAD_BALANCING),
        (r"^comm_car_", DIAGNOSTICS),
        (r"^(comm_|gprs_|wifi_|proxy_|ocpp_|modbus_|bo_network_)", NETWORK),
        (r"^(heartbeat_interval|mobile_weak_signal_threshold|protocol version|cpo_name)$", NETWORK),
        (r"^(temperature|max_temperature|min_temperature)$", DIAGNOSTICS),
        (r"^(license_|manufacturer_|ui_state_|ui_error_number_|mode_3_state_)", DIAGNOSTICS),
        (r"^(power_state|main_state)_socket_\d$", DIAGNOSTICS),
        (r"^ps_connector_\d_|^socket\d\.2_max_current$", DIAGNOSTICS),
        (r"^main_(active|external|station_active)_(max|min)_current", DIAGNOSTICS),
        (r"^(auth_|price_|dp_|display_|ev_|ps_|alarm_|timzone_)", CONFIGURATION),
    )
)


def entity_key(unique_id: str | None, device_id: str | None) -> str:
    """Return the key part of an entity unique ID ("<device id>[-_]<key>")."""
    if not unique_id:
        return ""
    if device_id and unique_id.startswith(device_id):
        return unique_id[len(device_id) :].lstrip("-_")
    return unique_id


def device_group(key: str, entity_category: str | None = None) -> str:
    """Return the (sub-)device group an entity belongs to.

    ``entity_category`` is "config", "diagnostic" or None; it decides the group
    of entities that are not matched by a topic rule.
    """
    key = key.lower()
    if key in _MAIN_KEYS:
        return MAIN
    if key in _DIAGNOSTIC_KEYS:
        return DIAGNOSTICS
    for pattern, group in _RULES:
        if pattern.search(key):
            # A setting with the same key as a read-only diagnostic value
            if group == DIAGNOSTICS and entity_category == "config":
                return CONFIGURATION
            return group
    if entity_category == "config":
        return CONFIGURATION
    if entity_category == "diagnostic":
        return DIAGNOSTICS
    return MAIN
