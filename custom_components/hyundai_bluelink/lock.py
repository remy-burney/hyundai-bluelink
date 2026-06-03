from __future__ import annotations

from homeassistant.components.lock import LockEntity
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
    """Set up Hyundai Bluelink lock entities."""
    coordinator: HyundaiBluelinkDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    known_vehicle_ids: set[str] = set()

    def async_add_current_entities() -> None:
        entities: list[HyundaiBluelinkLock] = []
        for vehicle_id in coordinator.data.vehicles:
            if vehicle_id in known_vehicle_ids:
                continue
            known_vehicle_ids.add(vehicle_id)
            entities.append(HyundaiBluelinkLock(coordinator, vehicle_id))
        if entities:
            async_add_entities(entities)

    async_add_current_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_current_entities))


class HyundaiBluelinkLock(HyundaiBluelinkEntity, LockEntity):
    """Hyundai Bluelink lock entity."""

    _attr_translation_key = "vehicle_lock"

    def __init__(
        self,
        coordinator: HyundaiBluelinkDataUpdateCoordinator,
        vehicle_id: str,
    ) -> None:
        """Initialize the lock."""
        super().__init__(coordinator, vehicle_id, "vehicle_lock")

    @property
    def is_locked(self) -> bool | None:
        """Return whether the vehicle is locked when known."""
        return self.vehicle_data.is_locked

    async def async_lock(self, **kwargs: object) -> None:
        """Lock the vehicle."""
        await self.coordinator.async_lock_vehicle(self.vehicle_id)

    async def async_unlock(self, **kwargs: object) -> None:
        """Unlock the vehicle."""
        await self.coordinator.async_unlock_vehicle(self.vehicle_id)
