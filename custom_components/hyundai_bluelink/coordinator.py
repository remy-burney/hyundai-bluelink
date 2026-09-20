from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    BluelinkAuthenticationError,
    BluelinkClientProtocol,
    BluelinkConnectionError,
    async_login_client,
)
from .const import (
    CONF_ACTIVE_INTERVAL,
    CONF_IDLE_INTERVAL,
    CONF_PIN,
    CONF_POLLING_SCHEDULE,
    CONF_VACATION,
    DEFAULT_ACTIVE_INTERVAL,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .models import BluelinkCommand, BluelinkVehicleData

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HyundaiBluelinkData:
    """Coordinator data for all vehicles."""

    vehicles: dict[str, BluelinkVehicleData]
    poll_interval: timedelta | None = DEFAULT_SCAN_INTERVAL
    polling_paused: bool = False


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
            config_entry=config_entry,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=False,
        )
        self.config_entry = config_entry
        self.client = client
        self._vehicle_records: list[dict[str, Any]] = []
        self.entry_data = dict(config_entry.data)
        self._options = dict(config_entry.options)
        self._logged_in = False
        self._poll_task: asyncio.Task[HyundaiBluelinkData] | None = None
        self._command_tasks: set[asyncio.Task[Any]] = set()
        self._controls_in_progress: set[str] = set()
        self._unsub_schedule: Callable[[], None] | None = None
        self._store = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.snapshot")
        self.update_interval = self._configured_interval
        self._subscribe_schedule()
        config_entry.async_on_unload(self._unsubscribe_schedule)

    async def _async_setup(self) -> None:
        """Restore last readings locally; Vacation startup must not contact Hyundai."""
        snapshot = await self._store.async_load()
        vehicles = {}
        if isinstance(snapshot, dict) and isinstance(snapshot.get("vehicles"), list):
            for item in snapshot.get("vehicles", []):
                if not isinstance(item, dict) or not all(
                    isinstance(item.get(key), dict)
                    for key in ("vehicle", "status", "location")
                ):
                    continue
                try:
                    vehicle = BluelinkVehicleData(**item)
                    vehicles[_vehicle_id(vehicle.vehicle)] = vehicle
                except (TypeError, BluelinkConnectionError):
                    continue
        self._vehicle_records = [item.vehicle for item in vehicles.values()]
        self.data = HyundaiBluelinkData(vehicles, self.update_interval, self.vacation)

    async def _async_update_data(self) -> HyundaiBluelinkData:
        """Fetch all vehicle telemetry in one coordinator update."""
        self.update_interval = self._configured_interval
        if self.vacation:
            return self._current_data()
        self._poll_task = asyncio.create_task(self._async_fetch_data())
        try:
            return await self._poll_task
        except asyncio.CancelledError:
            if self.vacation:
                return self._current_data()
            raise
        except BluelinkAuthenticationError as exc:
            raise ConfigEntryAuthFailed from exc
        except Exception as exc:
            # Rate limits and connection failures use the slower configured cadence.
            self.update_interval = timedelta(minutes=self._idle_minutes)
            raise UpdateFailed(str(exc)) from exc
        finally:
            self._poll_task = None

    async def _async_fetch_data(self) -> HyundaiBluelinkData:
        """Run network work in a task that Vacation can cancel."""
        if not self._logged_in:
            await async_login_client(self.client, self.config_entry.data)
            self._logged_in = True
        self._ensure_not_on_vacation()
        vehicle_records = await self._async_get_vehicle_records()
        if vehicle_records:
            self._vehicle_records = vehicle_records
        self._ensure_not_on_vacation()
        vehicles = await _async_gather(
            *(self._async_fetch_vehicle(record) for record in self._vehicle_records)
        )
        self._ensure_not_on_vacation()
        data = HyundaiBluelinkData(
            vehicles={vehicle.vehicle_id: vehicle for vehicle in vehicles},
            poll_interval=self.update_interval,
        )
        # Store telemetry only, never the client's credentials or authentication state.
        try:
            await self._store.async_save(
                {
                    "vehicles": [
                        {
                            "vehicle": v.vehicle,
                            "status": v.status,
                            "location": v.location,
                        }
                        for v in vehicles
                    ]
                }
            )
        except OSError:
            _LOGGER.warning("Could not save the local Bluelink telemetry snapshot")
        return data

    @property
    def vacation(self) -> bool:
        """Whether all requests for this account are paused."""
        return bool(self.config_entry.options.get(CONF_VACATION, False))

    @property
    def _idle_minutes(self) -> int:
        return int(
            self.config_entry.options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL)
        )

    @property
    def _configured_interval(self) -> timedelta | None:
        if self.vacation:
            return None
        schedule = self.config_entry.options.get(CONF_POLLING_SCHEDULE)
        if schedule and self.hass.states.is_state(schedule, "on"):
            return timedelta(
                minutes=int(
                    self.config_entry.options.get(
                        CONF_ACTIVE_INTERVAL, DEFAULT_ACTIVE_INTERVAL
                    )
                )
            )
        return timedelta(minutes=self._idle_minutes)

    def _current_data(self) -> HyundaiBluelinkData:
        return HyundaiBluelinkData(
            self.data.vehicles if self.data else {}, self.update_interval, self.vacation
        )

    def _unsubscribe_schedule(self) -> None:
        if self._unsub_schedule:
            self._unsub_schedule()
            self._unsub_schedule = None

    def _subscribe_schedule(self) -> None:
        self._unsubscribe_schedule()
        if schedule := self.config_entry.options.get(CONF_POLLING_SCHEDULE):
            self._unsub_schedule = async_track_state_change_event(
                self.hass, [schedule], self._async_schedule_changed
            )

    async def _async_schedule_changed(self, event: Any) -> None:
        """Apply weekly helper transitions without reauthenticating the account."""
        previous = self.update_interval
        self.update_interval = self._configured_interval
        if self.update_interval == previous or self.data is None:
            return
        self.async_set_updated_data(self._current_data())
        if (
            not self._poll_task
            and self.update_interval
            and (previous is None or self.update_interval < previous)
        ):
            await self.async_request_refresh()

    async def async_apply_options(self) -> None:
        """Apply new settings without a login/reload or unwanted telemetry request."""
        if self._options == dict(self.config_entry.options):
            return
        was_on_vacation = bool(self._options.get(CONF_VACATION, False))
        self._options = dict(self.config_entry.options)
        self._subscribe_schedule()
        self.update_interval = self._configured_interval
        if self.vacation:
            await self._async_cancel_requests()
        self.async_set_updated_data(self._current_data())
        if was_on_vacation and not self.vacation:
            await self.async_request_refresh()

    async def async_set_vacation(self, enabled: bool) -> None:
        """Persist the override before applying it, including during a restart."""
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={**self.config_entry.options, CONF_VACATION: enabled},
        )
        await self.async_apply_options()

    def _ensure_not_on_vacation(self) -> None:
        if self.vacation:
            raise HomeAssistantError(
                "Vacation mode is on. Turn it off before refreshing "
                "or controlling the car."
            )

    async def _async_cancel_requests(self) -> None:
        tasks = list(self._command_tasks)
        if self._poll_task:
            tasks.append(self._poll_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def async_shutdown(self) -> None:
        """Remove listeners and stop network work before closing the client."""
        await super().async_shutdown()
        self._unsubscribe_schedule()
        await self._async_cancel_requests()

    async def _async_run_client_command(
        self, method: Callable, *args: Any, **kwargs: Any
    ) -> Any:
        """Allow Vacation to cancel a command's remaining network requests too."""
        self._ensure_not_on_vacation()
        task = asyncio.create_task(method(*args, **kwargs))
        self._command_tasks.add(task)
        try:
            return await task
        except asyncio.CancelledError:
            self._ensure_not_on_vacation()
            raise
        finally:
            self._command_tasks.discard(task)

    async def _async_run_vehicle_control(
        self, method: Callable, vehicle_id: str, **kwargs: Any
    ) -> Any:
        """Reject overlapping vehicle controls without queueing a later action."""
        if vehicle_id in self._controls_in_progress:
            raise HomeAssistantError(
                "A remote command for this vehicle is already in progress. "
                "Wait for it to finish before trying again."
            )
        self._controls_in_progress.add(vehicle_id)
        try:
            return await self._async_run_client_command(method, vehicle_id, **kwargs)
        finally:
            self._controls_in_progress.discard(vehicle_id)

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
        status, location = await _async_gather(
            self.client.async_get_vehicle_status(vehicle_id),
            self.client.async_get_vehicle_location(vehicle_id),
        )
        vehicle = BluelinkVehicleData(
            vehicle=vehicle_record,
            status=_as_mapping(status),
            location=_as_mapping(location),
        )
        previous = self.data.vehicles.get(vehicle_id) if self.data else None
        if previous and previous.latitude is not None:
            previous_time = previous.location_updated_at
            incoming_time = vehicle.location_updated_at
            if vehicle.latitude is None or (
                previous_time is not None
                and (incoming_time is None or incoming_time < previous_time)
            ):
                # Preserve the original observation time too. Old cloud responses
                # must not move the car backwards or create false zone crossings.
                vehicle = replace(vehicle, location=previous.location)
        return vehicle

    async def async_execute_command(
        self,
        command: BluelinkCommand,
        vehicle_id: str | None = None,
    ) -> None:
        """Execute a remote command through the upstream client."""
        self._ensure_not_on_vacation()
        resolved_vehicle_id = self._resolve_vehicle_id(vehicle_id)

        if command.key == "refresh":
            await self._async_refresh_vehicle_now(resolved_vehicle_id)
            await self.async_request_refresh()
            return

        pin = self._remote_control_pin
        if command.requires_pin and not pin:
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
                kwargs["pin"] = pin
            await self._async_run_vehicle_control(method, resolved_vehicle_id, **kwargs)
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
        self._ensure_not_on_vacation()
        pin = self._remote_control_pin
        if not pin:
            raise HomeAssistantError(
                "This Bluelink action requires a PIN. Reconfigure the integration "
                "and store the remote-control PIN first."
            )
        method = getattr(self.client, method_name, None)
        if method is None:
            raise HomeAssistantError(
                f"The upstream Bluelink client does not implement {method_name}."
            )
        await self._async_run_vehicle_control(
            method,
            self._resolve_vehicle_id(vehicle_id),
            pin=pin,
        )
        await self.async_request_refresh()

    async def _async_refresh_vehicle_now(self, vehicle_id: str) -> None:
        """Request an immediate vehicle refresh if the upstream client supports it."""
        method = getattr(self.client, "async_refresh_vehicle_status", None)
        if method is not None:
            await self._async_run_client_command(method, vehicle_id)

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

    @property
    def _remote_control_pin(self) -> str | None:
        """Return the configured remote-control PIN."""
        if CONF_PIN in self.config_entry.options:
            return self.config_entry.options.get(CONF_PIN) or None
        return self.config_entry.data.get(CONF_PIN) or None


async def _async_gather(*requests: Any) -> list[Any]:
    """Finish/cancel every child before returning, including on partial failure."""
    tasks = [asyncio.create_task(request) for request in requests]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        # gather alone leaves siblings running after one fails. They could then
        # keep contacting Hyundai after Vacation or an integration unload.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


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
