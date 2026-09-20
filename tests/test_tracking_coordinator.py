"""Exercise coordinator scheduling and stale-location handling without HA runtime."""

import asyncio
import importlib
import json
import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.hyundai_bluelink.api import BluelinkConnectionError
from custom_components.hyundai_bluelink.models import (
    BluelinkCommand,
    BluelinkVehicleData,
)


@pytest.fixture
def coordinator_module(monkeypatch):
    class Coordinator:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, *args, **kwargs):
            self.hass = hass
            self.update_interval = kwargs["update_interval"]
            self.data = None
            self.last_update_success = True

        def async_set_updated_data(self, data):
            self.data = data

        async def async_request_refresh(self):
            self.data = await self._async_update_data()

        async def async_shutdown(self):
            pass

    class Store:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, version, key):
            self.hass, self.key = hass, key

        async def async_load(self):
            return self.hass.storage.get(self.key)

        async def async_save(self, data):
            self.hass.storage[self.key] = json.loads(json.dumps(data))

    def track_state(hass, entity_ids, listener):
        hass.schedule_listeners.append(listener)
        return lambda: hass.schedule_listeners.remove(listener)

    names = {
        "homeassistant": {},
        "homeassistant.config_entries": {"ConfigEntry": SimpleNamespace},
        "homeassistant.const": {
            "CONF_PASSWORD": "password",
            "CONF_USERNAME": "username",
        },
        "homeassistant.core": {
            "HomeAssistant": SimpleNamespace,
            "callback": lambda fn: fn,
        },
        "homeassistant.exceptions": {
            "ConfigEntryAuthFailed": type("ConfigEntryAuthFailed", (Exception,), {}),
            "HomeAssistantError": type("HomeAssistantError", (Exception,), {}),
        },
        "homeassistant.helpers": {},
        "homeassistant.helpers.aiohttp_client": {
            "async_get_clientsession": lambda hass: None,
        },
        "homeassistant.helpers.storage": {"Store": Store},
        "homeassistant.helpers.event": {"async_track_state_change_event": track_state},
        "homeassistant.helpers.update_coordinator": {
            "DataUpdateCoordinator": Coordinator,
            "UpdateFailed": type("UpdateFailed", (Exception,), {}),
        },
    }
    for name, attributes in names.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    name = "custom_components.hyundai_bluelink.coordinator"
    monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(name)
    yield module
    sys.modules.pop(name, None)
    sys.modules.pop("custom_components.hyundai_bluelink.client", None)


def build_coordinator(module, *, running=True, options=None, schedule_state="off"):
    status = {
        "resMsg": {
            "state": {
                "Vehicle": {
                    "Date": datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
                    "DrivingReady": running,
                }
            }
        }
    }
    client = SimpleNamespace(
        async_login=AsyncMock(),
        async_get_vehicles=AsyncMock(return_value=[{"vehicleId": "car"}]),
        async_get_vehicle_status=AsyncMock(return_value=status),
        async_get_vehicle_location=AsyncMock(
            return_value={
                "resMsg": {
                    "coord": {"lat": -38, "lon": 145},
                    "time": "20260920170000",
                }
            }
        ),
    )
    hass = SimpleNamespace(
        storage={},
        schedule_listeners=[],
        states=SimpleNamespace(is_state=lambda entity, state: schedule_state == state),
    )
    entry = SimpleNamespace(
        entry_id="test-entry",
        data={"username": "test", "password": "secret", "pin": "1234"},
        options=options or {},
        async_on_unload=lambda fn: None,
    )
    hass.config_entries = SimpleNamespace(
        async_update_entry=lambda entry, **kwargs: setattr(
            entry, "options", kwargs["options"]
        )
    )
    return module.HyundaiBluelinkDataUpdateCoordinator(hass, entry, client)


@pytest.mark.parametrize(
    ("schedule_state", "options", "minutes"),
    [
        ("on", {"polling_schedule": "schedule.car"}, 5),
        ("off", {"polling_schedule": "schedule.car"}, 60),
        ("unavailable", {"polling_schedule": "schedule.car"}, 60),
        ("on", {}, 60),
        ("on", {"polling_schedule": "schedule.car", "active_interval": 7}, 7),
        ("off", {"polling_schedule": "schedule.car", "idle_interval": 120}, 120),
    ],
)
def test_schedule_controls_polling_even_when_engine_is_running(
    coordinator_module, schedule_state, options, minutes
):
    coordinator = build_coordinator(
        coordinator_module, options=options, schedule_state=schedule_state
    )
    asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval == timedelta(minutes=minutes)


def test_connection_failure_backs_off(coordinator_module):
    coordinator = build_coordinator(
        coordinator_module,
        options={"polling_schedule": "schedule.car"},
        schedule_state="on",
    )
    asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval == timedelta(minutes=5)
    coordinator.client.async_get_vehicles.side_effect = BluelinkConnectionError("429")
    with pytest.raises(coordinator_module.UpdateFailed):
        asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval == timedelta(minutes=60)


def test_schedule_change_notifies_entities_without_changing_source_times(
    coordinator_module,
):
    coordinator = build_coordinator(
        coordinator_module,
        options={"polling_schedule": "schedule.car"},
        schedule_state="on",
    )
    active = asyncio.run(coordinator._async_update_data())
    coordinator.hass.states.is_state = lambda entity, state: False
    stale = asyncio.run(coordinator._async_update_data())
    assert active.vehicles == stale.vehicles
    assert active != stale


def test_vacation_restores_snapshot_after_restart_without_contacting_hyundai(
    coordinator_module,
):
    coordinator = build_coordinator(coordinator_module)
    coordinator.data = asyncio.run(coordinator._async_update_data())
    previous = coordinator.data.vehicles["car"]
    restarted = build_coordinator(coordinator_module, options={"vacation": True})
    restarted.hass.storage = coordinator.hass.storage

    async def restart():
        await restarted._async_setup()
        return await restarted._async_update_data()

    restored = asyncio.run(restart())
    assert restored.vehicles["car"] == previous
    assert restored.polling_paused is True
    assert restarted.update_interval is None
    for method in vars(restarted.client).values():
        method.assert_not_awaited()
    assert "secret" not in json.dumps(restarted.hass.storage)
    assert "1234" not in json.dumps(restarted.hass.storage)


def test_vacation_with_no_snapshot_does_not_login(coordinator_module):
    coordinator = build_coordinator(coordinator_module, options={"vacation": True})

    async def setup():
        await coordinator._async_setup()
        return await coordinator._async_update_data()

    data = asyncio.run(setup())
    assert data.vehicles == {}
    assert data.polling_paused
    coordinator.client.async_login.assert_not_awaited()


@pytest.mark.parametrize("command", BluelinkCommand.all())
def test_every_command_is_blocked_in_vacation(coordinator_module, command):
    coordinator = build_coordinator(coordinator_module, options={"vacation": True})
    method = AsyncMock()
    setattr(coordinator.client, command.client_method, method)
    with pytest.raises(coordinator_module.HomeAssistantError, match="Vacation"):
        asyncio.run(coordinator.async_execute_command(command, "car"))
    method.assert_not_awaited()


@pytest.mark.parametrize("method", ["async_lock_vehicle", "async_unlock_vehicle"])
def test_lock_commands_are_blocked_in_vacation(coordinator_module, method):
    coordinator = build_coordinator(coordinator_module, options={"vacation": True})
    with pytest.raises(coordinator_module.HomeAssistantError, match="Vacation"):
        asyncio.run(getattr(coordinator, method)("car"))


def test_vacation_preserves_options_and_resumes_polling(coordinator_module):
    coordinator = build_coordinator(
        coordinator_module,
        options={
            "pin": "5678",
            "polling_schedule": "schedule.car",
            "idle_interval": 90,
        },
    )

    async def toggle():
        coordinator.data = await coordinator._async_update_data()
        await coordinator.async_set_vacation(True)
        paused = coordinator.data
        assert coordinator.update_interval is None
        assert coordinator.config_entry.options["vacation"] is True
        await coordinator._async_update_data()
        await coordinator.async_set_vacation(False)
        return paused

    paused = asyncio.run(toggle())
    assert paused.polling_paused
    assert not coordinator.data.polling_paused
    assert coordinator.update_interval == timedelta(minutes=90)
    assert coordinator.config_entry.options["pin"] == "5678"
    assert coordinator.config_entry.options["polling_schedule"] == "schedule.car"
    assert coordinator.client.async_get_vehicles.await_count == 2
    assert coordinator.client.async_login.await_count == 1


def test_vacation_cancels_inflight_poll_before_fetching_status(coordinator_module):
    coordinator = build_coordinator(coordinator_module)

    async def run():
        started = asyncio.Event()

        async def delayed_vehicles():
            started.set()
            await asyncio.Event().wait()

        coordinator.client.async_get_vehicles.side_effect = delayed_vehicles
        poll = asyncio.create_task(coordinator._async_update_data())
        await started.wait()
        await coordinator.async_set_vacation(True)
        data = await poll
        assert data.polling_paused
        assert coordinator.update_interval is None

    asyncio.run(run())
    coordinator.client.async_get_vehicle_status.assert_not_awaited()
    coordinator.client.async_get_vehicle_location.assert_not_awaited()


def test_vacation_cancels_remaining_requests_in_a_running_command(coordinator_module):
    coordinator = build_coordinator(coordinator_module)

    async def run():
        coordinator.data = await coordinator._async_update_data()
        started = asyncio.Event()
        follow_up = AsyncMock()

        async def command(vehicle_id, **kwargs):
            started.set()
            await asyncio.Event().wait()
            await follow_up()

        coordinator.client.async_lock = command
        action = asyncio.create_task(coordinator.async_lock_vehicle("car"))
        await started.wait()
        await coordinator.async_set_vacation(True)
        with pytest.raises(coordinator_module.HomeAssistantError, match="Vacation"):
            await asyncio.wait_for(action, timeout=1)
        follow_up.assert_not_awaited()
        await coordinator.async_set_vacation(False)
        coordinator.client.async_lock = AsyncMock()
        await coordinator.async_lock_vehicle("car")
        coordinator.client.async_lock.assert_awaited_once_with("car", pin="1234")

    asyncio.run(run())


async def execute_control(coordinator, action, vehicle_id="car"):
    """Exercise the public lock and button entry points through one test helper."""
    if action == "lock":
        await coordinator.async_lock_vehicle(vehicle_id)
    elif action == "unlock":
        await coordinator.async_unlock_vehicle(vehicle_id)
    else:
        command = next(item for item in BluelinkCommand.all() if item.key == action)
        await coordinator.async_execute_command(command, vehicle_id)


@pytest.mark.parametrize(
    ("first", "second"),
    [("lock", "lock"), ("lock", "unlock"), ("unlock", "lock")]
    + [
        pair
        for command in BluelinkCommand.all()
        if command.key != "refresh"
        for pair in [("lock", command.key), (command.key, "lock")]
    ],
)
def test_overlapping_controls_are_rejected_without_queueing(
    coordinator_module, first, second
):
    coordinator = build_coordinator(coordinator_module)

    async def scenario():
        coordinator.data = await coordinator._async_update_data()
        previous = coordinator.data.vehicles["car"]
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def control(vehicle_id, *, pin):
            calls.append((vehicle_id, pin))
            if len(calls) == 1:
                started.set()
                await release.wait()
            elif not release.is_set():
                pytest.fail("An overlapping control reached the vehicle client")

        methods = {"async_lock", "async_unlock"} | {
            item.client_method
            for item in BluelinkCommand.all()
            if item.key != "refresh"
        }
        for method in methods:
            setattr(coordinator.client, method, control)
        action = asyncio.create_task(execute_control(coordinator, first))
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            with pytest.raises(
                coordinator_module.HomeAssistantError, match="already in progress"
            ):
                await asyncio.wait_for(execute_control(coordinator, second), timeout=1)
            assert calls == [("car", "1234")]
            assert coordinator.data.vehicles["car"] == previous
        finally:
            release.set()
            await action

        # A new user request after completion must work; rejected calls stay rejected.
        await execute_control(coordinator, second)
        assert calls == [("car", "1234"), ("car", "1234")]
        assert coordinator.data.vehicles["car"] == previous

    asyncio.run(scenario())


def test_pending_control_allows_another_vehicle_and_cached_refresh(coordinator_module):
    coordinator = build_coordinator(coordinator_module)

    async def scenario():
        coordinator.client.async_get_vehicles.return_value = [
            {"vehicleId": "car"},
            {"vehicleId": "second"},
        ]
        coordinator.data = await coordinator._async_update_data()
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def lock(vehicle_id, *, pin):
            calls.append(vehicle_id)
            if vehicle_id == "car":
                started.set()
                await release.wait()

        coordinator.client.async_lock = lock
        coordinator.client.async_refresh_vehicle_status = AsyncMock()
        action = asyncio.create_task(coordinator.async_lock_vehicle("car"))
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            await asyncio.wait_for(coordinator.async_lock_vehicle("second"), timeout=1)
            await asyncio.wait_for(execute_control(coordinator, "refresh"), timeout=1)
            assert not action.done()
            assert calls == ["car", "second"]
            coordinator.client.async_refresh_vehicle_status.assert_awaited_once_with(
                "car"
            )
        finally:
            release.set()
            await action

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["error", "cancel"])
def test_control_guard_clears_after_failure_or_cancellation(
    coordinator_module, outcome
):
    coordinator = build_coordinator(coordinator_module)

    async def scenario():
        coordinator.data = await coordinator._async_update_data()
        started = asyncio.Event()
        release = asyncio.Event()

        async def lock(vehicle_id, *, pin):
            started.set()
            await release.wait()
            raise BluelinkConnectionError("Vehicle request failed")

        coordinator.client.async_lock = lock
        action = asyncio.create_task(coordinator.async_lock_vehicle("car"))
        await asyncio.wait_for(started.wait(), timeout=1)
        if outcome == "cancel":
            action.cancel()
            with pytest.raises(asyncio.CancelledError):
                await action
        else:
            release.set()
            with pytest.raises(BluelinkConnectionError, match="Vehicle request failed"):
                await action
        coordinator.client.async_lock = AsyncMock()
        await coordinator.async_lock_vehicle("car")
        coordinator.client.async_lock.assert_awaited_once_with("car", pin="1234")

    asyncio.run(scenario())


def test_schedule_edges_reschedule_and_only_refresh_when_cadence_increases(
    coordinator_module,
):
    coordinator = build_coordinator(
        coordinator_module, options={"polling_schedule": "schedule.car"}
    )

    async def run():
        coordinator.data = await coordinator._async_update_data()
        coordinator.hass.states.is_state = lambda entity, state: True
        await coordinator._async_schedule_changed(None)
        assert coordinator.update_interval == timedelta(minutes=5)
        coordinator.hass.states.is_state = lambda entity, state: False
        await coordinator._async_schedule_changed(None)
        assert coordinator.data.poll_interval == timedelta(minutes=60)
        await coordinator.async_set_vacation(True)
        coordinator.hass.states.is_state = lambda entity, state: True
        await coordinator._async_schedule_changed(None)
        assert coordinator.update_interval is None

    asyncio.run(run())
    assert coordinator.client.async_get_vehicles.await_count == 2


def test_schedule_loading_does_not_start_a_second_startup_refresh(coordinator_module):
    coordinator = build_coordinator(
        coordinator_module, options={"polling_schedule": "schedule.car"}
    )
    coordinator.hass.states.is_state = lambda entity, state: True
    asyncio.run(coordinator._async_schedule_changed(None))
    assert coordinator.update_interval == timedelta(minutes=5)
    coordinator.client.async_get_vehicles.assert_not_awaited()


def test_corrupt_local_snapshot_does_not_prevent_vacation_startup(coordinator_module):
    coordinator = build_coordinator(coordinator_module, options={"vacation": True})
    coordinator.hass.storage[coordinator._store.key] = {"vehicles": None}
    asyncio.run(coordinator._async_setup())
    assert coordinator.data.vehicles == {}
    assert coordinator.data.polling_paused
    coordinator.client.async_login.assert_not_awaited()


@pytest.mark.parametrize("vehicle_ids", [["car"], ["car", "second"]])
def test_failed_poll_does_not_leave_untracked_network_requests(
    coordinator_module, vehicle_ids
):
    coordinator = build_coordinator(coordinator_module)

    async def run():
        all_locations_started = asyncio.Event()
        release_failure = asyncio.Event()
        started = set()
        cancelled = set()

        async def status(vehicle_id):
            if vehicle_id == "car":
                await release_failure.wait()
                raise BluelinkConnectionError("connection failed")
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.add((vehicle_id, "status"))

        async def location(vehicle_id):
            started.add(vehicle_id)
            if len(started) == len(vehicle_ids):
                all_locations_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.add((vehicle_id, "location"))

        coordinator.client.async_get_vehicles.return_value = [
            {"vehicleId": vehicle_id} for vehicle_id in vehicle_ids
        ]
        coordinator.client.async_get_vehicle_status.side_effect = status
        coordinator.client.async_get_vehicle_location.side_effect = location
        poll = asyncio.create_task(coordinator._async_update_data())
        await all_locations_started.wait()
        release_failure.set()
        with pytest.raises(coordinator_module.UpdateFailed):
            await poll
        assert ("car", "location") in cancelled
        if "second" in vehicle_ids:
            assert ("second", "location") in cancelled
            assert ("second", "status") in cancelled
        assert coordinator._poll_task is None

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"resMsg": {"coord": {"lat": 99, "lon": 145}}},
        {"resMsg": {"coord": {"lat": -37, "lon": 145}, "time": "20260920165959"}},
        {"resMsg": {"coord": {"lat": -37, "lon": 145}}},
    ],
)
def test_old_or_invalid_gps_preserves_last_known_position(coordinator_module, response):
    coordinator = build_coordinator(coordinator_module)
    coordinator.data = asyncio.run(coordinator._async_update_data())
    previous = coordinator.data.vehicles["car"]
    coordinator.client.async_get_vehicle_location.return_value = response
    updated = asyncio.run(coordinator._async_update_data()).vehicles["car"]
    assert (updated.latitude, updated.longitude) == (
        previous.latitude,
        previous.longitude,
    )
    assert updated.location_updated_at == previous.location_updated_at


def test_newer_gps_is_recorded_even_when_engine_off(coordinator_module):
    coordinator = build_coordinator(coordinator_module, running=False)
    coordinator.data = asyncio.run(coordinator._async_update_data())
    coordinator.client.async_get_vehicle_location.return_value = {
        "resMsg": {
            "coord": {"lat": -37, "lon": 145},
            "time": "20260920170100",
        }
    }
    data = asyncio.run(coordinator._async_update_data()).vehicles["car"]
    assert isinstance(data, BluelinkVehicleData)
    assert data.latitude == -37
    assert data.location_updated_at == datetime(2026, 9, 20, 7, 1, tzinfo=UTC)
