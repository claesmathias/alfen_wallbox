"""Base entity for Alfen Wallbox integration."""

from typing import cast

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN as ALFEN_DOMAIN
from .coordinator import AlfenConfigEntry, AlfenCoordinator
from .devices import MAIN, SUB_DEVICES, device_group, entity_key


class AlfenEntity(CoordinatorEntity[AlfenCoordinator], Entity):
    """Define a base Alfen entity."""

    # Note: _attr_has_entity_name = True would be ideal for gold tier compliance,
    # but enabling it would change entity_id patterns and break existing installations.
    # This should be enabled in a future major version with proper migration.

    def __init__(self, entry: AlfenConfigEntry) -> None:
        """Initialize the Alfen entity."""

        super().__init__(entry.runtime_data)
        self.coordinator = entry.runtime_data

    @property
    def device_info(self) -> DeviceInfo:
        """Return the (sub-)device this entity belongs to.

        The group follows from the key in the unique ID; see devices.py.
        """
        device = self.coordinator.device
        category = self.entity_category
        group = device_group(
            entity_key(self.unique_id, device.id),
            category.value if category is not None else None,
        )
        if group == MAIN:
            return main_device_info(self.coordinator)
        return DeviceInfo(
            identifiers={(ALFEN_DOMAIN, f"{device.name}_{group}")},
            manufacturer="Alfen",
            model=device.info.model if device.info else "Unknown",
            name=f"{device.name} {SUB_DEVICES[group]}",
            translation_key=group,
            translation_placeholders={"name": device.name},
            via_device=(ALFEN_DOMAIN, device.name),
        )

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Entities remain available even when coordinator updates fail, as long as we have
        cached data from previous successful updates. This prevents all sensors from
        becoming unavailable during brief network interruptions or timeouts.

        The coordinator preserves the properties dict between update cycles, so entities
        can continue displaying the last known values during transient failures.
        """
        return True

    async def async_added_to_hass(self) -> None:
        """Add listener for state changes."""
        await super().async_added_to_hass()


def main_device_info(coordinator: AlfenCoordinator) -> DeviceInfo:
    """Return the main wallbox device."""
    return cast(DeviceInfo, coordinator.device.device_info)
