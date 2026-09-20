"""Verify engine requests against the Australian app's two wire formats."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_authentication import VEHICLES, Response, Session, logged_in_client

from custom_components.hyundai_bluelink import api


@pytest.mark.parametrize(
    ("ccs2", "operation", "body"),
    [
        (1, "start", {"command": "start", "hvacCtrl": 0, "ignitionDuration": 5}),
        (1, "stop", {"command": "stop"}),
        (
            0,
            "start",
            {"action": "start", "options": {"airCtrl": 0, "igniOnDuration": 5}},
        ),
        (0, "stop", {"action": "stop", "deviceId": "device"}),
    ],
)
def test_engine_request_matches_vehicle_protocol(
    ccs2: int, operation: str, body: dict[str, Any]
) -> None:
    """CCS2 uses command/flat fields; legacy uses action/nested options."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        session.add(
            "GET",
            VEHICLES,
            Response(
                200,
                {
                    "resMsg": {
                        "vehicles": [
                            {"vehicleId": "car-1", "ccuCCS2ProtocolSupport": ccs2}
                        ]
                    }
                },
            ),
        )
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        suffix = "/ccs2" if ccs2 else ""
        path = f"/api/v2/spa/vehicles/car-1{suffix}/control/engine"
        session.add("POST", path, Response(200, {"retCode": "S", "msgId": "sent"}))

        result = await getattr(client, f"async_{operation}_engine")("car-1", pin="1234")

        assert result["msgId"] == "sent"
        assert not session.responses
        method, actual_path, request = session.requests[-1]
        assert (method, actual_path) == ("POST", path)
        assert request["json"] == body
        assert request["headers"]["Authorization"] == "Bearer control"
        assert request["headers"]["Ccuccs2protocolsupport"] == str(ccs2)
        assert session.requests[-2][2]["json"] == {"deviceId": "device", "pin": "1234"}

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["start", "stop"])
@pytest.mark.parametrize("status", [400, 401, 503])
def test_engine_failure_does_not_resend_command(operation: str, status: int) -> None:
    """Neither a schema rejection nor an uncertain result should run twice."""

    async def scenario() -> None:
        session = Session()
        client = await logged_in_client(session)
        client._vehicles = [{"vehicleId": "car-1", "ccuCCS2ProtocolSupport": 1}]
        session.add(
            "PUT", "/api/v1/user/pin", Response(200, {"controlToken": "control"})
        )
        path = "/api/v2/spa/vehicles/car-1/ccs2/control/engine"
        session.add(
            "POST",
            path,
            Response(status, {"retCode": "F", "resCode": "4002"}),
        )
        with pytest.raises(
            (api.BluelinkConnectionError, api.BluelinkAuthenticationError)
        ):
            await getattr(client, f"async_{operation}_engine")("car-1", pin="1234")
        assert not session.responses
        assert sum(request[1] == path for request in session.requests) == 1

    asyncio.run(scenario())
