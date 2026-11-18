"""Button: check the Zigbee topology now (targeted rescan)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NetworkTopologyConfigEntry
from .const import DOMAIN
from .coordinator import NetworkTopologyCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetworkTopologyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ZigbeeRescanButton(entry.runtime_data)])


class ZigbeeRescanButton(CoordinatorEntity[NetworkTopologyCoordinator], ButtonEntity):
    """Re-read neighbor and route tables of the routers involved in conflicts.

    Without conflicts it scans all routers, like ZHA's "Refresh topology".
    """

    _attr_has_entity_name = True
    _attr_translation_key = "zigbee_rescan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: NetworkTopologyCoordinator) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_zigbee_rescan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Network Topology",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.zigbee_available

    async def async_press(self) -> None:
        result = self.coordinator.async_start_rescan(manual=True)
        if result == "busy":
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="rescan_busy"
            )
        if result == "nothing":
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="rescan_nothing"
            )
