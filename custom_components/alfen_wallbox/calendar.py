"""Editable calendar for the Alfen Wallbox weekly charging schedule.

Every time slot of the wallbox's (Eve Connect compatible) weekly schedule is a
calendar event. Identical slots on several weekdays form one repeating series
(``FREQ=WEEKLY;BYDAY=...`` or ``FREQ=DAILY``), so Home Assistant's native
calendar dialog can create, edit and delete charging slots:

* **Create** an event with a start/end time; "repeat daily/weekly" picks the days
  (no repeat = every week on that weekday, since the wallbox repeats weekly).
* Put the power in the title, e.g. "7.4 kW" or "16 A" (default: station maximum).
* **Edit / delete "this event"** changes only that weekday; "this and following
  events" (or a non-recurring edit) changes every day of the series.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.calendar.const import (
    EVENT_END,
    EVENT_RRULE,
    EVENT_START,
    EVENT_SUMMARY,
    CalendarEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import charging
from .alfen import ChargingProfileError
from .charging import TimeSlot
from .coordinator import AlfenConfigEntry
from .entity import AlfenEntity

THIS_AND_FUTURE = "THISANDFUTURE"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Alfen calendar entity from a config entry."""
    async_add_entities([AlfenChargingScheduleCalendar(entry)])


def _seconds_to_time(seconds: int) -> datetime.time:
    """Convert seconds-from-midnight to a :class:`datetime.time` object."""
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return datetime.time(hour=hours % 24, minute=minutes, second=secs)


def _slot_uid(slot: TimeSlot) -> str:
    return f"alfen-{slot.start}-{slot.end}-{slot.amps}-{slot.phases}"


def _series(schedule: dict[int, list[TimeSlot]]) -> dict[str, tuple[TimeSlot, list[int]]]:
    """Group identical slots over weekdays: uid -> (slot, weekdays)."""
    series: dict[str, tuple[TimeSlot, list[int]]] = {}
    for weekday in range(7):
        for slot in schedule.get(weekday, []):
            series.setdefault(_slot_uid(slot), (slot, []))[1].append(weekday)
    return series


def _slot_event(
    slot: TimeSlot,
    day: datetime.date,
    tzinfo: datetime.tzinfo,
    weekdays: list[int] | None = None,
) -> CalendarEvent:
    midnight = datetime.datetime.combine(day, datetime.time.min, tzinfo=tzinfo)
    return CalendarEvent(
        start=midnight + datetime.timedelta(seconds=slot.start),
        end=midnight + datetime.timedelta(seconds=slot.end),
        summary=f"Charging {slot.power_kw} kW",
        description=(
            f"{charging.seconds_to_hhmm(slot.start)} – {charging.seconds_to_hhmm(slot.end)}"
            f" | {slot.amps}A × {slot.phases} phase(s)"
        ),
        uid=_slot_uid(slot),
        recurrence_id=day.isoformat(),
        rrule=charging.weekdays_rrule(weekdays) if weekdays else None,
    )


def _schedule_to_events(
    schedule: dict[int, list[TimeSlot]],
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    tzinfo: datetime.tzinfo,
) -> list[CalendarEvent]:
    series = _series(schedule)
    events: list[CalendarEvent] = []
    day = start_date.date()
    while day <= end_date.date():
        for slot in schedule.get(day.weekday(), []):
            events.append(_slot_event(slot, day, tzinfo, series[_slot_uid(slot)][1]))
        day += datetime.timedelta(days=1)
    return events


def _profile_to_events(
    profile: dict,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    tzinfo: datetime.tzinfo = datetime.UTC,
) -> list[CalendarEvent]:
    """Convert a single charging profile to CalendarEvents within the date range."""
    return _schedule_to_events(
        charging.schedule_from_profiles([profile]), start_date, end_date, tzinfo
    )


class AlfenChargingScheduleCalendar(AlfenEntity, CalendarEntity):
    """Calendar showing (and editing) the charging schedule time slots.

    Reads the profiles cached by the device (refreshed every ~5 minutes and right
    after every change), so viewing the calendar adds no wallbox requests.
    """

    _attr_icon = "mdi:calendar-clock"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
    )

    def __init__(self, entry: AlfenConfigEntry) -> None:
        """Initialise the calendar entity."""
        super().__init__(entry)
        device = self.coordinator.device
        self._attr_name = f"{device.name} Charging Schedule"
        self._attr_unique_id = f"{device.id}-charging_schedule_calendar"

    def _schedule(self) -> dict[int, list[TimeSlot]]:
        return charging.schedule_from_profiles(self.coordinator.device.charging_profiles)

    @property
    def event(self) -> CalendarEvent | None:
        """Return the currently active charging event, or None."""
        now = dt_util.now()
        schedule = self._schedule()
        slot = charging.active_slot(schedule, now)
        if slot is None:
            return None
        weekdays = _series(schedule)[_slot_uid(slot)][1]
        return _slot_event(slot, now.date(), now.tzinfo or datetime.UTC, weekdays)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events in the requested date range."""
        tz: datetime.tzinfo = ZoneInfo(hass.config.time_zone)
        return _schedule_to_events(self._schedule(), start_date, end_date, tz)

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def _event_slot(self, event: dict, previous: TimeSlot | None = None) -> tuple[TimeSlot, int]:
        """Turn the dialog's event into (slot, weekday of its start)."""
        start, end = event.get(EVENT_START), event.get(EVENT_END)
        if not isinstance(start, datetime.datetime) or not isinstance(end, datetime.datetime):
            raise HomeAssistantError(
                "Charging slots need a start and end time (all-day events are not supported)"
            )
        start, end = dt_util.as_local(start), dt_util.as_local(end)
        if not datetime.timedelta(0) < end - start < datetime.timedelta(days=1):
            raise HomeAssistantError("A charging slot must be shorter than 24 hours")
        start_secs = start.hour * 3600 + start.minute * 60
        end_secs = end.hour * 3600 + end.minute * 60
        power_kw, current = charging.parse_slot_limit(event.get(EVENT_SUMMARY))
        device = self.coordinator.device
        if power_kw is None and current is None and previous is not None:
            # Title not changed to a new power: keep the slot's power
            return TimeSlot(
                start_secs, end_secs or charging.SECONDS_PER_DAY, previous.amps, previous.phases
            ), start.weekday()
        slot = device.make_timeslot(start=start_secs, end=end_secs, power_kw=power_kw, current=current)
        return slot, start.weekday()

    def _find_series(self, uid: str) -> tuple[TimeSlot, list[int]]:
        found = _series(self._schedule()).get(uid)
        if found is None:
            raise HomeAssistantError("This charging slot no longer exists; refresh the calendar")
        return found

    @staticmethod
    def _target_days(
        weekdays: list[int], recurrence_id: str | None, recurrence_range: str | None
    ) -> list[int]:
        """"This event" -> that weekday only; otherwise the whole series."""
        if recurrence_id and recurrence_range != THIS_AND_FUTURE:
            try:
                return [datetime.date.fromisoformat(recurrence_id[:10]).weekday()]
            except ValueError:
                pass
        return weekdays

    def _without(self, slot: TimeSlot, days: list[int]) -> dict[int, list[TimeSlot]]:
        device = self.coordinator.device
        result: dict[int, list[TimeSlot]] = {}
        for weekday in days:
            current = list(device.schedule_day_slots(weekday))
            if slot not in current:
                raise HomeAssistantError(
                    "This slot is not stored in the Eve Connect schedule format and "
                    "can't be edited here (use the clear_charging_schedule service)"
                )
            current.remove(slot)
            result[weekday] = current
        return result

    def _with(
        self, days: dict[int, list[TimeSlot]], slot: TimeSlot, weekdays: list[int]
    ) -> dict[int, list[TimeSlot]]:
        device = self.coordinator.device
        for weekday in weekdays:
            for day, part in charging.split_slot(weekday, slot):
                days.setdefault(day, list(device.schedule_day_slots(day))).append(part)
        return days

    async def _apply(self, days: dict[int, list[TimeSlot]]) -> None:
        try:
            await self.coordinator.device.apply_schedule(days)
        except (ChargingProfileError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err
        self.async_write_ha_state()

    async def async_create_event(self, **kwargs) -> None:
        """Add a charging slot (repeat rule selects the weekdays)."""
        slot, weekday = self._event_slot(kwargs)
        try:
            weekdays = charging.rrule_weekdays(kwargs.get(EVENT_RRULE), weekday)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        await self._apply(self._with({}, slot, weekdays))

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete a slot from one weekday ("this event") or from all its days."""
        slot, weekdays = self._find_series(uid)
        await self._apply(self._without(slot, self._target_days(weekdays, recurrence_id, recurrence_range)))

    async def async_update_event(
        self,
        uid: str,
        event: dict,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Change a slot on one weekday ("this event") or on all its days."""
        old_slot, weekdays = self._find_series(uid)
        targets = self._target_days(weekdays, recurrence_id, recurrence_range)
        new_slot, new_weekday = self._event_slot(event, previous=old_slot)
        if targets == weekdays and event.get(EVENT_RRULE):
            try:
                new_days = charging.rrule_weekdays(event[EVENT_RRULE], new_weekday)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
        elif targets == weekdays and len(weekdays) > 1:
            new_days = weekdays  # series edited without touching the repeat rule
        else:
            new_days = [new_weekday]
        await self._apply(self._with(self._without(old_slot, targets), new_slot, new_days))
