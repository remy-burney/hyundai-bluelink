"""Source freshness, coordinate validation and polling behaviour."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.hyundai_bluelink.models import BluelinkVehicleData


def vehicle(*, running=True, stamp="20260920070000.000", location=None):
    return BluelinkVehicleData(
        vehicle={"vehicleId": "test-car"},
        status={
            "resMsg": {
                "state": {
                    "Vehicle": {
                        "Date": stamp,
                        "DrivingReady": running,
                    }
                }
            }
        },
        location=location,
    )


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("20260920170000", datetime(2026, 9, 20, 7, tzinfo=UTC)),
        ("20261220180000", datetime(2026, 12, 20, 7, tzinfo=UTC)),
        ("bad", None),
        ("20269999120000", None),
        (None, None),
        ("20260405023000", None),
        ("20261004023000", None),
        ("20269121700", None),
    ],
)
def test_location_time_uses_sydney_with_dst(stamp, expected):
    data = vehicle(location={"resMsg": {"time": stamp}})
    assert data.location_updated_at == expected


def test_ccs2_status_time_is_utc():
    assert vehicle().status_updated_at == datetime(2026, 9, 20, 7, tzinfo=UTC)


def test_legacy_status_time_is_local():
    data = BluelinkVehicleData(
        vehicle={"vehicleId": "test-car"},
        status={"resMsg": {"time": "20261220180000", "engine": True}},
    )
    assert data.status_updated_at == datetime(2026, 12, 20, 7, tzinfo=UTC)


@pytest.mark.parametrize(
    ("running", "stamp", "active"),
    [
        (True, "20260920070000.000", True),
        (False, "20260920070000.000", False),
        (None, "20260920070000.000", False),
        (True, "20260920064500.000", True),
        (True, "20260920064459.000", False),
        (True, "20260920080000.000", False),
        (True, None, False),
        (True, "bad", False),
    ],
)
def test_fast_polling_requires_recent_running_status(running, stamp, active):
    assert (
        vehicle(running=running, stamp=stamp).has_recent_running_status(
            datetime(2026, 9, 20, 7, tzinfo=UTC), timedelta(minutes=15)
        )
        is active
    )


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (91, 145),
        (-38, 181),
        ("nan", 145),
        (-38, "inf"),
        (None, 145),
        (-38, None),
        (True, 145),
    ],
)
def test_invalid_coordinates_are_not_published(lat, lon):
    data = vehicle(location={"resMsg": {"coord": {"lat": lat, "lon": lon}}})
    assert data.latitude is None
    assert data.longitude is None


def test_valid_coordinates_and_source_timestamp_are_stable():
    data = vehicle(
        location={
            "resMsg": {
                "coord": {"lat": "-38.1", "lon": "145.1"},
                "time": "20260920170000",
                "head": 120,
            }
        }
    )
    assert (data.latitude, data.longitude, data.heading) == (-38.1, 145.1, 120)
    assert data.location_updated_at == datetime(2026, 9, 20, 7, tzinfo=UTC)
