from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Self
from zoneinfo import ZoneInfo

CCS2_DRIVER_DOOR = "Cabin.Door.Row1.Driver"
CCS2_PASSENGER_DOOR = "Cabin.Door.Row1.Passenger"
CCS2_REAR_LEFT_DOOR = "Cabin.Door.Row2.Left"
CCS2_REAR_RIGHT_DOOR = "Cabin.Door.Row2.Right"

CCS2_DRIVER_WINDOW = "Cabin.Window.Row1.Driver"
CCS2_PASSENGER_WINDOW = "Cabin.Window.Row1.Passenger"
CCS2_REAR_LEFT_WINDOW = "Cabin.Window.Row2.Left"
CCS2_REAR_RIGHT_WINDOW = "Cabin.Window.Row2.Right"

AU_TIMEZONE = ZoneInfo("Australia/Sydney")


@dataclass(frozen=True, slots=True)
class BluelinkCommand:
    """Remote vehicle command exposed through Home Assistant entities/services."""

    key: str
    translation_key: str
    client_method: str
    icon: str
    requires_pin: bool = True

    @classmethod
    def all(cls) -> tuple[Self, ...]:
        """Return all command definitions."""
        return (
            cls(
                key="refresh",
                translation_key="refresh",
                client_method="async_refresh_vehicle_status",
                icon="mdi:refresh",
                requires_pin=False,
            ),
            cls(
                key="live_refresh",
                translation_key="live_refresh",
                client_method="async_live_refresh_vehicle_status",
                icon="mdi:refresh-circle",
            ),
            cls(
                key="start_engine",
                translation_key="start_engine",
                client_method="async_start_engine",
                icon="mdi:power",
            ),
            cls(
                key="stop_engine",
                translation_key="stop_engine",
                client_method="async_stop_engine",
                icon="mdi:power-off",
            ),
            cls(
                key="horn",
                translation_key="horn",
                client_method="async_horn",
                icon="mdi:bullhorn",
            ),
            cls(
                key="light",
                translation_key="light",
                client_method="async_light",
                icon="mdi:car-light-high",
            ),
            cls(
                key="horn_light",
                translation_key="horn_light",
                client_method="async_horn_light",
                icon="mdi:alarm-light",
            ),
            cls(
                key="open_windows",
                translation_key="open_windows",
                client_method="async_open_windows",
                icon="mdi:car-window",
            ),
            cls(
                key="close_windows",
                translation_key="close_windows",
                client_method="async_close_windows",
                icon="mdi:car-window",
            ),
            cls(
                key="window_ventilation",
                translation_key="window_ventilation",
                client_method="async_ventilate_windows",
                icon="mdi:weather-windy",
            ),
        )


@dataclass(frozen=True, slots=True)
class BluelinkVehicleData:
    """Normalized vehicle data produced from the upstream Bluelink client."""

    vehicle: dict[str, Any]
    status: dict[str, Any]
    location: dict[str, Any] | None = None

    @property
    def vehicle_id(self) -> str:
        """Return Hyundai's stable vehicle identifier."""
        return str(self.vehicle["vehicleId"])

    @property
    def vin(self) -> str | None:
        """Return the VIN."""
        return _as_str(self.vehicle.get("vin"))

    @property
    def name(self) -> str:
        """Return the display name."""
        return (
            _as_str(self.vehicle.get("nickname"))
            or _as_str(self.vehicle.get("vehicleName"))
            or self.vehicle_id
        )

    @property
    def model(self) -> str | None:
        """Return the model name."""
        return _as_str(self.vehicle.get("vehicleName"))

    @property
    def year(self) -> str | None:
        """Return the model year."""
        return _as_str(self.vehicle.get("year"))

    @property
    def engine_type(self) -> str | None:
        """Return the vehicle engine type code."""
        return _as_str(self.vehicle.get("type"))

    @property
    def ccs2_supported(self) -> bool:
        """Return true if the vehicle reports CCS2 support."""
        return _as_bool(self.vehicle.get("ccuCCS2ProtocolSupport")) is True

    @property
    def raw_vehicle_state(self) -> dict[str, Any]:
        """Return the nested CCS2 vehicle state, or an empty mapping."""
        state = _get_path(self.status, "resMsg.state.Vehicle")
        return state if isinstance(state, dict) else {}

    @property
    def raw_legacy_state(self) -> dict[str, Any]:
        """Return the legacy status mapping, or an empty mapping."""
        res_msg = _get_path(self.status, "resMsg")
        return res_msg if isinstance(res_msg, dict) else {}

    @property
    def last_updated(self) -> str | None:
        """Return the latest update timestamp in Hyundai's raw format."""
        return _first(
            _get_path(self.status, "resMsg.lastUpdateTime"),
            _get_path(self.raw_vehicle_state, "Date"),
            _get_path(self.raw_legacy_state, "time"),
        )

    @property
    def status_updated_at(self) -> datetime | None:
        """Return vehicle observation time, never the time we polled the cloud."""
        if self.raw_vehicle_state:
            # CCS2 Date is UTC even when the vehicle's Offset says AEST/AEDT.
            return _parse_timestamp(_get_path(self.raw_vehicle_state, "Date"), UTC)
        return _parse_timestamp(_get_path(self.raw_legacy_state, "time"), AU_TIMEZONE)

    def has_recent_running_status(self, now: datetime, max_age: timedelta) -> bool:
        """Avoid fast polling indefinitely on an old engine-on snapshot."""
        stamp = self.status_updated_at
        return (
            self.is_engine_running is True
            and stamp is not None
            and timedelta(0) <= now - stamp <= max_age
        )

    @property
    def odometer_km(self) -> int | None:
        """Return odometer in kilometers."""
        return _as_int(
            _first(
                _get_path(self.raw_vehicle_state, "Drivetrain.Odometer"),
                _get_path(self.raw_legacy_state, "odometer.value"),
            )
        )

    @property
    def range_km(self) -> int | None:
        """Return total vehicle range in kilometers."""
        return _as_int(
            _first(
                _get_path(self.raw_vehicle_state, "Drivetrain.FuelSystem.DTE.Total"),
                _get_path(
                    self.raw_legacy_state,
                    "evStatus.drvDistance.0.rangeByFuel.totalAvailableRange.value",
                ),
            )
        )

    @property
    def fuel_level(self) -> int | None:
        """Return fuel level as a percentage."""
        return _as_int(
            _get_path(self.raw_vehicle_state, "Drivetrain.FuelSystem.FuelLevel")
        )

    @property
    def low_fuel_warning(self) -> bool | None:
        """Return true if the vehicle reports low fuel."""
        return _as_bool(
            _get_path(self.raw_vehicle_state, "Drivetrain.FuelSystem.LowFuelWarning")
        )

    @property
    def hybrid_battery_level(self) -> int | None:
        """Return hybrid or EV battery state of charge as a percentage."""
        return _as_int(
            _first(
                _get_path(
                    self.raw_vehicle_state,
                    "Green.BatteryManagement.StateOfCharge.Displayed",
                ),
                _get_path(
                    self.raw_vehicle_state,
                    "Green.BatteryManagement.BatteryRemain.Ratio",
                ),
                _get_path(self.raw_legacy_state, "evStatus.batteryStatus"),
            )
        )

    @property
    def aux_battery_level(self) -> int | None:
        """Return auxiliary battery state of charge as a percentage."""
        return _as_int(
            _first(
                _get_path(self.raw_vehicle_state, "Electronics.Battery.Level"),
                _get_path(self.raw_legacy_state, "battery.batSoc"),
            )
        )

    @property
    def fuel_efficiency_accumulated(self) -> float | None:
        """Return accumulated average fuel efficiency in the upstream unit."""
        return _as_float(
            _get_path(
                self.raw_vehicle_state,
                "Drivetrain.FuelSystem.AverageFuelEconomy.Accumulated",
            )
        )

    @property
    def driving_mode(self) -> str | None:
        """Return the current driving mode."""
        return _as_str(_get_path(self.raw_vehicle_state, "Chassis.DrivingMode.State"))

    @property
    def is_engine_running(self) -> bool | None:
        """Return whether the drivetrain is ready/running."""
        return _as_bool(
            _first(
                _get_path(self.raw_vehicle_state, "Drivetrain.DrivingReady"),
                _get_path(self.raw_vehicle_state, "DrivingReady"),
                _get_path(self.raw_legacy_state, "engine"),
            )
        )

    @property
    def is_locked(self) -> bool | None:
        """Return lock state when the API field mapping is unambiguous."""
        ccs2_lock_values = [
            _get_path(self.raw_vehicle_state, f"{CCS2_DRIVER_DOOR}.Lock"),
            _get_path(self.raw_vehicle_state, f"{CCS2_PASSENGER_DOOR}.Lock"),
            _get_path(self.raw_vehicle_state, f"{CCS2_REAR_LEFT_DOOR}.Lock"),
            _get_path(self.raw_vehicle_state, f"{CCS2_REAR_RIGHT_DOOR}.Lock"),
        ]
        known_lock_values = [value for value in ccs2_lock_values if value is not None]
        if known_lock_values:
            return all(str(value) == "0" for value in known_lock_values)

        lock_state = _get_path(self.raw_legacy_state, "doorLock")
        if isinstance(lock_state, bool):
            return lock_state
        if isinstance(lock_state, str) and lock_state.lower() in {"locked", "unlocked"}:
            return lock_state.lower() == "locked"
        return None

    @property
    def all_doors_closed(self) -> bool | None:
        """Return true when every reported door is closed."""
        return _all_false(self.door_open_states.values())

    @property
    def all_windows_closed(self) -> bool | None:
        """Return true when every reported window is closed."""
        return _all_false(self.window_open_states.values())

    @property
    def door_open_states(self) -> dict[str, bool | None]:
        """Return open-state booleans for each door."""
        return {
            "front_driver": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_DRIVER_DOOR}.Open")
            ),
            "front_passenger": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_PASSENGER_DOOR}.Open")
            ),
            "rear_left": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_REAR_LEFT_DOOR}.Open")
            ),
            "rear_right": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_REAR_RIGHT_DOOR}.Open")
            ),
        }

    @property
    def window_open_states(self) -> dict[str, bool | None]:
        """Return open-state booleans for each window."""
        return {
            "front_driver": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_DRIVER_WINDOW}.Open")
            ),
            "front_passenger": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_PASSENGER_WINDOW}.Open")
            ),
            "rear_left": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_REAR_LEFT_WINDOW}.Open")
            ),
            "rear_right": _as_bool(
                _get_path(self.raw_vehicle_state, f"{CCS2_REAR_RIGHT_WINDOW}.Open")
            ),
        }

    @property
    def is_hood_open(self) -> bool | None:
        """Return true if the hood is open."""
        return _as_bool(_get_path(self.raw_vehicle_state, "Body.Hood.Open"))

    @property
    def is_trunk_open(self) -> bool | None:
        """Return true if the trunk is open."""
        return _as_bool(_get_path(self.raw_vehicle_state, "Body.Trunk.Open"))

    @property
    def is_sunroof_open(self) -> bool | None:
        """Return true if the sunroof is open."""
        return _as_bool(_get_path(self.raw_vehicle_state, "Body.Sunroof.Glass.Open"))

    @property
    def has_low_tire_pressure(self) -> bool | None:
        """Return true if any tire reports low pressure."""
        values = [
            _get_path(self.raw_vehicle_state, "Chassis.Axle.Tire.PressureLow"),
            _get_path(
                self.raw_vehicle_state,
                "Chassis.Axle.Row1.Left.Tire.PressureLow",
            ),
            _get_path(
                self.raw_vehicle_state,
                "Chassis.Axle.Row1.Right.Tire.PressureLow",
            ),
            _get_path(
                self.raw_vehicle_state,
                "Chassis.Axle.Row2.Left.Tire.PressureLow",
            ),
            _get_path(
                self.raw_vehicle_state,
                "Chassis.Axle.Row2.Right.Tire.PressureLow",
            ),
        ]
        bools = [_as_bool(value) for value in values if value is not None]
        if not bools:
            return None
        return any(bools)

    @property
    def tire_pressure_kpa(self) -> dict[str, int | None]:
        """Return tire pressure by wheel in kPa."""
        return {
            "front_left": _as_int(
                _get_path(
                    self.raw_vehicle_state, "Chassis.Axle.Row1.Left.Tire.Pressure"
                )
            ),
            "front_right": _as_int(
                _get_path(
                    self.raw_vehicle_state,
                    "Chassis.Axle.Row1.Right.Tire.Pressure",
                )
            ),
            "rear_left": _as_int(
                _get_path(
                    self.raw_vehicle_state, "Chassis.Axle.Row2.Left.Tire.Pressure"
                )
            ),
            "rear_right": _as_int(
                _get_path(
                    self.raw_vehicle_state,
                    "Chassis.Axle.Row2.Right.Tire.Pressure",
                )
            ),
        }

    @property
    def remote_control_available(self) -> bool | None:
        """Return whether remote control is available."""
        return _as_bool(
            _get_path(
                self.raw_vehicle_state,
                "Service.ConnectedCar.RemoteControl.Available",
            )
        )

    @property
    def remote_control_waiting_time(self) -> int | None:
        """Return remote-control waiting time in seconds."""
        return _as_int(
            _get_path(
                self.raw_vehicle_state,
                "Service.ConnectedCar.RemoteControl.WaitingTime",
            )
        )

    @property
    def latitude(self) -> float | None:
        """Return vehicle latitude."""
        coords = self._coordinates
        return coords[0] if coords else None

    @property
    def longitude(self) -> float | None:
        """Return vehicle longitude."""
        coords = self._coordinates
        return coords[1] if coords else None

    @property
    def _coordinates(self) -> tuple[float, float] | None:
        """Publish coordinates only as a valid pair."""
        raw_lat = _get_path(self.location or {}, "resMsg.coord.lat")
        raw_lon = _get_path(self.location or {}, "resMsg.coord.lon")
        if isinstance(raw_lat, bool) or isinstance(raw_lon, bool):
            return None
        lat, lon = _as_float(raw_lat), _as_float(raw_lon)
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon

    @property
    def location_updated_at(self) -> datetime | None:
        """Return the AU parked-location source time with daylight saving handled."""
        return _parse_timestamp(
            _get_path(self.location or {}, "resMsg.time"), AU_TIMEZONE
        )

    @property
    def heading(self) -> float | None:
        """Return vehicle heading in degrees."""
        return _as_float(_get_path(self.location or {}, "resMsg.head"))


def _parse_timestamp(value: Any, timezone: tzinfo) -> datetime | None:
    """Parse Hyundai's compact timestamp without inventing missing observations."""
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{14}(?:\.[0-9]{1,6})?", value
    ):
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M%S.%f"):
        try:
            local = datetime.strptime(value, fmt).replace(tzinfo=timezone)
            # Hyundai supplies no offset to distinguish repeated wall times or
            # resolve nonexistent times at daylight-saving transitions.
            if local.utcoffset() != local.replace(fold=1).utcoffset():
                return None
            return local.astimezone(UTC)
        except ValueError:
            pass
    return None


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"1", "true", "on", "open", "yes", "locked", "running"}:
            return True
        if lowered in {"0", "false", "off", "closed", "no", "unlocked", "stopped"}:
            return False
    return None


def _all_false(values: Iterable[bool | None]) -> bool | None:
    known_values = [value for value in values if value is not None]
    if not known_values:
        return None
    return not any(known_values)
