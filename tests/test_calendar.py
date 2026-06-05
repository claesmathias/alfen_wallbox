"""Tests for the Alfen Wallbox calendar entity and schedule sensor."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.alfen_wallbox.calendar import (
    AlfenChargingScheduleCalendar,
    _profile_to_events,
    _seconds_to_time,
    async_setup_entry,
)
from custom_components.alfen_wallbox.sensor import AlfenScheduleSensor
from custom_components.alfen_wallbox.button import ALFEN_BUTTON_TYPES, AlfenButton
from custom_components.alfen_wallbox.const import CLEAR_CHARGING_PROFILES


# ---------------------------------------------------------------------------
# Sample OCPP profiles for reuse across tests
# ---------------------------------------------------------------------------

DAILY_PROFILE = {
    "chargingProfileId": -19930828,
    "stackLevel": 0,
    "chargingProfileKind": "Recurring",
    "recurrencyKind": "DAILY",
    "chargingSchedule": {
        "chargingRateUnit": "A",
        "duration": 7200,
        "chargingSchedulePeriod": [
            {"startPeriod": 28800, "limit": 16, "numberPhases": 3},
            {"startPeriod": 36000, "limit": 0, "numberPhases": 3},
        ],
    },
}

WEEKLY_PROFILE = {
    "chargingProfileId": -19930828,
    "stackLevel": 0,
    "chargingProfileKind": "Recurring",
    "recurrencyKind": "WEEKLY",
    "daysOfWeek": ["Monday", "Wednesday"],
    "chargingSchedule": {
        "chargingRateUnit": "A",
        "duration": 3600,
        "chargingSchedulePeriod": [
            {"startPeriod": 32400, "limit": 10, "numberPhases": 1},
            {"startPeriod": 36000, "limit": 0, "numberPhases": 1},
        ],
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(name="mock_coordinator")
def mock_coordinator_fixture():
    """Return a lightweight mock coordinator backed by a mock device."""
    coordinator = MagicMock()
    coordinator.device = MagicMock()
    coordinator.device.id = "alfen_test"
    coordinator.device.name = "Test Wallbox"
    coordinator.device.log_id = "Test Wallbox@192.168.1.100"
    coordinator.device.info = MagicMock()
    coordinator.device.info.model = "Test Model"
    coordinator.device.info.firmware_version = "1.0.0"
    coordinator.device.get_charging_profiles = AsyncMock(return_value=[])
    coordinator.device.clear_charging_profiles = AsyncMock()
    coordinator.device.charging_profiles = []
    return coordinator


@pytest.fixture(name="calendar_entity")
def calendar_entity_fixture(mock_config_entry: MockConfigEntry, mock_coordinator):
    """Return an AlfenChargingScheduleCalendar with an injected coordinator."""
    mock_config_entry.runtime_data = mock_coordinator
    entity = AlfenChargingScheduleCalendar(mock_config_entry)
    return entity


@pytest.fixture(name="schedule_sensor")
def schedule_sensor_fixture(mock_config_entry: MockConfigEntry, mock_coordinator):
    """Return an AlfenScheduleSensor with an injected coordinator."""
    mock_config_entry.runtime_data = mock_coordinator
    sensor = AlfenScheduleSensor(mock_config_entry)
    return sensor


# ---------------------------------------------------------------------------
# _seconds_to_time helper
# ---------------------------------------------------------------------------


def test_seconds_to_time_midnight():
    """0 seconds maps to 00:00:00."""
    assert _seconds_to_time(0) == datetime.time(0, 0, 0)


def test_seconds_to_time_8am():
    """28800 seconds (8 h) maps to 08:00:00."""
    assert _seconds_to_time(28800) == datetime.time(8, 0, 0)


def test_seconds_to_time_10am():
    """36000 seconds (10 h) maps to 10:00:00."""
    assert _seconds_to_time(36000) == datetime.time(10, 0, 0)


# ---------------------------------------------------------------------------
# _profile_to_events — DAILY
# ---------------------------------------------------------------------------


def test_daily_profile_generates_event_for_each_day():
    """DAILY profile yields one event per day in the requested range."""
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 3, tzinfo=datetime.UTC)

    events = _profile_to_events(DAILY_PROFILE, start, end)

    assert len(events) == 3


def test_daily_profile_event_summary():
    """Summary is 'Charging {power} kW'."""
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)

    events = _profile_to_events(DAILY_PROFILE, start, end)

    assert len(events) == 1
    assert events[0].summary == "Charging 11.0 kW"  # 16A × 3ph × 230V / 1000


def test_daily_profile_event_start_end_times():
    """Event start/end match the schedule periods converted to wall-clock times."""
    start = datetime.datetime(2024, 1, 5, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 5, tzinfo=datetime.UTC)

    events = _profile_to_events(DAILY_PROFILE, start, end)

    assert len(events) == 1
    evt = events[0]
    assert evt.start == datetime.datetime(2024, 1, 5, 8, 0, 0, tzinfo=datetime.UTC)
    assert evt.end == datetime.datetime(2024, 1, 5, 10, 0, 0, tzinfo=datetime.UTC)


def test_daily_profile_event_description():
    """Description contains time range and phase count."""
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)

    events = _profile_to_events(DAILY_PROFILE, start, end)

    assert "08:00" in events[0].description
    assert "10:00" in events[0].description
    assert "3 phase" in events[0].description


def test_daily_profile_no_events_when_range_empty():
    """Single-day range with exactly one day still produces one event."""
    start = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)

    events = _profile_to_events(DAILY_PROFILE, start, end)

    assert len(events) == 1


# ---------------------------------------------------------------------------
# _profile_to_events — WEEKLY
# ---------------------------------------------------------------------------


def test_weekly_profile_only_on_matching_weekdays():
    """WEEKLY profile only generates events on the specified days of the week."""
    # 2024-01-01 is a Monday; 2024-01-07 is a Sunday
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 7, tzinfo=datetime.UTC)

    events = _profile_to_events(WEEKLY_PROFILE, start, end)

    # Monday (2024-01-01) and Wednesday (2024-01-03) → 2 events
    assert len(events) == 2
    dates = {evt.start.date() for evt in events}
    assert datetime.date(2024, 1, 1) in dates   # Monday
    assert datetime.date(2024, 1, 3) in dates   # Wednesday


def test_weekly_profile_no_events_on_wrong_days():
    """WEEKLY profile yields no events when the range contains none of the specified days."""
    # 2024-01-06 = Saturday, 2024-01-07 = Sunday (neither Monday nor Wednesday)
    start = datetime.datetime(2024, 1, 6, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 7, tzinfo=datetime.UTC)

    events = _profile_to_events(WEEKLY_PROFILE, start, end)

    assert events == []


def test_weekly_profile_event_summary():
    """Weekly profile events have the correct charging summary."""
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)  # Monday
    end = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)

    events = _profile_to_events(WEEKLY_PROFILE, start, end)

    assert len(events) == 1
    assert events[0].summary == "Charging 2.3 kW"  # 10A × 1ph × 230V / 1000


# ---------------------------------------------------------------------------
# Midnight-wrap events (end_time < start_time)
# ---------------------------------------------------------------------------


def test_midnight_wrap_event_spans_midnight():
    """When end period < start period the event must span into the next day."""
    # 23:00 → 01:00  (next day)
    profile = {
        "chargingProfileId": 1,
        "recurrencyKind": "DAILY",
        "chargingSchedule": {
            "duration": 7200,
            "chargingSchedulePeriod": [
                {"startPeriod": 82800, "limit": 6, "numberPhases": 1},  # 23:00
                {"startPeriod": 3600, "limit": 0, "numberPhases": 1},   # 01:00 (< 23:00)
            ],
        },
    }
    start = datetime.datetime(2024, 3, 10, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 3, 10, tzinfo=datetime.UTC)

    events = _profile_to_events(profile, start, end)

    assert len(events) == 1
    evt = events[0]
    assert evt.end > evt.start
    # End should be the following day
    assert evt.end.date() == datetime.date(2024, 3, 11)


# ---------------------------------------------------------------------------
# CalendarEntity – event property
# ---------------------------------------------------------------------------


def test_calendar_event_property_returns_none_when_no_profiles(calendar_entity):
    """event property is None when no profiles are loaded."""
    calendar_entity._profiles = []
    assert calendar_entity.event is None


def test_calendar_event_property_returns_active_event(calendar_entity):
    """event property returns the event that is currently active."""
    # Inject a profile where the schedule covers the entire day so "now" is always inside
    all_day_profile = {
        "chargingProfileId": 1,
        "recurrencyKind": "DAILY",
        "chargingSchedule": {
            "duration": 86400,
            "chargingSchedulePeriod": [
                {"startPeriod": 0, "limit": 16, "numberPhases": 3},
                {"startPeriod": 86400, "limit": 0, "numberPhases": 3},
            ],
        },
    }
    calendar_entity._profiles = [all_day_profile]
    evt = calendar_entity.event
    assert evt is not None
    assert evt.summary == "Charging 11.0 kW"


def test_calendar_event_property_returns_none_outside_schedule(calendar_entity):
    """event property is None when 'now' is outside all schedule windows.

    We use a tiny window in the far past so it will never be active.
    """
    past_profile = {
        "chargingProfileId": 1,
        "recurrencyKind": "DAILY",
        "chargingSchedule": {
            "duration": 1,
            "chargingSchedulePeriod": [
                {"startPeriod": 0, "limit": 16, "numberPhases": 3},
                {"startPeriod": 1, "limit": 0, "numberPhases": 3},
            ],
        },
    }
    calendar_entity._profiles = [past_profile]
    # The window is 00:00:00 UTC – 00:00:01 UTC; almost certainly not active right now.
    # If by extreme chance the test runs exactly at midnight UTC, skip it.
    now = datetime.datetime.now(datetime.UTC)
    if now.hour == 0 and now.minute == 0 and now.second == 0:
        pytest.skip("Skipping extremely rare midnight edge case")

    assert calendar_entity.event is None


# ---------------------------------------------------------------------------
# CalendarEntity – async_get_events
# ---------------------------------------------------------------------------


async def test_calendar_async_get_events_daily(
    hass: HomeAssistant,
    calendar_entity: AlfenChargingScheduleCalendar,
    mock_coordinator,
) -> None:
    """async_get_events returns one event per day for a DAILY profile."""
    mock_coordinator.device.get_charging_profiles = AsyncMock(return_value=[DAILY_PROFILE])

    start = datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 6, 7, tzinfo=datetime.UTC)

    events = await calendar_entity.async_get_events(hass, start, end)

    assert len(events) == 7
    for evt in events:
        assert evt.summary == "Charging 11.0 kW"


async def test_calendar_async_get_events_weekly(
    hass: HomeAssistant,
    calendar_entity: AlfenChargingScheduleCalendar,
    mock_coordinator,
) -> None:
    """async_get_events returns events only on matching weekdays for WEEKLY profile."""
    mock_coordinator.device.get_charging_profiles = AsyncMock(return_value=[WEEKLY_PROFILE])

    # Week of 2024-01-01 (Mon) – 2024-01-07 (Sun)
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 7, tzinfo=datetime.UTC)

    events = await calendar_entity.async_get_events(hass, start, end)

    # Monday (Jan 1) and Wednesday (Jan 3) = 2 events
    assert len(events) == 2


async def test_calendar_async_get_events_empty_when_no_profiles(
    hass: HomeAssistant,
    calendar_entity: AlfenChargingScheduleCalendar,
    mock_coordinator,
) -> None:
    """async_get_events returns empty list when there are no profiles."""
    mock_coordinator.device.get_charging_profiles = AsyncMock(return_value=[])

    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)
    end = datetime.datetime(2024, 1, 7, tzinfo=datetime.UTC)

    events = await calendar_entity.async_get_events(hass, start, end)

    assert events == []


async def test_calendar_async_get_events_multiple_profiles(
    hass: HomeAssistant,
    calendar_entity: AlfenChargingScheduleCalendar,
    mock_coordinator,
) -> None:
    """async_get_events aggregates events from all profiles."""
    mock_coordinator.device.get_charging_profiles = AsyncMock(
        return_value=[DAILY_PROFILE, WEEKLY_PROFILE]
    )

    # Single Monday
    start = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)  # Monday
    end = datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)

    events = await calendar_entity.async_get_events(hass, start, end)

    # DAILY produces 1 event; WEEKLY also produces 1 event (Monday matches)
    assert len(events) == 2


# ---------------------------------------------------------------------------
# CalendarEntity – _async_refresh_profiles
# ---------------------------------------------------------------------------


async def test_calendar_async_update_fetches_profiles(
    calendar_entity: AlfenChargingScheduleCalendar,
    mock_coordinator,
) -> None:
    """_async_refresh_profiles populates _profiles from the device."""
    mock_coordinator.device.get_charging_profiles = AsyncMock(return_value=[DAILY_PROFILE])

    await calendar_entity._async_refresh_profiles()

    assert calendar_entity._profiles == [DAILY_PROFILE]


async def test_calendar_async_update_handles_exception(
    calendar_entity: AlfenChargingScheduleCalendar,
    mock_coordinator,
) -> None:
    """_async_refresh_profiles resets profiles to [] on exception."""
    mock_coordinator.device.get_charging_profiles = AsyncMock(side_effect=Exception("API down"))

    await calendar_entity._async_refresh_profiles()

    assert calendar_entity._profiles == []


# ---------------------------------------------------------------------------
# CalendarEntity – setup
# ---------------------------------------------------------------------------


async def test_calendar_setup_entry_adds_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_alfen_device,
) -> None:
    """async_setup_entry registers exactly one calendar entity."""
    from custom_components.alfen_wallbox.coordinator import AlfenCoordinator

    mock_config_entry.add_to_hass(hass)
    coordinator = AlfenCoordinator(hass, mock_config_entry)
    coordinator.device = mock_alfen_device
    mock_alfen_device.get_charging_profiles = AsyncMock(return_value=[])
    mock_config_entry.runtime_data = coordinator

    entities = []

    def add_entities(new_entities):
        entities.extend(new_entities)

    await async_setup_entry(hass, mock_config_entry, add_entities)

    assert len(entities) == 1
    assert isinstance(entities[0], AlfenChargingScheduleCalendar)


# ---------------------------------------------------------------------------
# AlfenScheduleSensor – native_value
# ---------------------------------------------------------------------------


def test_schedule_sensor_native_value_zero_when_no_profiles(schedule_sensor, mock_coordinator):
    """native_value is 0 when no profiles are cached."""
    mock_coordinator.device.charging_profiles = []
    assert schedule_sensor.native_value == 0


def test_schedule_sensor_native_value_weekly_two_days(schedule_sensor, mock_coordinator):
    """WEEKLY profile with Mon+Wed → 2 scheduled days."""
    mock_coordinator.device.charging_profiles = [WEEKLY_PROFILE]
    assert schedule_sensor.native_value == 2


def test_schedule_sensor_native_value_daily_covers_all_days(schedule_sensor, mock_coordinator):
    """DAILY profile applies to all 7 days."""
    mock_coordinator.device.charging_profiles = [DAILY_PROFILE]
    assert schedule_sensor.native_value == 7


def test_schedule_sensor_native_value_eve_connect_one_day(schedule_sensor, mock_coordinator):
    """A single per-day Eve Connect profile (Monday anchor) counts as 1 scheduled day."""
    eve_monday = {
        "chargingProfileId": 234202401,
        "chargingProfileKind": "Recurring",
        "recurrencyKind": "Weekly",
        "startSchedule": "2024-04-01T00:00:00Z",  # Monday
        "startPeriod": [0, 33300, 64800],
        "limit": [0.0, 15.9, 0.0],
        "numberPhases": [1, 3, 3],
    }
    mock_coordinator.device.charging_profiles = [eve_monday]
    assert schedule_sensor.native_value == 1


# ---------------------------------------------------------------------------
# AlfenScheduleSensor – extra_state_attributes
# ---------------------------------------------------------------------------


def test_schedule_sensor_extra_state_attributes_empty(schedule_sensor, mock_coordinator):
    """extra_state_attributes schedule dict is empty when no profiles cached."""
    mock_coordinator.device.charging_profiles = []
    assert schedule_sensor.extra_state_attributes == {"schedule": {}}


def test_schedule_sensor_extra_state_attributes_daily(schedule_sensor, mock_coordinator):
    """DAILY profile produces entries for all 7 day names."""
    mock_coordinator.device.charging_profiles = [DAILY_PROFILE]
    attrs = schedule_sensor.extra_state_attributes
    schedule = attrs["schedule"]

    assert len(schedule) == 7
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        assert day in schedule
        assert schedule[day]["start"] == "08:00"
        assert schedule[day]["end"] == "10:00"
        assert schedule[day]["current_a"] == 16
        assert schedule[day]["phases"] == 3


def test_schedule_sensor_extra_state_attributes_weekly(schedule_sensor, mock_coordinator):
    """WEEKLY profile produces entries only for the matching days."""
    mock_coordinator.device.charging_profiles = [WEEKLY_PROFILE]
    attrs = schedule_sensor.extra_state_attributes
    schedule = attrs["schedule"]

    assert set(schedule.keys()) == {"monday", "wednesday"}
    assert schedule["monday"]["start"] == "09:00"
    assert schedule["monday"]["end"] == "10:00"
    assert schedule["monday"]["current_a"] == 10
    assert schedule["monday"]["phases"] == 1


def test_schedule_sensor_extra_state_attributes_multiple_profiles(schedule_sensor, mock_coordinator):
    """DAILY and WEEKLY profiles combined — DAILY already covers all days."""
    mock_coordinator.device.charging_profiles = [DAILY_PROFILE, WEEKLY_PROFILE]
    attrs = schedule_sensor.extra_state_attributes
    # DAILY covers all 7; WEEKLY covers Mon+Wed which are already in DAILY
    assert len(attrs["schedule"]) == 7


def test_schedule_sensor_extra_state_attributes_ignores_zero_limit(schedule_sensor, mock_coordinator):
    """Profiles with no active period (all limit==0) produce no schedule entries."""
    off_profile = {
        "recurrencyKind": "DAILY",
        "chargingSchedule": {
            "duration": 3600,
            "chargingSchedulePeriod": [
                {"startPeriod": 0, "limit": 0, "numberPhases": 1},
            ],
        },
    }
    mock_coordinator.device.charging_profiles = [off_profile]
    assert schedule_sensor.extra_state_attributes == {"schedule": {}}


# ---------------------------------------------------------------------------
# Clear Charging Profiles Button
# ---------------------------------------------------------------------------


async def test_clear_charging_profiles_button_exists():
    """ALFEN_BUTTON_TYPES contains a clear_charging_profiles button."""
    keys = [desc.key for desc in ALFEN_BUTTON_TYPES]
    assert "clear_charging_profiles" in keys


async def test_clear_charging_profiles_button_description():
    """Clear charging profiles button has correct description fields."""
    desc = next(d for d in ALFEN_BUTTON_TYPES if d.key == "clear_charging_profiles")
    assert desc.url_action == CLEAR_CHARGING_PROFILES
    assert desc.json_data is None


async def test_clear_charging_profiles_button_press(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_alfen_device,
) -> None:
    """Pressing the clear charging profiles button calls device.clear_charging_profiles."""
    from custom_components.alfen_wallbox.coordinator import AlfenCoordinator

    mock_config_entry.add_to_hass(hass)
    coordinator = AlfenCoordinator(hass, mock_config_entry)
    coordinator.device = mock_alfen_device
    mock_alfen_device.clear_charging_profiles = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    desc = next(d for d in ALFEN_BUTTON_TYPES if d.key == "clear_charging_profiles")
    button = AlfenButton(mock_config_entry, desc)

    await button.async_press()

    mock_alfen_device.clear_charging_profiles.assert_called_once()
