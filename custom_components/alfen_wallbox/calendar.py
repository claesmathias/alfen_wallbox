"""Calendar entity for Alfen Wallbox charging schedules."""

from __future__ import annotations

import datetime
import logging
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

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


def _normalize_periods(profile: dict) -> list[tuple[int, float, int]]:
    """Return ``(startPeriod_secs, limit_amps, numberPhases)`` tuples for all periods.

    Handles two profile layouts used by Alfen wallboxes:

    * **Nested** (standard OCPP / HA add_charging_profile service):
      ``profile.chargingSchedule.chargingSchedulePeriod``
    * **Flat-array** (Eve Connect / ChargingStationExternalConstraints):
      parallel top-level lists ``startPeriod``, ``limit``, ``numberPhases``.
    """
    # Nested format
    schedule = profile.get("chargingSchedule", {})
    nested = schedule.get("chargingSchedulePeriod", [])
    if nested:
        return [
            (int(p["startPeriod"]), float(p.get("limit", 0)), int(p.get("numberPhases", 1)))
            for p in nested
        ]

    # Flat-array format
    start_periods = profile.get("startPeriod", [])
    if not start_periods:
        return []
    limits = profile.get("limit", [])
    num_phases = profile.get("numberPhases", [])
    return [
        (int(sp), float(lim), int(np))
        for sp, lim, np in zip(
            start_periods,
            limits if limits else [0.0] * len(start_periods),
            num_phases if num_phases else [1] * len(start_periods),
        )
    ]


def _profile_to_events(
    profile: dict,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    tzinfo: datetime.tzinfo = datetime.UTC,
) -> list[CalendarEvent]:
    """Convert a single charging profile to CalendarEvents within the date range.

    Supports:

    * **DAILY** recurrence (no day filter)
    * **WEEKLY** with ``daysOfWeek`` list (standard OCPP names)
    * **Weekly** with ``startSchedule`` anchor date (Eve Connect format — one
      profile per weekday, anchored on a reference week in April 2024)
    """
    periods = _normalize_periods(profile)
    if not periods:
        return []

    recurrency_kind: str = profile.get("recurrencyKind", "DAILY")
    days_of_week: list[str] = profile.get("daysOfWeek", [])
    start_schedule: str | None = profile.get("startSchedule")

    # Determine which weekday(s) this profile applies to.
    # None means "every day" (DAILY).
    target_weekdays: set[int] | None = None

    if start_schedule and recurrency_kind in ("Weekly", "WEEKLY"):
        # Eve Connect stores one profile per day, with startSchedule anchored
        # on the concrete date of that weekday in a reference week.
        try:
            anchor = datetime.datetime.fromisoformat(
                start_schedule.replace("Z", "+00:00")
            )
            target_weekdays = {anchor.weekday()}
        except (ValueError, AttributeError):
            pass
    elif days_of_week:
        target_weekdays = {WEEKDAY_MAP[d] for d in days_of_week if d in WEEKDAY_MAP}

    events: list[CalendarEvent] = []

    for idx, (start_period, limit, num_phases) in enumerate(periods):
        if limit <= 0:
            continue

        # End of this active window = start of the next off-period
        end_period: int | None = None
        for next_sp, next_limit, _ in periods[idx + 1 :]:
            if next_limit == 0:
                end_period = next_sp
                break
        if end_period is None:
            end_period = start_period + 86400

        charge_start = _seconds_to_time(start_period)
        charge_end = _seconds_to_time(end_period)

        power_kw = round(limit * num_phases * 230 / 1000, 1)
        summary = f"Charging {power_kw} kW"
        description = (
            f"{charge_start.strftime('%H:%M')} – {charge_end.strftime('%H:%M')}"
            f" | {limit}A × {num_phases} phase(s)"
        )

        current = start_date.date()
        end = end_date.date()

        while current <= end:
            include = target_weekdays is None or current.weekday() in target_weekdays

            if include:
                event_start = datetime.datetime.combine(
                    current, charge_start, tzinfo=tzinfo
                )
                event_end = datetime.datetime.combine(
                    current, charge_end, tzinfo=tzinfo
                )

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
        now = dt_util.now()
        tz = now.tzinfo or datetime.UTC
        today_start = datetime.datetime.combine(now.date(), datetime.time.min, tzinfo=tz)
        today_end = datetime.datetime.combine(now.date(), datetime.time.max, tzinfo=tz)

        for profile in self._profiles:
            for evt in _profile_to_events(profile, today_start, today_end, tzinfo=tz):
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
        tz: datetime.tzinfo = ZoneInfo(hass.config.time_zone)
        events: list[CalendarEvent] = []
        for profile in self._profiles:
            events.extend(_profile_to_events(profile, start_date, end_date, tzinfo=tz))
        return events
