"""Time entities for the Alfen Wallbox schedule editor."""

from __future__ import annotations

import datetime

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AlfenConfigEntry
from .entity import AlfenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the schedule editor time entities."""
    async_add_entities(
        [
            AlfenScheduleSlotTime(entry, "start", "Schedule Slot Start", "mdi:clock-start"),
            AlfenScheduleSlotTime(entry, "end", "Schedule Slot End", "mdi:clock-end"),
        ]
    )


class AlfenScheduleSlotTime(AlfenEntity, TimeEntity):
    """Start or end of the draft time slot.

    Together with the slot power and days entities this lets a dashboard build a
    time slot and add it with the "Add Schedule Slot" button. An end time at or
    before the start time extends the slot into the next day.
    """

    def __init__(self, entry: AlfenConfigEntry, field: str, name: str, icon: str) -> None:
        """Initialize."""
        super().__init__(entry)
        device = self.coordinator.device
        self._field = field
        self._attr_icon = icon
        self._attr_translation_key = f"schedule_slot_{field}"
        self._attr_name = f"{device.name} {name}"
        self._attr_unique_id = f"{device.id}_schedule_slot_{field}"

    @property
    def native_value(self) -> datetime.time:
        """Return the draft time."""
        return self.coordinator.schedule_draft[self._field]

    async def async_set_value(self, value: datetime.time) -> None:
        """Store the draft time."""
        self.coordinator.schedule_draft[self._field] = value.replace(second=0, microsecond=0)
        self.async_write_ha_state()
