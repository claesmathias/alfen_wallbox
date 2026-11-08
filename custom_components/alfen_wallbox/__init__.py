"""Alfen Wallbox integration."""

import logging
from typing import Any

from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_REFRESH_CATEGORIES,
    DEFAULT_REFRESH_CATEGORIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
)
from .coordinator import AlfenConfigEntry, AlfenCoordinator, options_update_listener
from .export import AlfenExportView

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.TIME,
]

# Entities removed in 3.6.0 (unique_id suffixes). "Solar Charging Schedule Enabled"
# was an on/off switch for 3280_1, which is really the 3-way solar charging mode
# already exposed by the "Solar Charging Mode" select.
REMOVED_ENTITY_UNIQUE_ID_SUFFIXES = ("_lb_solar_charging_schedule",)

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, config_entry: AlfenConfigEntry) -> bool:
    """Migrate old entry."""
    name = config_entry.data.get(CONF_NAME, "Unknown")
    host = config_entry.data.get(CONF_HOST, "Unknown")
    log_id = f"{name}@{host}"

    _LOGGER.debug("[%s] Migrating from version %s", log_id, config_entry.version)

    if config_entry.version == 1:
        scan_interval = config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        options = {
            CONF_SCAN_INTERVAL: scan_interval,
            CONF_TIMEOUT: DEFAULT_TIMEOUT,
            CONF_REFRESH_CATEGORIES: DEFAULT_REFRESH_CATEGORIES,
        }
        data = {
            CONF_HOST: config_entry.data.get(CONF_HOST),
            CONF_NAME: config_entry.data.get(CONF_NAME),
            CONF_USERNAME: config_entry.data.get(CONF_USERNAME),
            CONF_PASSWORD: config_entry.data.get(CONF_PASSWORD),
        }

        hass.config_entries.async_update_entry(
            config_entry,
            version=2,
            data=data,
            options=options,
        )

        _LOGGER.debug("[%s] Migration to version %s successful", log_id, config_entry.version)

    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: AlfenConfigEntry) -> bool:
    """Set up Alfen from a config entry."""
    await er.async_migrate_entries(hass, config_entry.entry_id, async_migrate_entity_entry)
    _async_remove_obsolete_entities(hass, config_entry)

    # Authenticated CSV / JSON download of the charging history (registered once)
    if hass.http is not None and not hass.data.get(f"{DOMAIN}_export_view"):
        hass.http.register_view(AlfenExportView())
        hass.data[f"{DOMAIN}_export_view"] = True

    coordinator = AlfenCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()

    config_entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    config_entry.async_on_unload(config_entry.add_update_listener(options_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: AlfenConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = config_entry.runtime_data
    _LOGGER.debug("[%s] async_unload_entry", coordinator.device.log_id)

    await coordinator.async_save_transactions()
    await coordinator.device.logout()

    # Close the dedicated ClientSession
    if coordinator._session and not coordinator._session.closed:
        await coordinator._session.close()

    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)


@callback
def _async_remove_obsolete_entities(hass: HomeAssistant, config_entry: AlfenConfigEntry) -> None:
    """Remove registry entries of entities this version no longer provides."""
    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if entity_entry.unique_id.endswith(REMOVED_ENTITY_UNIQUE_ID_SUFFIXES):
            _LOGGER.debug("Removing obsolete entity %s", entity_entry.entity_id)
            registry.async_remove(entity_entry.entity_id)


@callback
def async_migrate_entity_entry(
    entity_entry: er.RegistryEntry,
) -> dict[str, Any] | None:
    """Migrate a Alfen entity entry."""

    # Migrate uptime_hours sensor to add device_class: duration (2025-11-03)
    if (
        entity_entry.domain == "sensor"
        and entity_entry.unique_id.endswith("_uptime_hours")
        and entity_entry.device_class != "duration"
    ):
        _LOGGER.debug("Migrating %s to add device_class=duration", entity_entry.entity_id)
        return {"device_class": "duration"}

    # Remove device_class from uptime sensor (it returns a string, not numeric) (2025-11-03)
    if (
        entity_entry.domain == "sensor"
        and entity_entry.unique_id.endswith("_uptime")
        and not entity_entry.unique_id.endswith("_uptime_hours")  # Don't match uptime_hours
        and entity_entry.device_class == "duration"
    ):
        _LOGGER.debug(
            "Migrating %s to remove device_class (returns string not numeric)",
            entity_entry.entity_id,
        )
        return {"device_class": None}

    return None
