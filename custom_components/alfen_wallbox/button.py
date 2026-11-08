"""Button entities for Alfen EV chargers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from homeassistant.components import persistent_notification
from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import charging
from .alfen import ChargingProfileError
from .const import (
    ADD_SCHEDULE_SLOT,
    BOOST_MODE,
    CLEAR_CHARGING_SCHEDULE,
    CLEAR_SCHEDULE_DAYS,
    CMD,
    COMMAND_CLEAR_TRANSACTIONS,
    COMMAND_REBOOT,
    EXPORT_HISTORY,
    FORCE_TRANSACTION_UPDATE,
    FORCE_UPDATE,
    LOGIN,
    LOGOUT,
    METHOD_POST,
    PARAM_COMMAND,
    PAUSE_CHARGING,
    REFRESH_CHARGING_SCHEDULE,
    REPLACE_SCHEDULE_SLOTS,
    RESUME_CHARGING,
    SCHEDULE_DAY_KEYS,
    SCHEDULE_DAY_OPTIONS,
    STOP_BOOST_MODE,
)
from .coordinator import AlfenConfigEntry, AlfenCoordinator
from .entity import AlfenEntity
from .export import async_create_export_links


@dataclass(frozen=True)
class AlfenButtonDescriptionMixin:
    """Define an entity description mixin for button entities."""

    method: str
    url_action: str
    json_data: dict[str, str] | None


@dataclass(frozen=True)
class AlfenButtonDescription(ButtonEntityDescription, AlfenButtonDescriptionMixin):
    """Class to describe an Alfen button entity."""


ALFEN_BUTTON_TYPES: Final[tuple[AlfenButtonDescription, ...]] = (
    AlfenButtonDescription(
        key="reboot_wallbox",
        name="Reboot Wallbox",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        method=METHOD_POST,
        url_action=CMD,
        json_data={PARAM_COMMAND: COMMAND_REBOOT},
    ),
    AlfenButtonDescription(
        key="auth_logout",
        name="HTTPS API Logout",
        icon="mdi:logout",
        entity_category=EntityCategory.DIAGNOSTIC,
        method=METHOD_POST,
        url_action=LOGOUT,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="auth_login",
        name="HTTPS API Login",
        icon="mdi:login",
        entity_category=EntityCategory.DIAGNOSTIC,
        method=METHOD_POST,
        url_action=LOGIN,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="wallbox_force_update",
        name="Force Update",
        icon="mdi:refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        method=METHOD_POST,
        url_action=FORCE_UPDATE,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="clear_transaction",
        name="Clear Transaction",
        icon="mdi:delete-clock",
        entity_category=EntityCategory.CONFIG,
        method=METHOD_POST,
        url_action=CMD,
        json_data={PARAM_COMMAND: COMMAND_CLEAR_TRANSACTIONS},
    ),
    AlfenButtonDescription(
        key="force_fetch_transaction",
        name="Force Fetch Transaction",
        icon="mdi:database-refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        method="",
        url_action=FORCE_TRANSACTION_UPDATE,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="clear_charging_profiles",
        name="Clear Charging Schedule",
        icon="mdi:calendar-remove",
        method=METHOD_POST,
        url_action=CLEAR_CHARGING_SCHEDULE,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="refresh_charging_schedule",
        name="Refresh Charging Schedule",
        icon="mdi:calendar-refresh",
        entity_category=EntityCategory.DIAGNOSTIC,
        method="",
        url_action=REFRESH_CHARGING_SCHEDULE,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="enable_boost_mode",
        name="Enable Boost Mode",
        icon="mdi:lightning-bolt",
        method=METHOD_POST,
        url_action=BOOST_MODE,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="stop_boost_mode",
        name="Stop Boost Mode",
        icon="mdi:lightning-bolt-outline",
        method=METHOD_POST,
        url_action=STOP_BOOST_MODE,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="pause_charging",
        name="Pause Charging",
        icon="mdi:pause-circle",
        method=METHOD_POST,
        url_action=PAUSE_CHARGING,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="resume_charging",
        name="Resume Charging",
        icon="mdi:play-circle",
        method=METHOD_POST,
        url_action=RESUME_CHARGING,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="add_schedule_slot",
        name="Add Schedule Slot",
        icon="mdi:calendar-plus",
        method="",
        url_action=ADD_SCHEDULE_SLOT,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="replace_schedule_slots",
        name="Replace Schedule Slots",
        icon="mdi:calendar-edit",
        method="",
        url_action=REPLACE_SCHEDULE_SLOTS,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="clear_schedule_days",
        name="Clear Schedule Days",
        icon="mdi:calendar-minus",
        method="",
        url_action=CLEAR_SCHEDULE_DAYS,
        json_data=None,
    ),
    AlfenButtonDescription(
        key="export_charging_history",
        name="Export Charging History",
        icon="mdi:file-export",
        method="",
        url_action=EXPORT_HISTORY,
        json_data=None,
    ),
)


def _draft_weekdays(coordinator: AlfenCoordinator) -> list[int]:
    """Return the weekdays selected in the schedule editor."""
    label = SCHEDULE_DAY_KEYS.get(coordinator.schedule_draft["days"], "Every day")
    return SCHEDULE_DAY_OPTIONS[label]


async def _force_update(coordinator: AlfenCoordinator) -> None:
    coordinator.device.get_static_properties = True
    await coordinator.device.async_update()


async def _force_fetch_transactions(coordinator: AlfenCoordinator) -> None:
    """Load the charging history in the background (can take a few minutes).

    The Insights sensor shows progress (loading / loaded_until) and the sessions
    found so far; the regular update cycle keeps running meanwhile.
    """
    coordinator.hass.async_create_background_task(
        coordinator.device.async_load_transaction_history(),
        name="alfen_wallbox_load_transaction_history",
    )


async def _export_history(coordinator: AlfenCoordinator) -> None:
    """Create signed CSV / JSON download links and show them in a notification.

    The links are signed for the user who pressed the button and expire after
    an hour. They are also exposed on the Insights sensor for automations.
    """
    links = async_create_export_links(coordinator.hass, coordinator.config_entry.entry_id)
    coordinator.export_links = links
    coordinator.async_update_listeners()
    sessions = len(coordinator.device.transactions)
    expires = dt_util.parse_datetime(links["expires"])
    persistent_notification.async_create(
        coordinator.hass,
        (
            f"{sessions} charging sessions are ready to download:\n\n"
            f'<a href="{links["csv"]}" target="_blank">⬇️ Download CSV</a> &nbsp;·&nbsp; '
            f'<a href="{links["json"]}" target="_blank">⬇️ Download JSON</a>\n\n'
            f"The links work until {dt_util.as_local(expires):%H:%M}."
        ),
        title=f"{coordinator.device.name}: charging history export",
        notification_id=f"alfen_wallbox_export_{coordinator.config_entry.entry_id}",
    )


async def _refresh_schedule(coordinator: AlfenCoordinator) -> None:
    await coordinator.device.async_update_charging_profiles()
    coordinator.async_update_listeners()


def _draft_slot(coordinator: AlfenCoordinator) -> charging.TimeSlot:
    draft = coordinator.schedule_draft
    return coordinator.device.make_timeslot(
        start=charging.hhmm_to_seconds(draft["start"]),
        end=charging.hhmm_to_seconds(draft["end"]),
        power_kw=draft["power_kw"],
    )


async def _add_schedule_slot(coordinator: AlfenCoordinator) -> None:
    await coordinator.device.add_schedule_slot(
        _draft_weekdays(coordinator), _draft_slot(coordinator)
    )


async def _replace_schedule_slots(coordinator: AlfenCoordinator) -> None:
    await coordinator.device.add_schedule_slot(
        _draft_weekdays(coordinator), _draft_slot(coordinator), replace=True
    )


async def _clear_schedule_days(coordinator: AlfenCoordinator) -> None:
    await coordinator.device.clear_schedule(_draft_weekdays(coordinator))


BUTTON_ACTIONS: Final[dict[str, Callable[[AlfenCoordinator], Awaitable[None]]]] = {
    FORCE_UPDATE: _force_update,
    FORCE_TRANSACTION_UPDATE: _force_fetch_transactions,
    LOGIN: lambda c: c.device.login(),
    LOGOUT: lambda c: c.device.logout(),
    CLEAR_CHARGING_SCHEDULE: lambda c: c.device.clear_schedule(),
    REFRESH_CHARGING_SCHEDULE: _refresh_schedule,
    EXPORT_HISTORY: _export_history,
    BOOST_MODE: lambda c: c.device.set_boost_mode(),
    STOP_BOOST_MODE: lambda c: c.device.stop_boost_mode(),
    PAUSE_CHARGING: lambda c: c.device.pause_charging(),
    RESUME_CHARGING: lambda c: c.device.resume_charging(),
    ADD_SCHEDULE_SLOT: _add_schedule_slot,
    REPLACE_SCHEDULE_SLOTS: _replace_schedule_slots,
    CLEAR_SCHEDULE_DAYS: _clear_schedule_days,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AlfenConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Alfen button entities from a config entry."""
    async_add_entities(AlfenButton(entry, description) for description in ALFEN_BUTTON_TYPES)


class AlfenButton(AlfenEntity, ButtonEntity):
    """Representation of a Alfen button entity."""

    entity_description: AlfenButtonDescription

    def __init__(
        self,
        entry: AlfenConfigEntry,
        description: AlfenButtonDescription,
    ) -> None:
        """Initialize the Alfen button entity."""
        super().__init__(entry)
        self._attr_name = f"{self.coordinator.device.name} {description.name}"
        self._attr_unique_id = f"{self.coordinator.device.id}-{description.key}"
        self._attr_translation_key = description.key
        self.entity_description = description

    async def async_press(self) -> None:
        """Press the button."""
        action = BUTTON_ACTIONS.get(self.entity_description.url_action)
        try:
            if action is not None:
                await action(self.coordinator)
            elif self.entity_description.json_data is not None:
                await self.coordinator.device.send_command(self.entity_description.json_data)
        except (ChargingProfileError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err
