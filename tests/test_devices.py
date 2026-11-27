"""Tests for the grouping of entities into sub-devices."""

import re

import pytest

from custom_components.alfen_wallbox import (
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
    text,
)
from custom_components.alfen_wallbox.devices import (
    CONFIGURATION,
    DIAGNOSTICS,
    LOAD_BALANCING,
    MAIN,
    METER,
    NETWORK,
    SCHEDULE,
    SUB_DEVICES,
    device_group,
    entity_key,
)


def test_entity_key():
    """The key is the part of the unique ID after the device ID."""
    assert entity_key("alfen_x-voltage_l1_socket_1", "alfen_x") == "voltage_l1_socket_1"
    assert entity_key("alfen_x_charge_control", "alfen_x") == "charge_control"
    assert entity_key(None, "alfen_x") == ""


@pytest.mark.parametrize(
    ("key", "category", "group"),
    [
        ("sensor", None, MAIN),
        ("status_socket_1", None, MAIN),
        ("active_power_total_socket_1", None, MAIN),
        ("charge_control", None, MAIN),
        ("session_energy", None, MAIN),
        ("solar_charging_power", None, MAIN),
        ("pause_charging", None, MAIN),
        ("schedule_monday", None, SCHEDULE),
        ("charging_schedule_enabled", None, SCHEDULE),
        ("schedule_slot_start", "config", SCHEDULE),
        ("add_schedule_slot", None, SCHEDULE),
        ("voltage_l1_socket_1", None, METER),
        ("current_n_socket_2", None, METER),
        ("frequency_socket_1", None, METER),
        ("smart_meter_power_real_sum", None, LOAD_BALANCING),
        ("solar_power", None, LOAD_BALANCING),
        ("lb_solar_charging_mode", "config", LOAD_BALANCING),
        ("active_load_balancing", "config", LOAD_BALANCING),
        ("wifi_ssid", None, NETWORK),
        ("comm_ip_address_1", None, NETWORK),
        ("ocpp_wired_ocpp_send_timeout", "config", NETWORK),
        ("Protocol Version", None, NETWORK),
        ("comm_car_cp_voltage_high_socket_1", None, DIAGNOSTICS),
        ("firmware_version", None, DIAGNOSTICS),
        ("socket2.2_max_current", None, DIAGNOSTICS),
        ("main_normal_max_current_socket_1", None, MAIN),
        ("license_scn", "diagnostic", DIAGNOSTICS),
        ("reboot_wallbox", "config", DIAGNOSTICS),
        ("auth_mode", "config", CONFIGURATION),
        ("price_other_description", None, CONFIGURATION),
        ("max_station_current", "config", CONFIGURATION),
        # Same key: read-only value -> diagnostics, setting -> configuration
        ("main_external_max_current_socket_1", None, DIAGNOSTICS),
        ("main_external_max_current_socket_1", "config", CONFIGURATION),
        ("unknown_new_value", None, MAIN),
        ("unknown_new_setting", "config", CONFIGURATION),
    ],
)
def test_device_group(key, category, group):
    """Entities are grouped by topic, then by entity category."""
    assert device_group(key, category) == group


def test_main_device_keeps_only_everyday_entities():
    """Described entities left on the main device are the charging essentials."""
    descriptions = [
        *sensor.ALFEN_SENSOR_TYPES,
        *sensor.ALFEN_SENSOR_DUAL_SOCKET_TYPES,
        *binary_sensor.ALFEN_BINARY_SENSOR_TYPES,
        *number.ALFEN_NUMBER_TYPES,
        *number.ALFEN_NUMBER_DUAL_SOCKET_TYPES,
        *select.ALFEN_SELECT_TYPES,
        *select.ALFEN_SELECT_DUAL_SOCKET_TYPES,
        *switch.ALFEN_SWITCH_TYPES,
        *button.ALFEN_BUTTON_TYPES,
        *text.ALFEN_TEXT_TYPES,
    ]
    on_main = {
        description.key
        for description in descriptions
        if device_group(
            description.key,
            description.entity_category.value if description.entity_category else None,
        )
        == MAIN
    }
    allowed = re.compile(
        r"^(status|active_power_total|meter_reading|custom_tag|main_normal_max_current)"
        r"_socket_\d$|^custom_transaction_socket_\d_|^(auth_log(in|out)|enable_boost_mode|"
        r"stop_boost_mode|pause_charging|resume_charging|export_charging_history)$"
    )
    assert {key for key in on_main if not allowed.search(key)} == set()
    assert SUB_DEVICES.keys() == {
        SCHEDULE,
        METER,
        LOAD_BALANCING,
        NETWORK,
        CONFIGURATION,
        DIAGNOSTICS,
    }
