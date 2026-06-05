"""Calendar entity for Alfen Wallbox charging schedules."""

from __future__ import annotations

import datetime
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AlfenConfigEntry
from .entity import AlfenEntity

_LOGGER = logging.getLogger(__name__)

# Map weekday names to Python weekday integers (Monday=0 … Sunday=6)
WEEKDAY_MAP: dict[str, int] = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


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


def _profile_to_events(
    profile: dict,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
) -> list[CalendarEvent]:
    """Convert a single OCPP charging profile to a list of CalendarEvents.

    A profile may contain multiple active periods (limit > 0).  For each
    active period the end is defined by the next period where limit == 0
    (or by start + schedule duration when no explicit off-period follows).

    Args:
        profile: OCPP charging profile dict.
        start_date: Inclusive lower bound of the requested calendar range.
        end_date:   Inclusive upper bound of the requested calendar range.

    Returns:
        List of :class:`CalendarEvent` instances within the requested range.
    """
    schedule = profile.get("chargingSchedule", {})
    periods: list[dict] = schedule.get("chargingSchedulePeriod", [])
    duration: int = schedule.get("duration", 86400)
    recurrency_kind: str = profile.get("recurrencyKind", "DAILY")
    days_of_week: list[str] = profile.get("daysOfWeek", [])

    events: list[CalendarEvent] = []

    # Build charging windows: consecutive pairs of (on-period, off-period)
    for idx, period in enumerate(periods):
        limit = period.get("limit", 0)
        if limit <= 0:
            continue  # not an active charging period

        start_period: int = period["startPeriod"]
        number_phases: int = period.get("numberPhases", 1)

        # Find the end of this active window
        end_period: int | None = None
        for next_period in periods[idx + 1 :]:
            if next_period.get("limit", 0) == 0:
                end_period = next_period["startPeriod"]
                break

        if end_period is None:
            end_period = start_period + duration

        charge_start_time = _seconds_to_time(start_period)
        charge_end_time = _seconds_to_time(end_period)

        start_str = charge_start_time.strftime("%H:%M")
        end_str = charge_end_time.strftime("%H:%M")

        summary = f"Charging {limit}A"
        description = f"{start_str} – {end_str} | {number_phases} phase(s)"

        # Iterate over each calendar day in the requested range
        current = start_date.date()
        end = end_date.date()

        while current <= end:
            include_day = False

            if recurrency_kind == "DAILY":
                include_day = True
            elif recurrency_kind == "WEEKLY":
                # days_of_week contains human-readable names, e.g. ["Monday", "Wednesday"]
                weekday_numbers = [WEEKDAY_MAP[d] for d in days_of_week if d in WEEKDAY_MAP]
                include_day = current.weekday() in weekday_numbers

            if include_day:
                event_start = datetime.datetime.combine(
                    current, charge_start_time, tzinfo=datetime.UTC
                )
                event_end = datetime.datetime.combine(
                    current, charge_end_time, tzinfo=datetime.UTC
                )

                # Handle midnight wrap-around (end time before start time)
                if event_end <= event_start:
                    event_end += datetime.timedelta(days=1)

                events.append(
                    CalendarEvent(
                        start=event_start,
                        end=event_end,
                        summary=summary,
                        description=description,
                    )
                )

            current += datetime.timedelta(days=1)

    return events


class AlfenChargingScheduleCalendar(AlfenEntity, CalendarEntity):
    """Calendar entity that shows charging schedule timeslots as events."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: AlfenConfigEntry) -> None:
        """Initialise the calendar entity."""
        super().__init__(entry)
        device = self.coordinator.device
        self._attr_name = f"{device.name} Charging Schedule"
        self._attr_unique_id = f"{device.id}-charging_schedule_calendar"
        self._profiles: list[dict] = []

    @property
    def event(self) -> CalendarEvent | None:
        """Return the currently active charging event, or None."""
        now = datetime.datetime.now(datetime.UTC)
        today_start = datetime.datetime.combine(now.date(), datetime.time.min, tzinfo=datetime.UTC)
        today_end = datetime.datetime.combine(now.date(), datetime.time.max, tzinfo=datetime.UTC)

        for profile in self._profiles:
            for evt in _profile_to_events(profile, today_start, today_end):
                if evt.start <= now < evt.end:
                    return evt

        return None

    async def async_added_to_hass(self) -> None:
        """Fetch profiles once on startup so the `event` property is populated."""
        await super().async_added_to_hass()
        await self._async_refresh_profiles()

    async def _async_refresh_profiles(self) -> None:
        """Fetch current charging profiles from the device."""
        try:
            self._profiles = await self.coordinator.device.get_charging_profiles()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.debug(
                "[%s] Failed to fetch charging profiles for calendar",
                self.coordinator.device.log_id,
                exc_info=True,
            )
            self._profiles = []

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events in the requested date range."""
        await self._async_refresh_profiles()
        events: list[CalendarEvent] = []
        for profile in self._profiles:
            events.extend(_profile_to_events(profile, start_date, end_date))
        return events
