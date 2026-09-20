"""Check remote requests against the Australian mobile app's API contracts."""

from __future__ import annotations

import asyncio

import pytest
from test_authentication import Response, Session, logged_in_client

from custom_components.hyundai_bluelink import api

# Literal routes and payloads transcribed from the app, independently of api.py.
# Engine requests are covered separately in test_engine_commands.py.
COMMANDS = {
    "async_lock": (
        ("door", {"deviceId": "device", "action": "close"}),
        ("door", {"command": "close"}),
    ),
    "async_unlock": (
        ("door", {"deviceId": "device", "action": "open"}),
        ("door", {"command": "open"}),
    ),
    "async_horn": (
        ("horn", {"deviceId": "device"}),
        ("hornlight", {"command": "on"}),
    ),
    "async_light": (
        ("light", {"deviceId": "device"}),
        ("light", {"command": "on"}),
    ),
    "async_horn_light": (
        ("horn", {"deviceId": "device"}),
        ("hornlight", {"command": "on"}),
    ),
    "async_open_windows": (
        ("window", {"deviceId": "device", "action": "open"}),
        ("window", {"command": "open"}),
    ),
    "async_close_windows": (
        ("window", {"deviceId": "device", "action": "close"}),
        ("window", {"command": "close"}),
    ),
    "async_ventilate_windows": (
        (
            "windowcurtain",
            {
                "deviceId": "device",
                "frontLeft": 2,
                "frontRight": 2,
                "backLeft": 2,
                "backRight": 2,
            },
        ),
        (
            "windowcurtain",
            {
                "drvSeatWindow": 2,
                "psgSeatWindow": 2,
                "rlSeatWindow": 2,
                "rrSeatWindow": 2,
            },
        ),
    ),
}

PROFILE_PATH = "/api/v1/spa/vehicles/car-1/profile"
BASIC_WINDOW_PROFILE = {"option": {"windowSafetyOption": 1}}


def add_window_profile(session: Session, profile: dict) -> None:
    """Supply the profile endpoint's actual vinInfo envelope."""
    session.add("GET", PROFILE_PATH, Response(200, {"resMsg": {"vinInfo": [profile]}}))


@pytest.mark.parametrize("ccs2", [0, 1])
@pytest.mark.parametrize("operation", COMMANDS)
def test_control_request_matches_app_contract(operation: str, ccs2: int) -> None:
    """Wrong verbs, missing fields and protocol-specific routes reject controls."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": ccs2}]
        if operation == "async_ventilate_windows":
            add_window_profile(session, {"option": {"windowSafetyOption2": 3}})
        elif "windows" in operation:
            add_window_profile(session, BASIC_WINDOW_PROFILE)
        route, body = COMMANDS[operation][ccs2]
        suffix = "/ccs2" if ccs2 else ""
        path = f"/api/v2/spa/vehicles/car-1{suffix}/control/{route}"
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        session.add("POST", path, Response(200, {"retCode": "S", "msgId": "sent"}))

        result = await getattr(client, operation)("car-1", pin="1234")

        assert result["msgId"] == "sent"
        assert not session.responses
        assert session.requests[-2][2]["json"] == {"deviceId": "device", "pin": "1234"}
        pin_request = session.requests[-2][2]
        assert pin_request["headers"]["Authorization"] == "Bearer login-token"
        request = session.requests[-1][2]
        assert request["json"] == body
        assert request["headers"]["Authorization"] == "Bearer control"
        assert request["headers"]["Ccuccs2protocolsupport"] == str(ccs2)
        assert request["headers"]["ccsp-device-id"] == "device"

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", COMMANDS)
@pytest.mark.parametrize("ccs2", [0, 1])
@pytest.mark.parametrize("failure", [400, 401, 503, "timeout"])
def test_control_failure_is_not_replayed(
    operation: str, ccs2: int, failure: int | str
) -> None:
    """Uncertain or rejected controls must never trigger another vehicle action."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": ccs2}]
        if operation == "async_ventilate_windows":
            add_window_profile(session, {"option": {"windowSafetyOption2": 3}})
        elif "windows" in operation:
            add_window_profile(session, BASIC_WINDOW_PROFILE)
        route, _ = COMMANDS[operation][ccs2]
        suffix = "/ccs2" if ccs2 else ""
        path = f"/api/v2/spa/vehicles/car-1{suffix}/control/{route}"
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        response = (
            TimeoutError()
            if failure == "timeout"
            else Response(failure, {"retCode": "F", "resCode": "4002"})
        )
        session.add("POST", path, response)
        request_count = len(session.requests)

        with pytest.raises(
            (api.BluelinkConnectionError, api.BluelinkAuthenticationError)
        ):
            await getattr(client, operation)("car-1", pin="1234")

        assert not session.responses
        assert len(session.requests) == request_count + 2 + ("windows" in operation)

    asyncio.run(scenario())


@pytest.mark.parametrize("ccs2", [0, 1])
@pytest.mark.parametrize("family", ["old_extended", "new"])
@pytest.mark.parametrize(
    ("operation", "position"),
    [
        ("async_close_windows", 0),
        ("async_open_windows", 1),
        ("async_ventilate_windows", 2),
    ],
)
def test_extended_window_requests(
    ccs2: int, family: str, operation: str, position: int
) -> None:
    """Extended windows use numeric positions, a distinct endpoint and seat names."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": ccs2}]
        profile = (
            {
                "option": {"windowSafetyOption": 1, "drvSeatLoc": "R"},
                "serviceOption": {"windowControlOption": 2},
            }
            if family == "old_extended"
            else {"option": {"windowSafetyOption2": 3, "drvSeatLoc": "R"}}
        )
        add_window_profile(session, profile)
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        suffix = "/ccs2" if ccs2 else ""
        path = f"/api/v2/spa/vehicles/car-1{suffix}/control/windowcurtain"
        session.add("POST", path, Response(200, {"retCode": "S"}))

        await getattr(client, operation)("car-1", pin="1234")

        assert not session.responses
        expected = (
            {
                "drvSeatWindow": position,
                "psgSeatWindow": position,
                "rlSeatWindow": position,
                "rrSeatWindow": position,
                "drvSeatLoc": "R",
            }
            if ccs2
            else {
                "deviceId": "device",
                "frontLeft": position,
                "frontRight": position,
                "backLeft": position,
                "backRight": position,
            }
        )
        assert session.requests[-1][2]["json"] == expected
        assert session.requests[-1][2]["headers"]["Authorization"] == "Bearer control"
        assert (
            session.requests[-3][2]["headers"]["Authorization"] == "Bearer login-token"
        )
        assert session.requests[-3][2]["json"] is None

    asyncio.run(scenario())


@pytest.mark.parametrize("seat_location", [None, ""])
def test_window_request_omits_unknown_seat_location(seat_location: str | None) -> None:
    """Do not invent a driver position or send null curtain/window settings."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": 1}]
        add_window_profile(
            session, {"option": {"windowSafetyOption2": 3, "drvSeatLoc": seat_location}}
        )
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        session.add(
            "POST",
            "/api/v2/spa/vehicles/car-1/ccs2/control/windowcurtain",
            Response(200, {"retCode": "S"}),
        )

        await client.async_ventilate_windows("car-1", pin="1234")

        assert not session.responses
        assert session.requests[-1][2]["json"] == {
            "drvSeatWindow": 2,
            "psgSeatWindow": 2,
            "rlSeatWindow": 2,
            "rrSeatWindow": 2,
        }

    asyncio.run(scenario())


@pytest.mark.parametrize("ccs2", [0, 1])
@pytest.mark.parametrize("control_option", [None, -1, 0, 1])
def test_unsupported_ventilation_fails_before_pin(
    ccs2: int, control_option: int
) -> None:
    """Windows without ventilation support must reject that command before the PIN."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": ccs2}]
        add_window_profile(
            session,
            {
                "option": {"windowSafetyOption": 1},
                "serviceOption": {"windowControlOption": control_option},
            },
        )
        request_count = len(session.requests)

        with pytest.raises(api.BluelinkConnectionError, match="ventilation"):
            await client.async_ventilate_windows("car-1", pin="1234")

        assert not session.responses
        assert len(session.requests) == request_count + 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation",
    ["async_open_windows", "async_close_windows", "async_ventilate_windows"],
)
def test_unsupported_windows_fail_before_pin(operation: str) -> None:
    """Absent capability flags must not enable a vehicle's window controls."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": 1}]
        add_window_profile(session, {"option": {"windowSafetyOption2": 0}})

        with pytest.raises(api.BluelinkConnectionError, match="window control"):
            await getattr(client, operation)("car-1", pin="1234")

        assert not session.responses
        assert session.requests[-1][1] == PROFILE_PATH

    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [{}, {"resMsg": {}}, {"resMsg": {"vinInfo": []}}])
def test_incomplete_window_profile_fails_before_pin(payload: dict) -> None:
    """A malformed profile must not silently select a control format."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": 1}]
        session.add("GET", PROFILE_PATH, Response(200, payload))

        with pytest.raises(api.BluelinkConnectionError, match="profile"):
            await client.async_open_windows("car-1", pin="1234")

        assert not session.responses
        assert session.requests[-1][1] == PROFILE_PATH

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("ccs2", "live", "path"),
    [
        (0, False, "/api/v1/spa/vehicles/car-1/status/latest"),
        (1, False, "/api/v1/spa/vehicles/car-1/ccs2/carstatus/latest"),
        (0, True, "/api/v2/spa/vehicles/car-1/status"),
        (1, True, "/api/v2/spa/vehicles/car-1/ccs2/carstatus"),
    ],
)
def test_refresh_uses_correct_route_and_token(ccs2: int, live: bool, path: str) -> None:
    """Cached refresh needs no PIN; live refresh uses a control token and no body."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": ccs2}]
        request_count = len(session.requests)
        if live:
            session.add(
                "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
            )
        session.add("GET", path, Response(200, {"retCode": "S"}))

        if live:
            await client.async_live_refresh_vehicle_status("car-1", pin="1234")
        else:
            await client.async_refresh_vehicle_status("car-1")

        assert not session.responses
        assert len(session.requests) == request_count + (2 if live else 1)
        request = session.requests[-1][2]
        assert request["json"] is None
        expected_token = "control" if live else "login-token"
        assert request["headers"]["Authorization"] == f"Bearer {expected_token}"
        assert request["headers"]["Ccuccs2protocolsupport"] == str(ccs2)

    asyncio.run(scenario())


@pytest.mark.parametrize("ccs2", [0, 1])
def test_live_refresh_401_is_not_replayed(ccs2: int) -> None:
    """A GET used for a live vehicle command must not use cached-GET auth retry."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": ccs2}]
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        path = (
            "/api/v2/spa/vehicles/car-1/ccs2/carstatus"
            if ccs2
            else "/api/v2/spa/vehicles/car-1/status"
        )
        session.add("GET", path, Response(401, {"error": "invalid_token"}))
        request_count = len(session.requests)

        with pytest.raises(api.BluelinkAuthenticationError):
            await client.async_live_refresh_vehicle_status("car-1", pin="1234")

        assert not session.responses
        assert len(session.requests) == request_count + 2

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("operation", "method", "path", "uses_pin"),
    [
        ("async_lock", "POST", "/api/v2/spa/vehicles/car-1/ccs2/control/door", True),
        (
            "async_refresh_vehicle_status",
            "GET",
            "/api/v1/spa/vehicles/car-1/ccs2/carstatus/latest",
            False,
        ),
        (
            "async_live_refresh_vehicle_status",
            "GET",
            "/api/v2/spa/vehicles/car-1/ccs2/carstatus",
            True,
        ),
        (
            "async_get_vehicle_location",
            "GET",
            "/api/v1/spa/vehicles/car-1/location/park",
            False,
        ),
    ],
)
def test_protocol_header_preserves_reported_version(
    operation: str, method: str, path: str, uses_pin: bool
) -> None:
    """Protocol version 2 must not be flattened to boolean 1 in request headers."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": 2}]
        if uses_pin:
            session.add(
                "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
            )
        session.add(method, path, Response(200, {"retCode": "S"}))

        kwargs = {"pin": "1234"} if uses_pin else {}
        await getattr(client, operation)("car-1", **kwargs)

        assert not session.responses
        assert session.requests[-1][2]["headers"]["Ccuccs2protocolsupport"] == "2"
        if uses_pin:
            assert session.requests[-2][2]["headers"]["Ccuccs2protocolsupport"] == "2"

    asyncio.run(scenario())
