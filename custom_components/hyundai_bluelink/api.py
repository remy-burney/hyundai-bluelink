"""Async Hyundai Bluelink Australia API client.

This is a local HACS-compatible adapter for the upstream client contract used by
the integration. The code should move to a standalone `aiobluelink` package
before a Home Assistant Core submission.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

try:
    from aiohttp import ClientError, ClientSession
except ImportError:  # pragma: no cover - Home Assistant provides aiohttp.

    class ClientError(Exception):
        """Fallback aiohttp client error for helper-only test environments."""

    ClientSession = Any

BASE_URL = "https://au-apigw.ccs.hyundai.com.au:8080"
BASE_HOST = "au-apigw.ccs.hyundai.com.au:8080"
CLIENT_ID = "855c72df-dfd7-4230-ab03-67cbf902bb1c"
APP_ID = "f9ccfdac-a48d-4c57-bd32-9116963c24ed"
BASIC_AUTHORIZATION = (
    "Basic "
    "ODU1YzcyZGYtZGZkNy00MjMwLWFiMDMtNjdjYmY5MDJiYjFjOmU2ZmJ3SE0zMllOYmhRbDBw"
    "dmlhUHAzcmY0dDNTNms5MWVjZUEzTUpMZGJkVGhDTw=="
)
STAMP_CFB = base64.b64decode(
    "nGDHng3k4Cg9gWV+C+A6Yk/ecDopUNTkGmDpr2qVKAQXx9bvY2/YLoHPfObliK32mZQ="
)
REDIRECT_URI = f"{BASE_URL}/api/v1/user/oauth2/redirect"
REQUEST_TIMEOUT = 30


class BluelinkAuthenticationError(Exception):
    """Authentication error returned by Hyundai Bluelink."""


class BluelinkConnectionError(Exception):
    """Connection or API error returned by Hyundai Bluelink."""


class AsyncBluelinkClient:
    """Async client for the Hyundai Bluelink Australia API."""

    account_id: str | None = None

    def __init__(
        self,
        *,
        session: ClientSession,
        region: str = "AU",
    ) -> None:
        """Initialize the client."""
        self.session = session
        self.region = region
        self._tokens: dict[str, Any] = {}
        self._device_id: str | None = None
        self._vehicles: list[dict[str, Any]] = []

    async def async_login(
        self,
        username: str,
        password: str,
        *,
        pin: str | None = None,
    ) -> None:
        """Authenticate with Hyundai Bluelink."""
        self.account_id = username
        self._device_id = await self._async_register_device()

        try:
            async with self.session.get(
                self._auth_url(),
                timeout=REQUEST_TIMEOUT,
            ):
                pass
            response = await self._async_request(
                "POST",
                "/api/v1/user/signin",
                json_data={"email": username, "password": password},
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "okhttp/3.12.0",
                },
                authenticated=False,
            )
        except BluelinkConnectionError as exc:
            raise BluelinkAuthenticationError(str(exc)) from exc

        redirect_url = response.get("redirectUrl")
        if not redirect_url:
            raise BluelinkAuthenticationError(
                "Hyundai did not return an OAuth redirect URL."
            )

        code = _extract_code(redirect_url)
        self._tokens = await self._async_exchange_code(code, self._device_id)

    async def async_close(self) -> None:
        """Close client resources."""

    async def async_get_vehicles(self) -> list[dict[str, Any]]:
        """Return vehicles for the account."""
        await self._async_ensure_session()
        data = await self._async_request("GET", "/api/v1/spa/vehicles")
        vehicles = data.get("resMsg", {}).get("vehicles")
        if not isinstance(vehicles, list):
            raise BluelinkConnectionError(
                "Vehicle response did not include resMsg.vehicles."
            )
        self._vehicles = vehicles
        return vehicles

    async def async_get_vehicle_status(self, vehicle_id: str) -> dict[str, Any]:
        """Return cached vehicle status."""
        vehicle = await self._async_get_vehicle_record(vehicle_id)
        ccs2 = _ccs2_supported(vehicle)
        path = (
            f"/api/v1/spa/vehicles/{vehicle_id}/ccs2/carstatus/latest"
            if ccs2
            else f"/api/v1/spa/vehicles/{vehicle_id}/status/latest"
        )
        return await self._async_request("GET", path, ccs2=ccs2)

    async def async_get_vehicle_location(self, vehicle_id: str) -> dict[str, Any]:
        """Return cached vehicle location."""
        vehicle = await self._async_get_vehicle_record(vehicle_id)
        return await self._async_request(
            "GET",
            f"/api/v1/spa/vehicles/{vehicle_id}/location/park",
            ccs2=_ccs2_supported(vehicle),
        )

    async def async_refresh_vehicle_status(self, vehicle_id: str) -> dict[str, Any]:
        """Refresh cached vehicle status without requiring a remote-control PIN."""
        return await self.async_get_vehicle_status(vehicle_id)

    async def async_live_refresh_vehicle_status(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Request live vehicle status through the PIN-protected v2 endpoint."""
        vehicle = await self._async_get_vehicle_record(vehicle_id)
        ccs2 = _ccs2_supported(vehicle)
        path = (
            f"/api/v2/spa/vehicles/{vehicle_id}/ccs2/carstatus"
            if ccs2
            else f"/api/v2/spa/vehicles/{vehicle_id}/status"
        )
        return await self._async_control_request("GET", path, pin=pin, ccs2=ccs2)

    async def async_lock(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Lock the vehicle."""
        return await self._async_vehicle_command(
            vehicle_id,
            "door",
            {"action": "lock"},
            pin=pin,
        )

    async def async_unlock(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Unlock the vehicle."""
        return await self._async_vehicle_command(
            vehicle_id,
            "door",
            {"action": "unlock"},
            pin=pin,
        )

    async def async_start_engine(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Start the engine."""
        return await self._async_vehicle_command(
            vehicle_id,
            "engine",
            {"action": "start"},
            pin=pin,
        )

    async def async_stop_engine(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Stop the engine."""
        return await self._async_vehicle_command(
            vehicle_id,
            "engine",
            {"action": "stop"},
            pin=pin,
        )

    async def async_horn(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Sound the horn."""
        return await self._async_vehicle_command(vehicle_id, "horn", {}, pin=pin)

    async def async_light(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Flash the lights."""
        return await self._async_vehicle_command(vehicle_id, "light", {}, pin=pin)

    async def async_horn_light(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Sound the horn and flash the lights."""
        return await self._async_vehicle_command(vehicle_id, "hornlight", {}, pin=pin)

    async def async_open_windows(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Open the windows."""
        return await self._async_vehicle_command(
            vehicle_id,
            "window",
            {"action": "open"},
            pin=pin,
        )

    async def async_close_windows(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Close the windows."""
        return await self._async_vehicle_command(
            vehicle_id,
            "window",
            {"action": "close"},
            pin=pin,
        )

    async def async_ventilate_windows(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Start window ventilation."""
        return await self._async_vehicle_command(
            vehicle_id,
            "window",
            {"action": "ventilation"},
            pin=pin,
        )

    async def _async_vehicle_command(
        self,
        vehicle_id: str,
        command: str,
        body: dict[str, Any],
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Execute a PIN-protected vehicle command."""
        vehicle = await self._async_get_vehicle_record(vehicle_id)
        ccs2 = _ccs2_supported(vehicle)
        path = (
            f"/api/v2/spa/vehicles/{vehicle_id}/ccs2/control/{command}"
            if ccs2
            else f"/api/v2/spa/vehicles/{vehicle_id}/control/{command}"
        )
        return await self._async_control_request(
            "POST",
            path,
            json_data=body,
            pin=pin,
            ccs2=ccs2,
        )

    async def _async_control_request(
        self,
        method: str,
        path: str,
        *,
        json_data: dict[str, Any] | None = None,
        pin: str | None = None,
        ccs2: bool = False,
    ) -> dict[str, Any]:
        """Call a control endpoint with a short-lived control token."""
        control_token = await self._async_get_control_token(pin)
        headers = self._api_headers(control_token, ccs2=ccs2)
        return await self._async_request(
            method,
            path,
            json_data=json_data,
            headers=headers,
            authenticated=False,
        )

    async def _async_get_control_token(self, pin: str | None) -> str:
        """Return a short-lived remote control token."""
        if pin is None:
            raise BluelinkAuthenticationError("Remote control PIN is required.")
        data = await self._async_request(
            "PUT",
            "/api/v1/user/pin",
            json_data={"deviceId": self._device_id, "pin": pin},
        )
        token = data.get("controlToken") or data.get("resMsg", {}).get("controlToken")
        if not token:
            raise BluelinkAuthenticationError("Hyundai did not return a control token.")
        return str(token)

    async def _async_get_vehicle_record(self, vehicle_id: str) -> dict[str, Any]:
        """Return a cached vehicle record, refreshing the list if needed."""
        if not self._vehicles:
            await self.async_get_vehicles()
        for vehicle in self._vehicles:
            if str(vehicle.get("vehicleId")) == vehicle_id:
                return vehicle
        raise BluelinkConnectionError(f"Unknown Bluelink vehicle ID: {vehicle_id}")

    async def _async_ensure_session(self) -> None:
        """Refresh the OAuth session if needed."""
        if not self._tokens:
            raise BluelinkAuthenticationError(
                "Not authenticated with Hyundai Bluelink."
            )
        if int(self._tokens.get("expires_at") or 0) > int(time.time()):
            return
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise BluelinkAuthenticationError("Hyundai refresh token is missing.")
        self._tokens = await self._async_refresh_token(str(refresh_token))

    async def _async_register_device(self) -> str:
        """Register a pseudo push device and return the Hyundai device ID."""
        data = await self._async_request(
            "POST",
            "/api/v1/spa/notifications/register",
            json_data={
                "pushRegId": secrets.token_hex(32),
                "pushType": "GCM",
                "uuid": str(uuid.uuid4()),
            },
            headers=self._api_headers(None),
            authenticated=False,
        )
        device_id = data.get("resMsg", {}).get("deviceId")
        if not device_id:
            raise BluelinkConnectionError(
                "Device registration response did not include deviceId."
            )
        return str(device_id)

    async def _async_exchange_code(
        self,
        code: str,
        device_id: str,
    ) -> dict[str, Any]:
        """Exchange an OAuth authorization code for tokens."""
        data = await self._async_request(
            "POST",
            "/api/v1/user/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
            headers=_token_headers(),
            authenticated=False,
        )
        return _session_from_token(data, device_id)

    async def _async_refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh OAuth tokens."""
        data = await self._async_request(
            "POST",
            "/api/v1/user/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token.removeprefix("Bearer "),
                "redirect_uri": REDIRECT_URI,
            },
            headers=_token_headers(),
            authenticated=False,
        )
        refreshed = _session_from_token(data, self._device_id or "")
        if not refreshed.get("refresh_token"):
            refreshed["refresh_token"] = refresh_token
        return refreshed

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
        ccs2: bool = False,
    ) -> dict[str, Any]:
        """Make a Hyundai API request and validate the JSON response."""
        if authenticated:
            await self._async_ensure_session()
        request_headers = headers or self._api_headers(
            self._tokens.get("access_token") if authenticated else None,
            ccs2=ccs2,
        )
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        try:
            async with self.session.request(
                method,
                url,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                return await _async_checked_json(response)
        except BluelinkAuthenticationError:
            raise
        except BluelinkConnectionError:
            raise
        except ClientError as exc:
            raise BluelinkConnectionError(str(exc)) from exc

    def _api_headers(
        self,
        token: str | None,
        *,
        ccs2: bool = False,
    ) -> dict[str, str]:
        """Return common Hyundai API headers."""
        headers = {
            "ccsp-service-id": CLIENT_ID,
            "ccsp-application-id": APP_ID,
            "Stamp": _make_stamp(),
            "Host": BASE_HOST,
            "Connection": "close",
            "Accept-Encoding": "gzip",
            "Ccuccs2protocolsupport": "1" if ccs2 else "0",
            "User-Agent": "okhttp/3.12.0",
            "Content-Type": "application/json;charset=UTF-8",
        }
        if token:
            headers["Authorization"] = _normalize_bearer(token)
        if self._device_id:
            headers["ccsp-device-id"] = self._device_id
        return headers

    @staticmethod
    def _auth_url() -> str:
        """Return the Hyundai OAuth authorization URL."""
        query = urlencode(
            {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "lang": "en",
            }
        )
        return f"{BASE_URL}/api/v1/user/oauth2/authorize?{query}"


async def _async_checked_json(response: Any) -> dict[str, Any]:
    """Return validated JSON from an aiohttp response."""
    try:
        data = await response.json(content_type=None)
    except (json.JSONDecodeError, ValueError) as exc:
        raise BluelinkConnectionError(
            f"Hyundai returned non-JSON HTTP {response.status}."
        ) from exc

    if response.status in {401, 403}:
        raise BluelinkAuthenticationError(
            f"Hyundai returned HTTP {response.status}: {_safe_json(data)}"
        )
    if response.status >= 400:
        raise BluelinkConnectionError(
            f"Hyundai returned HTTP {response.status}: {_safe_json(data)}"
        )

    if isinstance(data, dict):
        oauth_error = data.get("error") or data.get("error_description")
        if oauth_error:
            raise BluelinkAuthenticationError(f"Hyundai API error: {_safe_json(data)}")
        ret_code = str(data.get("retCode") or "").upper()
        res_code = str(data.get("resCode") or "").upper()
        if ret_code in {"F", "FAIL", "FAILED", "ERROR", "E"} or res_code in {
            "F",
            "FAIL",
            "FAILED",
            "ERROR",
            "E",
        }:
            message = data.get("resMsg") or data.get("msg") or data
            raise BluelinkConnectionError(f"Hyundai API error: {_safe_json(message)}")
        return data

    raise BluelinkConnectionError("Hyundai returned an unexpected JSON response.")


def _make_stamp() -> str:
    """Return a fresh Hyundai stamp header."""
    raw = f"{APP_ID}:{int(time.time())}".encode()
    return base64.b64encode(bytes(a ^ b for a, b in zip(STAMP_CFB, raw))).decode()


def _token_headers() -> dict[str, str]:
    """Return OAuth token request headers."""
    return {
        "Authorization": BASIC_AUTHORIZATION,
        "Stamp": _make_stamp(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": BASE_HOST,
        "Connection": "close",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "okhttp/3.12.0",
    }


def _session_from_token(token: dict[str, Any], device_id: str) -> dict[str, Any]:
    """Normalize an OAuth token response."""
    access_token = token.get("access_token")
    token_type = token.get("token_type") or "Bearer"
    if not access_token:
        raise BluelinkAuthenticationError(
            "Token response did not include access_token."
        )
    expires_in = int(token.get("expires_in") or 23 * 60 * 60)
    return {
        "access_token": f"{token_type} {access_token}",
        "refresh_token": token.get("refresh_token"),
        "token_type": token_type,
        "expires_at": int(time.time()) + max(60, expires_in - 300),
        "device_id": device_id,
    }


def _extract_code(value: str) -> str:
    """Extract an OAuth code from a code value or redirect URL."""
    if "code=" not in value:
        return value
    parsed = urlparse(value)
    codes = parse_qs(parsed.query).get("code")
    if not codes:
        raise BluelinkAuthenticationError(
            "The Hyundai redirect URL did not include a code."
        )
    return codes[0]


def _normalize_bearer(token: str) -> str:
    """Return token with a Bearer prefix."""
    return token if token.startswith("Bearer ") else f"Bearer {token}"


def _ccs2_supported(vehicle: dict[str, Any]) -> bool:
    """Return true if a vehicle record reports CCS2 support."""
    return str(vehicle.get("ccuCCS2ProtocolSupport") or "0") not in {"0", "false"}


def _safe_json(value: Any) -> str:
    """Return redacted JSON for error messages."""
    sensitive = {"access_token", "refresh_token", "authorization", "controltoken"}

    def redact(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: (
                    "***redacted***"
                    if str(key).lower() in sensitive
                    else redact(inner)
                )
                for key, inner in item.items()
            }
        if isinstance(item, list):
            return [redact(inner) for inner in item]
        return item

    return json.dumps(redact(value), ensure_ascii=False)[:1200]
