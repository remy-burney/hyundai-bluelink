from __future__ import annotations

from custom_components.hyundai_bluelink.models import (
    BluelinkCommand,
    BluelinkVehicleData,
)


def _vehicle_data() -> BluelinkVehicleData:
    vehicle = {
        "vin": "KMHP3811SSU125978",
        "vehicleId": "cd7fce8d-ae93-4b5a-94ac-9d31181e0c6f",
        "vehicleName": "MX5 HEV/PHEV (NEW TM) 24",
        "nickname": "SANTA FE",
        "year": "2025",
        "type": "HV",
        "ccuCCS2ProtocolSupport": 1,
    }
    status = {
        "resMsg": {
            "lastUpdateTime": "20260603021531",
            "state": {
                "Vehicle": {
                    "Date": "20260603021526.000",
                    "Cabin": {
                        "Door": {
                            "Row1": {
                                "Driver": {"Open": 0, "Lock": 0},
                                "Passenger": {"Open": 0, "Lock": 0},
                            },
                            "Row2": {
                                "Left": {"Open": 0, "Lock": 0},
                                "Right": {"Open": 0, "Lock": 0},
                            },
                        },
                        "Window": {
                            "Row1": {
                                "Driver": {"Open": 0, "OpenLevel": 0},
                                "Passenger": {"Open": 0, "OpenLevel": 0},
                            },
                            "Row2": {
                                "Left": {"Open": 0, "OpenLevel": 0},
                                "Right": {"Open": 0, "OpenLevel": 0},
                            },
                        },
                    },
                    "Body": {
                        "Hood": {"Open": 0},
                        "Trunk": {"Open": 0},
                        "Sunroof": {"Glass": {"Open": 0}},
                    },
                    "Chassis": {
                        "DrivingMode": {"State": "Eco"},
                        "Axle": {
                            "Tire": {"PressureLow": 0, "PressureUnit": 0},
                            "Row1": {
                                "Left": {"Tire": {"PressureLow": 0, "Pressure": 255}},
                                "Right": {"Tire": {"PressureLow": 0, "Pressure": 255}},
                            },
                            "Row2": {
                                "Left": {"Tire": {"PressureLow": 0, "Pressure": 255}},
                                "Right": {"Tire": {"PressureLow": 0, "Pressure": 255}},
                            },
                        },
                    },
                    "Drivetrain": {
                        "DrivingReady": 0,
                        "FuelSystem": {
                            "DTE": {"Total": 922, "Unit": 1},
                            "FuelLevel": 100,
                            "LowFuelWarning": 0,
                            "AverageFuelEconomy": {
                                "Drive": 17.1,
                                "AfterRefuel": 14.2,
                                "Accumulated": 15.3,
                                "Unit": 0,
                            },
                        },
                        "Odometer": 14172,
                        "Transmission": {"ParkingPosition": 1},
                    },
                    "Electronics": {"Battery": {"Level": 89}},
                    "Green": {
                        "BatteryManagement": {
                            "SoH": {"Ratio": 100},
                            "BatteryRemain": {"Ratio": 63},
                        }
                    },
                    "Service": {
                        "ConnectedCar": {
                            "RemoteControl": {"Available": 1, "WaitingTime": 336}
                        }
                    },
                    "RemoteControl": {"SleepMode": 1},
                }
            },
        }
    }
    location = {
        "resMsg": {
            "coord": {"lat": -38.052102, "lon": 145.380688, "alt": 0},
            "head": 117.5999984741211,
            "speed": {"value": 0, "unit": 0},
            "time": "20260603121224",
        }
    }
    return BluelinkVehicleData(vehicle=vehicle, status=status, location=location)


def test_vehicle_data_extracts_ccs2_hybrid_status() -> None:
    data = _vehicle_data()

    assert data.vehicle_id == "cd7fce8d-ae93-4b5a-94ac-9d31181e0c6f"
    assert data.name == "SANTA FE"
    assert data.vin == "KMHP3811SSU125978"
    assert data.model == "MX5 HEV/PHEV (NEW TM) 24"
    assert data.odometer_km == 14172
    assert data.range_km == 922
    assert data.fuel_level == 100
    assert data.hybrid_battery_level == 63
    assert data.aux_battery_level == 89
    assert data.fuel_efficiency_accumulated == 15.3
    assert data.driving_mode == "Eco"
    assert data.remote_control_available is True
    assert data.remote_control_waiting_time == 336


def test_vehicle_data_extracts_open_closed_and_location_status() -> None:
    data = _vehicle_data()

    assert data.is_engine_running is False
    assert data.is_locked is True
    assert data.all_doors_closed is True
    assert data.all_windows_closed is True
    assert data.is_hood_open is False
    assert data.is_trunk_open is False
    assert data.is_sunroof_open is False
    assert data.has_low_tire_pressure is False
    assert data.tire_pressure_kpa == {
        "front_left": 255,
        "front_right": 255,
        "rear_left": 255,
        "rear_right": 255,
    }
    assert data.latitude == -38.052102
    assert data.longitude == 145.380688
    assert data.heading == 117.5999984741211


def test_command_definitions_map_to_upstream_client_methods() -> None:
    commands = {command.key: command for command in BluelinkCommand.all()}

    assert commands["start_engine"].client_method == "async_start_engine"
    assert commands["stop_engine"].client_method == "async_stop_engine"
    assert commands["horn"].client_method == "async_horn"
    assert commands["light"].client_method == "async_light"
    assert commands["horn_light"].client_method == "async_horn_light"
    assert commands["open_windows"].client_method == "async_open_windows"
    assert commands["close_windows"].client_method == "async_close_windows"
    assert commands["refresh"].requires_pin is False
    assert commands["start_engine"].requires_pin is True
