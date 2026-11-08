"""Tests for creating, editing and deleting charging slots via the calendar."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.alfen_wallbox import charging
from custom_components.alfen_wallbox.alfen import AlfenDevice
from custom_components.alfen_wallbox.calendar import AlfenChargingScheduleCalendar
from custom_components.alfen_wallbox.charging import TimeSlot

TZ = datetime.UTC
EVERY_DAY = TimeSlot(36000, 57600, 10.4, 1)  # 10:00-16:00, 2.4 kW (the real wallbox)


def _day_profile(weekday: int, slots: list[TimeSlot]) -> dict:
    request = charging.build_schedule_day_request(weekday, slots, TZ)["csChargingProfiles"]
    periods = request.pop("chargingSchedule")["chargingSchedulePeriod"]
    # stored (GET) layout: flat arrays, like the wallbox returns
    return {
        **request,
        "startPeriod": [p["startPeriod"] for p in periods],
        "limit": [p["limit"] for p in periods],
        "numberPhases": [p["numberPhases"] for p in periods],
    }


@pytest.fixture(name="setup")
def setup_fixture():
    """Return (calendar, device, written) with the real every-day schedule."""
    device = AlfenDevice(
        session=MagicMock(),
        host="192.168.1.100",
        name="Alfen",
        username="admin",
        password="secret",
        category_options=["generic"],
        ssl=MagicMock(),
    )
    device.id = "alfen_Alfen"
    device.info = None
    device.properties = {
        "2062_0": {"id": "2062_0", "value": 16, "cat": "generic"},
        "2221_3": {"id": "2221_3", "value": 230, "cat": "meter1"},
        "2221_4": {"id": "2221_4", "value": 0, "cat": "meter1"},
        "2221_5": {"id": "2221_5", "value": 0, "cat": "meter1"},
    }
    device.charging_profiles_by_id = {
        charging.PROFILE_IDS_SCHEDULE_DAYS[d]: _day_profile(d, [EVERY_DAY]) for d in range(7)
    }
    device.charging_profiles = device._schedule_profiles()

    written: dict[int, list[tuple[int, int, float]]] = {}

    async def fake_post(cmd, payload):
        if payload:
            profile = payload["csChargingProfiles"]
            weekday = charging.schedule_weekday_for_profile_id(profile["chargingProfileId"])
            written[weekday] = [
                (s.start, s.end, s.amps) for s in charging.profile_slots(profile)
            ]
        elif "clear=" in cmd:
            weekday = charging.schedule_weekday_for_profile_id(int(cmd.split("=")[1]))
            written[weekday] = []
        return ""

    device._profile_post = AsyncMock(side_effect=fake_post)
    device.async_update_charging_profiles = AsyncMock()

    coordinator = MagicMock()
    coordinator.device = device
    entry = MagicMock()
    entry.runtime_data = coordinator
    calendar = AlfenChargingScheduleCalendar(entry)
    calendar.async_write_ha_state = MagicMock()
    return calendar, device, written


def _dt(day: int, hour: int, minute: int = 0) -> datetime.datetime:
    # 2026-11-09 is a Monday
    return datetime.datetime(2026, 11, 9 + day, hour, minute, tzinfo=TZ)


async def test_every_day_slot_is_one_daily_series(setup):
    """The same slot on all days is one series with FREQ=DAILY."""
    calendar, _, _ = setup
    with patch("homeassistant.util.dt.get_default_time_zone", return_value=TZ):
        events = await calendar.async_get_events(MagicMock(config=MagicMock(time_zone="UTC")), _dt(0, 0), _dt(6, 0))
    assert len(events) == 7
    assert {e.uid for e in events} == {"alfen-36000-57600-10.4-1"}
    assert all(e.rrule == "FREQ=DAILY" for e in events)


async def test_create_weekly_slot_with_power_in_title(setup):
    """'7.4 kW' weekdays 22:00-06:00 adds evening + next-morning parts."""
    calendar, _, written = setup
    with patch("homeassistant.util.dt.as_local", side_effect=lambda d: d):
        await calendar.async_create_event(
            dtstart=_dt(0, 22), dtend=_dt(1, 6), summary="Night 7.4 kW",
            rrule="FREQ=WEEKLY;BYDAY=MO,TU",
        )
    # 7.4 kW on one phase would be 32.2 A: capped at the 16 A station maximum
    assert written[0] == [(36000, 57600, 10.4), (79200, 86400, 16.0)]  # Mon: + 22-24
    assert written[1] == [(0, 21600, 16.0), (36000, 57600, 10.4), (79200, 86400, 16.0)]
    assert written[2] == [(0, 21600, 16.0), (36000, 57600, 10.4)]  # Wed morning
    assert set(written) == {0, 1, 2}


async def test_create_overlapping_slot_is_rejected(setup):
    """Overlaps are refused and nothing is written."""
    calendar, device, written = setup
    with (
        patch("homeassistant.util.dt.as_local", side_effect=lambda d: d),
        pytest.raises(HomeAssistantError, match="conflicts"),
    ):
        await calendar.async_create_event(dtstart=_dt(2, 15), dtend=_dt(2, 17), summary="11 kW")
    assert written == {}
    device._profile_post.assert_not_called()


async def test_unsupported_repeat_and_all_day_rejected(setup):
    """Monthly repeats and all-day events can't map to the weekly schedule."""
    calendar, _, _ = setup
    with patch("homeassistant.util.dt.as_local", side_effect=lambda d: d):
        with pytest.raises(HomeAssistantError, match="repeats every week"):
            await calendar.async_create_event(
                dtstart=_dt(0, 1), dtend=_dt(0, 2), summary="x", rrule="FREQ=MONTHLY"
            )
        with pytest.raises(HomeAssistantError, match="all-day"):
            await calendar.async_create_event(
                dtstart=datetime.date(2026, 11, 9), dtend=datetime.date(2026, 11, 10), summary="x"
            )


async def test_edit_whole_series_moves_all_days(setup):
    """Editing the series (this and following) changes every day, keeping power."""
    calendar, _, written = setup
    with patch("homeassistant.util.dt.as_local", side_effect=lambda d: d):
        await calendar.async_update_event(
            "alfen-36000-57600-10.4-1",
            {"dtstart": _dt(3, 11), "dtend": _dt(3, 15), "summary": "Charging 2.4 kW"},
            recurrence_id="2026-11-12",
            recurrence_range="THISANDFUTURE",
        )
    assert written == {d: [(39600, 54000, 10.4)] for d in range(7)}


async def test_edit_single_occurrence_changes_one_day(setup):
    """'This event' only changes that weekday."""
    calendar, _, written = setup
    with patch("homeassistant.util.dt.as_local", side_effect=lambda d: d):
        await calendar.async_update_event(
            "alfen-36000-57600-10.4-1",
            {"dtstart": _dt(5, 8), "dtend": _dt(5, 18), "summary": "16 A"},
            recurrence_id="2026-11-14",
        )
    assert written == {5: [(28800, 64800, 16.0)]}


async def test_delete_single_and_all(setup):
    """Delete one occurrence (one weekday) or the whole series (all days)."""
    calendar, _, written = setup
    await calendar.async_delete_event("alfen-36000-57600-10.4-1", recurrence_id="2026-11-15")
    assert written == {6: []}

    written.clear()
    await calendar.async_delete_event("alfen-36000-57600-10.4-1")
    assert written == {d: [] for d in range(7)}


async def test_unknown_uid(setup):
    """A stale event gives a clear error."""
    calendar, _, _ = setup
    with pytest.raises(HomeAssistantError, match="no longer exists"):
        await calendar.async_delete_event("alfen-1-2-3-4")


def test_rrule_helpers():
    """Repeat rules map to weekdays and back."""
    assert charging.rrule_weekdays(None, 4) == [4]
    assert charging.rrule_weekdays("FREQ=DAILY", 0) == list(range(7))
    assert charging.rrule_weekdays("RRULE:FREQ=WEEKLY;BYDAY=SA,SU;INTERVAL=1", 0) == [5, 6]
    with pytest.raises(ValueError):
        charging.rrule_weekdays("FREQ=WEEKLY;COUNT=3", 0)
    assert charging.weekdays_rrule([0, 1, 2, 3, 4]) == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    assert charging.parse_slot_limit("Night 7,4 kW") == (7.4, None)
    assert charging.parse_slot_limit("16 A") == (None, 16.0)
    assert charging.parse_slot_limit("Charging") == (None, None)


async def test_selecting_days_loads_their_slot_into_the_editor(setup):
    """Picking a day prefills From / To / Power with that day's current slot."""
    from custom_components.alfen_wallbox.select import AlfenScheduleDaysSelect

    _, device, _ = setup
    coordinator = MagicMock()
    coordinator.device = device
    coordinator.schedule_draft = {
        "start": datetime.time(22, 0), "end": datetime.time(6, 0), "power_kw": None, "days": "every_day",
    }
    entry = MagicMock()
    entry.runtime_data = coordinator
    select = AlfenScheduleDaysSelect(entry)

    await select.async_select_option("Tuesday")

    assert coordinator.schedule_draft == {
        "start": datetime.time(10, 0), "end": datetime.time(16, 0), "power_kw": 2.4, "days": "tuesday",
    }
    coordinator.async_update_listeners.assert_called_once()
