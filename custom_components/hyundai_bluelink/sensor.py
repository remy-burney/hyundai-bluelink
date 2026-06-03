from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfPressure, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HyundaiBluelinkDataUpdateCoordinator
from .entity import HyundaiBluelinkEntity
from .models import BluelinkVehicleData

SensorValueFn = Callable[[BluelinkVehicleData], Any]


@dataclass(frozen=True, kw_only=True)
class HyundaiBluelinkSensorEntityDescription(SensorEntityDescription):
    """Description for a Hyundai Bluelink sensor."""

    value_fn: SensorValueFn


SENSOR_DESCRIPTIONS: tuple[HyundaiBluelinkSensorEntityDescription, ...] = (
    HyundaiBluelinkSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.odometer_km,
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="range",
        translation_key="range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_fn=lambda data: data.range_km,
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="fuel_level",
        translation_key="fuel_level",
        icon="mdi:gas-station",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.fuel_level,
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="hybrid_battery_level",
        translation_key="hybrid_battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.hybrid_battery_level,
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="aux_battery_level",
        translation_key="aux_battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.aux_battery_level,
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="fuel_efficiency_accumulated",
        translation_key="fuel_efficiency_accumulated",
        icon="mdi:gas-station",
        native_unit_of_measurement="km/L",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.fuel_efficiency_accumulated,
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="remote_control_waiting_time",
        translation_key="remote_control_waiting_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: data.remote_control_waiting_time,
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="front_left_tire_pressure",
        translation_key="front_left_tire_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.KPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.tire_pressure_kpa["front_left"],
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="front_right_tire_pressure",
        translation_key="front_right_tire_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.KPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.tire_pressure_kpa["front_right"],
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="rear_left_tire_pressure",
        translation_key="rear_left_tire_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.KPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.tire_pressure_kpa["rear_left"],
    ),
    HyundaiBluelinkSensorEntityDescription(
        key="rear_right_tire_pressure",
        translation_key="rear_right_tire_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.KPA,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.tire_pressure_kpa["rear_right"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai Bluelink sensors."""
    coordinator: HyundaiBluelinkDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    known_vehicle_ids: set[str] = set()

    def async_add_current_entities() -> None:
        entities: list[HyundaiBluelinkSensor] = []
        for vehicle_id in coordinator.data.vehicles:
            if vehicle_id in known_vehicle_ids:
                continue
            known_vehicle_ids.add(vehicle_id)
            entities.extend(
                HyundaiBluelinkSensor(coordinator, vehicle_id, description)
                for description in SENSOR_DESCRIPTIONS
            )
        if entities:
            async_add_entities(entities)

    async_add_current_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_current_entities))


class HyundaiBluelinkSensor(HyundaiBluelinkEntity, SensorEntity):
    """Hyundai Bluelink sensor entity."""

    entity_description: HyundaiBluelinkSensorEntityDescription

    def __init__(
        self,
        coordinator: HyundaiBluelinkDataUpdateCoordinator,
        vehicle_id: str,
        description: HyundaiBluelinkSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.vehicle_data)
