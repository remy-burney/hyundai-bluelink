"""Persistent Vacation override for Bluelink polling and remote controls."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HyundaiBluelinkDataUpdateCoordinator
from .entity import HyundaiBluelinkEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose the account's Vacation setting on each vehicle device."""
    coordinator: HyundaiBluelinkDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    known: set[str] = set()

    def async_add_current_entities() -> None:
        entities = []
        for vehicle_id in coordinator.data.vehicles:
            if vehicle_id not in known:
                known.add(vehicle_id)
                entities.append(HyundaiBluelinkVacationSwitch(coordinator, vehicle_id))
        if entities:
            async_add_entities(entities)

    async_add_current_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_current_entities))


class HyundaiBluelinkVacationSwitch(HyundaiBluelinkEntity, SwitchEntity):
    """Pause the entire account, including login, across HA restarts."""

    _attr_translation_key = "vacation"
    _attr_icon = "mdi:beach"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: HyundaiBluelinkDataUpdateCoordinator, vehicle_id: str
    ) -> None:
        super().__init__(coordinator, vehicle_id, "vacation")

    @property
    def available(self) -> bool:
        """The local override must work even when Hyundai cannot be reached."""
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.vacation

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_vacation(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_vacation(False)
