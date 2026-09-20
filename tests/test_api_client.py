"""Tests for the bundled Bluelink API adapter."""

from __future__ import annotations

import asyncio

import pytest
from test_authentication import Response, Session, logged_in_client

from custom_components.hyundai_bluelink.api import (
    BluelinkConnectionError,
    _async_checked_json,
    _ccs2_protocol,
    _extract_code,
    _normalize_bearer,
)


def test_extract_code_accepts_raw_code() -> None:
    """A raw OAuth code can be passed through unchanged."""
    assert _extract_code("abc123") == "abc123"


def test_extract_code_accepts_redirect_url() -> None:
    """An OAuth redirect URL is parsed for the code query value."""
    assert _extract_code("https://example.invalid/callback?code=abc123") == "abc123"


def test_normalize_bearer() -> None:
    """Bearer tokens are normalized without double-prefixing."""
    assert _normalize_bearer("token") == "Bearer token"
    assert _normalize_bearer("Bearer token") == "Bearer token"


def test_ccs2_protocol() -> None:
    """Protocol versions retain their numeric value instead of becoming booleans."""
    assert _ccs2_protocol({"ccuCCS2ProtocolSupport": 1}) == 1
    assert _ccs2_protocol({"ccuCCS2ProtocolSupport": "2"}) == 2
    assert _ccs2_protocol({"ccuCCS2ProtocolSupport": 0}) == 0
    assert _ccs2_protocol({"ccuCCS2ProtocolSupport": None}) == 0
    assert _ccs2_protocol({"ccuCCS2ProtocolSupport": "false"}) == 0


@pytest.mark.parametrize("status", [200, 400])
@pytest.mark.parametrize("res_code", [4004, "4004"])
def test_pending_lock_explains_delayed_status_without_replaying(status, res_code):
    """The vendor's pending-command response must not cause another lock request."""

    async def scenario():
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": 0}]
        path = "/api/v2/spa/vehicles/car-1/control/door"
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        session.add(
            "POST",
            path,
            Response(
                status,
                {
                    "retCode": "F",
                    "resCode": res_code,
                    "resMsg": "Duplicate request - Duplicate request",
                    "msgId": "pending-request",
                },
            ),
        )
        before = len(session.requests)

        with pytest.raises(BluelinkConnectionError) as error:
            await client.async_lock("car-1", pin="1234")

        message = str(error.value).lower()
        assert "previous remote command" in message
        assert "last known" in message
        assert "delayed" in message
        assert [(method, route) for method, route, _ in session.requests[before:]] == [
            ("PUT", "/api/v1/user/pin"),
            ("POST", path),
        ]
        assert not session.responses

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [200, 400])
def test_other_vehicle_errors_keep_their_original_message(status):
    """Pending-command translation must not hide a different vehicle error."""
    response = Response(
        status,
        {"retCode": "F", "resCode": "4002", "resMsg": "Vehicle rejected the command"},
    )
    with pytest.raises(BluelinkConnectionError, match="Vehicle rejected the command"):
        asyncio.run(_async_checked_json(response))
