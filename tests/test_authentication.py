"""Exercise authentication recovery against a scripted HTTP transport."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any
from urllib.parse import urlparse

import pytest

from custom_components.hyundai_bluelink import api

AUTHORIZE = "/api/v1/user/oauth2/authorize"
SIGNIN = "/api/v1/user/signin"
TOKEN = "/api/v1/user/oauth2/token"
REGISTER = "/api/v1/spa/notifications/register"
VEHICLES = "/api/v1/spa/vehicles"
VEHICLE_DATA = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": 0}]


class Response:
    """An HTTP response which can pause to reproduce concurrent requests."""

    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.payload = payload
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def __aenter__(self) -> Response:
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def json(self, **kwargs: Any) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    """Assert the actual client sends only the expected HTTP requests."""

    def __init__(self) -> None:
        self.responses: deque[tuple[str, str, Response | Exception]] = deque()
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    def add(self, method: str, path: str, response: Response | Exception) -> None:
        self.responses.append((method, path, response))

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        path = urlparse(url).path
        self.requests.append((method, path, kwargs))
        assert self.responses, f"Unexpected request: {method} {path}"
        expected_method, expected_path, response = self.responses.popleft()
        assert (method, path) == (expected_method, expected_path)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)


def add_login(session: Session, *, initial: bool = False) -> None:
    """Queue a complete successful login, retaining the registered device."""
    if initial:
        session.add("POST", REGISTER, Response(200, {"resMsg": {"deviceId": "device"}}))
    session.add("GET", AUTHORIZE, Response(200, {}))
    session.add(
        "POST", SIGNIN, Response(200, {"redirectUrl": "https://test/?code=abc"})
    )
    session.add(
        "POST",
        TOKEN,
        Response(
            200,
            {
                "access_token": "login-token",
                "refresh_token": "refresh",
                "expires_in": 86400,
            },
        ),
    )


def add_vehicles(session: Session) -> None:
    session.add("GET", VEHICLES, Response(200, {"resMsg": {"vehicles": VEHICLE_DATA}}))


async def logged_in_client(session: Session) -> api.AsyncBluelinkClient:
    add_login(session, initial=True)
    client = api.AsyncBluelinkClient(session=session)
    await client.async_login("test@example.invalid", "test-password")
    return client


@pytest.fixture
def now(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    clock = [1700000000]
    monkeypatch.setattr(api.time, "time", lambda: clock[0])
    return clock


@pytest.mark.parametrize("status", [400, 401, 403])
def test_rejected_refresh_token_logs_in_again(now: list[int], status: int) -> None:
    """An expired refresh token must not strand an otherwise valid account."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        now[0] += 86400
        session.add("POST", TOKEN, Response(status, {"error": "invalid_grant"}))
        add_login(session)
        add_vehicles(session)
        assert await client.async_get_vehicles() == VEHICLE_DATA
        assert not session.responses
        signins = [r for r in session.requests if r[1] == SIGNIN]
        assert signins[-1][2]["json"] == {
            "email": "test@example.invalid",
            "password": "test-password",
        }

    asyncio.run(scenario())


def test_refresh_preserves_token_when_response_omits_it(now: list[int]) -> None:
    """A successful refresh must keep the old refresh token when not rotated."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        for _ in range(2):
            now[0] += 86400
            session.add(
                "POST",
                TOKEN,
                Response(200, {"access_token": "renewed", "expires_in": 86400}),
            )
            add_vehicles(session)
            assert await client.async_get_vehicles() == VEHICLE_DATA
        refreshes = [
            r
            for r in session.requests
            if (r[2].get("data") or {}).get("grant_type") == "refresh_token"
        ]
        assert len(refreshes) == 2
        assert all(r[2]["data"]["refresh_token"] == "refresh" for r in refreshes)

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_access_token_logs_in_and_retries_once(status: int) -> None:
    """Server-side expiry must recover even before the local expiry time."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        session.add("GET", VEHICLES, Response(status, {"error": "invalid_token"}))
        add_login(session)
        add_vehicles(session)
        assert await client.async_get_vehicles() == VEHICLE_DATA
        assert not session.responses

    asyncio.run(scenario())


def test_rejected_credentials_end_recovery(now: list[int]) -> None:
    """A rejected saved password must reach Home Assistant without a retry loop."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        now[0] += 86400
        session.add("POST", TOKEN, Response(400, {"error": "invalid_grant"}))
        session.add("GET", AUTHORIZE, Response(200, {}))
        session.add("POST", SIGNIN, Response(401, {"error": "access_denied"}))
        with pytest.raises(api.BluelinkAuthenticationError):
            await client.async_get_vehicles()
        assert not session.responses

    asyncio.run(scenario())


@pytest.mark.parametrize("expired", [False, True])
def test_still_rejected_after_fresh_login_is_not_retried(
    now: list[int], expired: bool
) -> None:
    """A single request cannot loop through repeated fresh logins."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        if expired:
            now[0] += 86400
            session.add("POST", TOKEN, Response(401, {}))
        else:
            session.add("GET", VEHICLES, Response(401, {}))
        add_login(session)
        session.add("GET", VEHICLES, Response(401, {}))
        with pytest.raises(api.BluelinkAuthenticationError):
            await client.async_get_vehicles()
        assert not session.responses

    asyncio.run(scenario())


def test_concurrent_expiry_refreshes_only_once(now: list[int]) -> None:
    """Simultaneous polling must not reuse a rotating refresh token twice."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        now[0] += 86400
        refresh = Response(200, {"access_token": "renewed", "refresh_token": "rotated"})
        refresh.release = asyncio.Event()
        session.add("POST", TOKEN, refresh)
        add_vehicles(session)
        add_vehicles(session)
        first = asyncio.create_task(client.async_get_vehicles())
        await refresh.entered.wait()
        second = asyncio.create_task(client.async_get_vehicles())
        await asyncio.sleep(0)
        refresh.release.set()
        assert await asyncio.gather(first, second) == [VEHICLE_DATA, VEHICLE_DATA]
        assert not session.responses

    asyncio.run(scenario())


def test_concurrent_rejections_share_one_fresh_login() -> None:
    """A late rejection for the old session must reuse the replacement session."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        errors = [Response(401, {}), Response(401, {})]
        for error in errors:
            error.release = asyncio.Event()
            session.add("GET", VEHICLES, error)
        add_login(session)
        add_vehicles(session)
        add_vehicles(session)
        tasks = [asyncio.create_task(client.async_get_vehicles()) for _ in errors]
        await asyncio.gather(*(error.entered.wait() for error in errors))
        errors[0].release.set()
        assert await tasks[0] == VEHICLE_DATA
        errors[1].release.set()
        assert await tasks[1] == VEHICLE_DATA
        assert not session.responses

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [429, 503])
def test_temporary_signin_failure_remains_retryable(status: int) -> None:
    """An unavailable login service must not be reported as a bad password."""

    async def scenario() -> None:
        session = Session()
        session.add("POST", REGISTER, Response(200, {"resMsg": {"deviceId": "device"}}))
        session.add("GET", AUTHORIZE, Response(200, {}))
        session.add(
            "POST", SIGNIN, Response(status, {"error": "temporarily_unavailable"})
        )
        client = api.AsyncBluelinkClient(session=session)
        with pytest.raises(api.BluelinkConnectionError):
            await client.async_login("test@example.invalid", "test-password")

    asyncio.run(scenario())


def test_temporary_refresh_failure_does_not_trigger_login(now: list[int]) -> None:
    """A refresh outage should retry on the next poll using the same session."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        now[0] += 86400
        session.add("POST", TOKEN, Response(503, {"error": "server_error"}))
        with pytest.raises(api.BluelinkConnectionError):
            await client.async_get_vehicles()
        session.add("POST", TOKEN, Response(200, {"access_token": "renewed"}))
        add_vehicles(session)
        assert await client.async_get_vehicles() == VEHICLE_DATA

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [TimeoutError(), api.ClientError("offline")])
def test_authorization_connection_failure_is_retryable(failure: Exception) -> None:
    """Failures before sign-in must use the same retryable error contract."""

    async def scenario() -> None:
        session = Session()
        session.add("POST", REGISTER, Response(200, {"resMsg": {"deviceId": "device"}}))
        session.add("GET", AUTHORIZE, failure)
        with pytest.raises(api.BluelinkConnectionError):
            await api.AsyncBluelinkClient(session=session).async_login(
                "user", "password"
            )

    asyncio.run(scenario())


def test_password_change_prompt_explains_required_user_action() -> None:
    """The live Hyundai step-5 response must explain the password prompt."""

    async def scenario() -> None:
        session = Session()
        session.add("POST", REGISTER, Response(200, {"resMsg": {"deviceId": "device"}}))
        session.add("GET", AUTHORIZE, Response(200, {}))
        session.add("POST", SIGNIN, Response(200, {"step": 5, "upgrade": False}))
        with pytest.raises(
            api.BluelinkAuthenticationError, match="password.*Bluelink app"
        ):
            await api.AsyncBluelinkClient(session=session).async_login(
                "user", "password"
            )
        assert not session.responses

    asyncio.run(scenario())


def test_vehicle_control_is_not_replayed_after_authentication_failure() -> None:
    """An uncertain remote-control outcome must never send the command twice."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        add_vehicles(session)
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        session.add(
            "POST", "/api/v2/spa/vehicles/car-1/control/door", Response(401, {})
        )
        with pytest.raises(api.BluelinkAuthenticationError):
            await client.async_lock("car-1", pin="1234")
        assert not session.responses

    asyncio.run(scenario())


def test_pin_rejection_is_not_retried_with_account_credentials() -> None:
    """A rejected remote PIN must not lead to repeated PIN attempts."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        add_vehicles(session)
        session.add("PUT", "/api/v1/user/pin", Response(403, {}))
        with pytest.raises(api.BluelinkAuthenticationError):
            await client.async_lock("car-1", pin="1234")
        assert not session.responses

    asyncio.run(scenario())


@pytest.mark.parametrize("error", [{"message": "unavailable"}, ["unavailable"]])
def test_structured_api_errors_remain_retryable(error: Any) -> None:
    """Unexpected error shapes must not crash OAuth error classification."""
    with pytest.raises(api.BluelinkConnectionError):
        asyncio.run(api._async_checked_json(Response(400, {"error": error})))


@pytest.mark.parametrize("error", ["server_error", "temporarily_unavailable"])
def test_oauth_outage_in_success_response_is_retryable(error: str) -> None:
    """OAuth error bodies must not treat provider outages as bad credentials."""
    with pytest.raises(api.BluelinkConnectionError):
        asyncio.run(api._async_checked_json(Response(200, {"error": error})))


def test_missing_refresh_token_falls_back_to_login(now: list[int]) -> None:
    """Accounts without a usable refresh token can still use saved credentials."""

    async def scenario() -> None:
        session = Session()
        add_login(session, initial=True)
        session.responses[-1] = (
            "POST",
            TOKEN,
            Response(200, {"access_token": "initial", "expires_in": 86400}),
        )
        client = api.AsyncBluelinkClient(session=session)
        await client.async_login("user", "password")
        now[0] += 86400
        add_login(session)
        add_vehicles(session)
        assert await client.async_get_vehicles() == VEHICLE_DATA
        assert not session.responses

    asyncio.run(scenario())


def test_non_json_unauthorized_response_can_recover() -> None:
    """A proxy's non-JSON unauthorized response must still allow session recovery."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        session.add("GET", VEHICLES, Response(401, ValueError("not JSON")))
        add_login(session)
        add_vehicles(session)
        assert await client.async_get_vehicles() == VEHICLE_DATA

    asyncio.run(scenario())


def test_temporary_relogin_failure_can_recover_on_next_poll(now: list[int]) -> None:
    """A failed recovery attempt must not stop future polling after an outage."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        now[0] += 86400
        session.add("POST", TOKEN, Response(400, {"error": "invalid_grant"}))
        session.add("GET", AUTHORIZE, Response(200, {}))
        session.add("POST", SIGNIN, Response(503, {}))
        with pytest.raises(api.BluelinkConnectionError):
            await client.async_get_vehicles()
        session.add("POST", TOKEN, Response(400, {"error": "invalid_grant"}))
        add_login(session)
        add_vehicles(session)
        assert await client.async_get_vehicles() == VEHICLE_DATA

    asyncio.run(scenario())


def test_account_action_is_distinct_from_invalid_credentials() -> None:
    """An interactive prompt must select the actionable config-flow error."""

    async def scenario() -> None:
        session = Session()
        session.add("POST", REGISTER, Response(200, {"resMsg": {"deviceId": "device"}}))
        session.add("GET", AUTHORIZE, Response(200, {}))
        session.add("POST", SIGNIN, Response(200, {"step": 5, "upgrade": False}))
        with pytest.raises(api.BluelinkAccountActionRequiredError):
            await api.AsyncBluelinkClient(session=session).async_login(
                "user", "password"
            )

    asyncio.run(scenario())


def test_authentication_diagnostics_redact_credentials() -> None:
    """Provider errors must not expose passwords, PINs, or returned tokens."""
    result = api._safe_json(
        {
            "nested": {"password": "test-password", "pin": "1234"},
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
        }
    )
    for secret in ("test-password", "1234", "access-secret", "refresh-secret"):
        assert secret not in result


def test_concurrent_rejections_share_failed_login_until_credentials_updated() -> None:
    """A rejected password is submitted once, and explicit reauth clears the failure."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        errors = [Response(401, {}), Response(401, {})]
        for error in errors:
            error.release = asyncio.Event()
            session.add("GET", VEHICLES, error)
        session.add("GET", AUTHORIZE, Response(200, {}))
        session.add("POST", SIGNIN, Response(401, {"error": "access_denied"}))
        tasks = [asyncio.create_task(client.async_get_vehicles()) for _ in errors]
        await asyncio.gather(*(error.entered.wait() for error in errors))
        errors[0].release.set()
        with pytest.raises(api.BluelinkAuthenticationError):
            await tasks[0]
        errors[1].release.set()
        with pytest.raises(api.BluelinkAuthenticationError):
            await tasks[1]
        with pytest.raises(api.BluelinkAuthenticationError):
            await client.async_get_vehicles()
        assert not session.responses
        add_login(session)
        await client.async_login("test@example.invalid", "updated-password")
        add_vehicles(session)
        assert await client.async_get_vehicles() == VEHICLE_DATA

    asyncio.run(scenario())
