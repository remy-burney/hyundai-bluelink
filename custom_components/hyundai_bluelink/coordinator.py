from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    BluelinkAuthenticationError,
    BluelinkClientProtocol,
    BluelinkConnectionError,
    async_login_client,
)
from .const import CONF_PIN, DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import BluelinkCommand, BluelinkVehicleData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HyundaiBluelinkData:
    """Coordinator data for all vehicles."""

    vehicles: dict[str, BluelinkVehicleData]


class HyundaiBluelinkDataUpdateCoordinator(DataUpdateCoordinator[HyundaiBluelinkData]):
    """Coordinate Bluelink polling across all entity platforms."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: BluelinkClientProtocol,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=False,
        )
        self.config_entry = config_entry
        self.client = client
        self._vehicle_records: list[dict[str, Any]] = []

    async def _async_setup(self) -> None:
        """Authenticate and discover vehicles before the first refresh."""
        try:
            await async_login_client(self.client, self.config_entry.data)
            self._vehicle_records = await self._async_get_vehicle_records()
        except BluelinkAuthenticationError as exc:
            raise ConfigEntryAuthFailed from exc
        except BluelinkConnectionError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def _async_update_data(self) -> HyundaiBluelinkData:
        """Fetch all vehicle telemetry in one coordinator update."""
        try:
            vehicle_records = await self._async_get_vehicle_records()
            if vehicle_records:
                self._vehicle_records = vehicle_records

            vehicles = await asyncio.gather(
                *(self._async_fetch_vehicle(record) for record in self._vehicle_records)
            )
        except BluelinkAuthenticationError as exc:
            raise ConfigEntryAuthFailed from exc
        except BluelinkConnectionError as exc:
            raise UpdateFailed(str(exc)) from exc
        except Exception as exc:
            raise UpdateFailed(str(exc)) from exc

        return HyundaiBluelinkData(
            vehicles={vehicle.vehicle_id: vehicle for vehicle in vehicles}
        )

    async def _async_get_vehicle_records(self) -> list[dict[str, Any]]:
        """Return normalized vehicle records from the upstream client."""
        vehicles = await self.client.async_get_vehicles()
        return [_as_mapping(vehicle) for vehicle in vehicles]

    async def _async_fetch_vehicle(
        self,
        vehicle_record: dict[str, Any],
    ) -> BluelinkVehicleData:
        """Fetch telemetry for one vehicle."""
        vehicle_id = _vehicle_id(vehicle_record)
        status, location = await asyncio.gather(
            self.client.async_get_vehicle_status(vehicle_id),
            self.client.async_get_vehicle_location(vehicle_id),
        )
        return BluelinkVehicleData(
            vehicle=vehicle_record,
            status=_as_mapping(status),
            location=_as_mapping(location),
        )

    async def async_execute_command(
        self,
        command: BluelinkCommand,
        vehicle_id: str | None = None,
    ) -> None:
        """Execute a remote command through the upstream client."""
        resolved_vehicle_id = self._resolve_vehicle_id(vehicle_id)

        if command.key == "refresh":
            await self._async_refresh_vehicle_now(resolved_vehicle_id)
            await self.async_request_refresh()
            return

        if command.requires_pin and not self.config_entry.data.get(CONF_PIN):
            raise HomeAssistantError(
                "This Bluelink action requires a PIN. Reconfigure the integration "
                "and store the remote-control PIN first."
            )

        method = getattr(self.client, command.client_method, None)
        if method is None:
            raise HomeAssistantError(
                f"The upstream Bluelink client does not implement "
                f"{command.client_method}."
            )

        try:
            kwargs: dict[str, Any] = {}
            if command.requires_pin:
                kwargs["pin"] = self.config_entry.data[CONF_PIN]
            await method(resolved_vehicle_id, **kwargs)
        except BluelinkAuthenticationError as exc:
            raise ConfigEntryAuthFailed from exc
        except BluelinkConnectionError as exc:
            raise HomeAssistantError(str(exc)) from exc

        await self.async_request_refresh()

    async def async_lock_vehicle(self, vehicle_id: str | None = None) -> None:
        """Lock a vehicle through the upstream client."""
        await self._async_call_pin_command("async_lock", vehicle_id)

    async def async_unlock_vehicle(self, vehicle_id: str | None = None) -> None:
        """Unlock a vehicle through the upstream client."""
        await self._async_call_pin_command("async_unlock", vehicle_id)

    async def _async_call_pin_command(
        self,
        method_name: str,
        vehicle_id: str | None,
    ) -> None:
        """Call a PIN-protected client method."""
        if not self.config_entry.data.get(CONF_PIN):
            raise HomeAssistantError(
                "This Bluelink action requires a PIN. Reconfigure the integration "
                "and store the remote-control PIN first."
            )
        method = getattr(self.client, method_name, None)
        if method is None:
            raise HomeAssistantError(
                f"The upstream Bluelink client does not implement {method_name}."
            )
        await method(
            self._resolve_vehicle_id(vehicle_id),
            pin=self.config_entry.data[CONF_PIN],
        )
        await self.async_request_refresh()

    async def _async_refresh_vehicle_now(self, vehicle_id: str) -> None:
        """Request an immediate vehicle refresh if the upstream client supports it."""
        method = getattr(self.client, "async_refresh_vehicle_status", None)
        if method is not None:
            await method(vehicle_id)

    def _resolve_vehicle_id(self, vehicle_id: str | None) -> str:
        """Resolve a vehicle ID from service/entity input."""
        vehicles = (self.data.vehicles if self.data else {}) or {}
        if vehicle_id:
            if vehicle_id not in vehicles:
                raise HomeAssistantError(f"Unknown Bluelink vehicle ID: {vehicle_id}")
            return vehicle_id
        if len(vehicles) == 1:
            return next(iter(vehicles))
        raise HomeAssistantError("vehicle_id is required when multiple vehicles exist.")


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        return as_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _vehicle_id(vehicle: dict[str, Any]) -> str:
    vehicle_id = (
        vehicle.get("vehicleId") or vehicle.get("vehicle_id") or vehicle.get("id")
    )
    if not vehicle_id:
        raise BluelinkConnectionError("Vehicle record did not include a vehicle ID.")
    return str(vehicle_id)
