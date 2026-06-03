from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HyundaiBluelinkDataUpdateCoordinator
from .models import BluelinkVehicleData


class HyundaiBluelinkEntity(CoordinatorEntity[HyundaiBluelinkDataUpdateCoordinator]):
    """Base entity for Hyundai Bluelink vehicle entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HyundaiBluelinkDataUpdateCoordinator,
        vehicle_id: str,
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.vehicle_id = vehicle_id
        self._attr_unique_id = f"{vehicle_id}_{key}"

    @property
    def vehicle_data(self) -> BluelinkVehicleData:
        """Return the current coordinator data for this vehicle."""
        return self.coordinator.data.vehicles[self.vehicle_id]

    @property
    def device_info(self) -> DeviceInfo:
        """Return the Home Assistant device metadata for this vehicle."""
        vehicle = self.vehicle_data
        identifier = vehicle.vin or vehicle.vehicle_id
        return DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer=MANUFACTURER,
            name=vehicle.name,
            model=vehicle.model,
            serial_number=vehicle.vin,
            sw_version=f"CCS2={int(vehicle.ccs2_supported)}",
        )
