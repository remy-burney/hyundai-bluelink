from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HyundaiBluelinkDataUpdateCoordinator
from .entity import HyundaiBluelinkEntity
from .models import BluelinkVehicleData

BinaryValueFn = Callable[[BluelinkVehicleData], bool | None]


@dataclass(frozen=True, kw_only=True)
class HyundaiBluelinkBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Description for a Hyundai Bluelink binary sensor."""

    value_fn: BinaryValueFn


BINARY_SENSOR_DESCRIPTIONS: tuple[HyundaiBluelinkBinarySensorEntityDescription, ...] = (
    HyundaiBluelinkBinarySensorEntityDescription(
        key="engine_running",
        translation_key="engine_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda data: data.is_engine_running,
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="low_fuel",
        translation_key="low_fuel",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: data.low_fuel_warning,
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="low_tire_pressure",
        translation_key="low_tire_pressure",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda data: data.has_low_tire_pressure,
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="remote_control_available",
        translation_key="remote_control_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: data.remote_control_available,
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="front_driver_door",
        translation_key="front_driver_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda data: data.door_open_states["front_driver"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="front_passenger_door",
        translation_key="front_passenger_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda data: data.door_open_states["front_passenger"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="rear_left_door",
        translation_key="rear_left_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda data: data.door_open_states["rear_left"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="rear_right_door",
        translation_key="rear_right_door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda data: data.door_open_states["rear_right"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="front_driver_window",
        translation_key="front_driver_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda data: data.window_open_states["front_driver"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="front_passenger_window",
        translation_key="front_passenger_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda data: data.window_open_states["front_passenger"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="rear_left_window",
        translation_key="rear_left_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda data: data.window_open_states["rear_left"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="rear_right_window",
        translation_key="rear_right_window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda data: data.window_open_states["rear_right"],
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="hood",
        translation_key="hood",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=lambda data: data.is_hood_open,
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="trunk",
        translation_key="trunk",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=lambda data: data.is_trunk_open,
    ),
    HyundaiBluelinkBinarySensorEntityDescription(
        key="sunroof",
        translation_key="sunroof",
        device_class=BinarySensorDeviceClass.OPENING,
        value_fn=lambda data: data.is_sunroof_open,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai Bluelink binary sensors."""
    coordinator: HyundaiBluelinkDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    known_vehicle_ids: set[str] = set()

    def async_add_current_entities() -> None:
        entities: list[HyundaiBluelinkBinarySensor] = []
        for vehicle_id in coordinator.data.vehicles:
            if vehicle_id in known_vehicle_ids:
                continue
            known_vehicle_ids.add(vehicle_id)
            entities.extend(
                HyundaiBluelinkBinarySensor(coordinator, vehicle_id, description)
                for description in BINARY_SENSOR_DESCRIPTIONS
            )
        if entities:
            async_add_entities(entities)

    async_add_current_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_current_entities))


class HyundaiBluelinkBinarySensor(HyundaiBluelinkEntity, BinarySensorEntity):
    """Hyundai Bluelink binary sensor entity."""

    entity_description: HyundaiBluelinkBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: HyundaiBluelinkDataUpdateCoordinator,
        vehicle_id: str,
        description: HyundaiBluelinkBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        return self.entity_description.value_fn(self.vehicle_data)
