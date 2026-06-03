from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HyundaiBluelinkDataUpdateCoordinator
from .entity import HyundaiBluelinkEntity
from .models import BluelinkCommand


@dataclass(frozen=True, kw_only=True)
class HyundaiBluelinkButtonEntityDescription(ButtonEntityDescription):
    """Description for a Hyundai Bluelink button."""

    command: BluelinkCommand


BUTTON_DESCRIPTIONS: tuple[HyundaiBluelinkButtonEntityDescription, ...] = tuple(
    HyundaiBluelinkButtonEntityDescription(
        key=command.key,
        translation_key=command.translation_key,
        icon=command.icon,
        command=command,
    )
    for command in BluelinkCommand.all()
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hyundai Bluelink button entities."""
    coordinator: HyundaiBluelinkDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]
    known_vehicle_ids: set[str] = set()

    def async_add_current_entities() -> None:
        entities: list[HyundaiBluelinkButton] = []
        for vehicle_id in coordinator.data.vehicles:
            if vehicle_id in known_vehicle_ids:
                continue
            known_vehicle_ids.add(vehicle_id)
            entities.extend(
                HyundaiBluelinkButton(coordinator, vehicle_id, description)
                for description in BUTTON_DESCRIPTIONS
            )
        if entities:
            async_add_entities(entities)

    async_add_current_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_current_entities))


class HyundaiBluelinkButton(HyundaiBluelinkEntity, ButtonEntity):
    """Hyundai Bluelink remote command button."""

    entity_description: HyundaiBluelinkButtonEntityDescription

    def __init__(
        self,
        coordinator: HyundaiBluelinkDataUpdateCoordinator,
        vehicle_id: str,
        description: HyundaiBluelinkButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Execute the configured remote command."""
        await self.coordinator.async_execute_command(
            self.entity_description.command,
            self.vehicle_id,
        )
