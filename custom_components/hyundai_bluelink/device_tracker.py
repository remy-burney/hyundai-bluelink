from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HyundaiBluelinkDataUpdateCoordinator
from .entity import HyundaiBluelinkEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai Bluelink device trackers."""
    coordinator: HyundaiBluelinkDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    known_vehicle_ids: set[str] = set()

    def async_add_current_entities() -> None:
        entities: list[HyundaiBluelinkDeviceTracker] = []
        for vehicle_id in coordinator.data.vehicles:
            if vehicle_id in known_vehicle_ids:
                continue
            known_vehicle_ids.add(vehicle_id)
            entities.append(HyundaiBluelinkDeviceTracker(coordinator, vehicle_id))
        if entities:
            async_add_entities(entities)

    async_add_current_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_current_entities))


class HyundaiBluelinkDeviceTracker(HyundaiBluelinkEntity, TrackerEntity):
    """Hyundai Bluelink GPS tracker entity."""

    _attr_translation_key = "location"

    def __init__(
        self,
        coordinator: HyundaiBluelinkDataUpdateCoordinator,
        vehicle_id: str,
    ) -> None:
        """Initialize the device tracker."""
        super().__init__(coordinator, vehicle_id, "location")

    @property
    def latitude(self) -> float | None:
        """Return latitude."""
        return self.vehicle_data.latitude

    @property
    def longitude(self) -> float | None:
        """Return longitude."""
        return self.vehicle_data.longitude

    @property
    def source_type(self) -> SourceType:
        """Return the location source type."""
        return SourceType.GPS
