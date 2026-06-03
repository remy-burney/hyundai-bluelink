from __future__ import annotations

from typing import Any

from .const import ATTR_VEHICLE_ID, DOMAIN
from .models import BluelinkCommand

PLATFORMS = [
    "sensor",
    "binary_sensor",
    "device_tracker",
    "lock",
    "button",
]


async def async_setup(hass: Any, config: dict[str, Any]) -> bool:
    """Set up domain services."""
    import voluptuous as vol

    hass.data.setdefault(DOMAIN, {})
    service_schema = vol.Schema({vol.Optional(ATTR_VEHICLE_ID): str})

    async def async_handle_command(call: Any) -> None:
        command = next(
            command for command in BluelinkCommand.all() if command.key == call.service
        )
        vehicle_id = call.data.get(ATTR_VEHICLE_ID)
        coordinator = _coordinator_for_service(hass, vehicle_id)
        await coordinator.async_execute_command(command, vehicle_id)

    for command in BluelinkCommand.all():
        hass.services.async_register(
            DOMAIN,
            command.key,
            async_handle_command,
            schema=service_schema,
        )

    return True


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Hyundai Bluelink from a config entry."""
    from .client import async_create_client
    from .coordinator import HyundaiBluelinkDataUpdateCoordinator

    client = await async_create_client(hass, entry.data)
    coordinator = HyundaiBluelinkDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a config entry."""
    from .client import async_close_client

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await async_close_client(coordinator.client)
    return unload_ok


async def _async_update_listener(
    hass: Any,
    entry: Any,
) -> None:
    """Reload the config entry after options or reconfigure updates."""
    await hass.config_entries.async_reload(entry.entry_id)


def _coordinator_for_service(
    hass: Any,
    vehicle_id: str | None,
) -> Any:
    """Resolve the coordinator that should handle a domain service call."""
    from homeassistant.exceptions import HomeAssistantError

    coordinators = list(hass.data.get(DOMAIN, {}).values())
    if not coordinators:
        raise HomeAssistantError("No Hyundai Bluelink config entries are loaded.")
    if vehicle_id:
        for coordinator in coordinators:
            if coordinator.data and vehicle_id in coordinator.data.vehicles:
                return coordinator
        raise HomeAssistantError(f"Unknown Bluelink vehicle ID: {vehicle_id}")
    if len(coordinators) == 1:
        return coordinators[0]
    raise HomeAssistantError(
        "vehicle_id is required when multiple accounts are loaded."
    )
