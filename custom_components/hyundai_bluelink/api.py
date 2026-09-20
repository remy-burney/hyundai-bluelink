"""Async Hyundai Bluelink Australia API client.

This is a local HACS-compatible adapter for the upstream client contract used by
the integration. The code should move to a standalone `aiobluelink` package
before a Home Assistant Core submission.
"""

from __future__ import annotations

import asyncio
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


class BluelinkAccountActionRequiredError(BluelinkAuthenticationError):
    """Hyundai requires the user to complete an interactive account step."""


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
        self._credentials: tuple[str, str] | None = None
        self._auth_lock = asyncio.Lock()
        self._authentication_error: BluelinkAuthenticationError | None = None

    async def async_login(
        self,
        username: str,
        password: str,
        *,
        pin: str | None = None,
    ) -> None:
        """Authenticate with Hyundai Bluelink."""
        async with self._auth_lock:
            self._credentials = (username, password)
            self._authentication_error = None
            await self._async_login()

    async def _async_login(self) -> None:
        """Sign in with saved credentials while holding the authentication lock."""
        if self._authentication_error is not None:
            raise self._authentication_error
        try:
            await self._async_sign_in()
        except BluelinkAuthenticationError as exc:
            # Other requests must share a rejected login, not submit the same
            # password again. An explicit login resets this terminal failure.
            self._authentication_error = exc
            raise

    async def _async_sign_in(self) -> None:
        """Complete the Hyundai authorization-code flow."""
        if self._credentials is None:
            raise BluelinkAuthenticationError(
                "Not authenticated with Hyundai Bluelink."
            )
        username, password = self._credentials
        self.account_id = username
        if self._device_id is None:
            self._device_id = await self._async_register_device()

        try:
            async with self.session.get(
                self._auth_url(),
                timeout=REQUEST_TIMEOUT,
            ) as auth_response:
                if auth_response.status >= 400:
                    await _async_checked_json(auth_response)
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
        except (ClientError, TimeoutError) as exc:
            raise BluelinkConnectionError(str(exc)) from exc

        redirect_url = response.get("redirectUrl")
        if not redirect_url:
            if response.get("step") == 5:
                raise BluelinkAccountActionRequiredError(
                    "Hyundai requests a password update. Sign in to the official "
                    "Bluelink app and complete the password prompt, then "
                    "reauthenticate in Home Assistant with your current password."
                )
            if "step" in response or response.get("upgrade"):
                raise BluelinkAccountActionRequiredError(
                    "Sign in to the official Bluelink app and complete the "
                    "account prompts, then reauthenticate in Home Assistant."
                )
            raise BluelinkAuthenticationError(
                "Hyundai did not return an OAuth redirect URL."
            )

        code = _extract_code(redirect_url)
        self._tokens = await self._async_exchange_code(code, self._device_id)

    async def async_close(self) -> None:
        """Close client resources."""
        self._credentials = None
        self._tokens = {}
        self._authentication_error = None

    async def async_get_vehicles(self) -> list[dict[str, Any]]:
        """Return vehicles for the account."""
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
        ccs2 = _ccs2_protocol(vehicle)
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
            ccs2=_ccs2_protocol(vehicle),
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
        ccs2 = _ccs2_protocol(vehicle)
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
            {"action": "close", "deviceId": self._device_id},
            pin=pin,
            ccs2_body={"command": "close"},
        )

    async def async_unlock(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Unlock the vehicle."""
        return await self._async_vehicle_command(
            vehicle_id,
            "door",
            {"action": "open", "deviceId": self._device_id},
            pin=pin,
            ccs2_body={"command": "open"},
        )

    async def async_start_engine(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Start the engine for five minutes with air conditioning off."""
        return await self._async_vehicle_command(
            vehicle_id,
            "engine",
            {"action": "start", "options": {"airCtrl": 0, "igniOnDuration": 5}},
            pin=pin,
            ccs2_body={"command": "start", "hvacCtrl": 0, "ignitionDuration": 5},
        )

    async def async_stop_engine(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Stop the engine."""
        return await self._async_vehicle_command(
            vehicle_id,
            "engine",
            {"action": "stop", "deviceId": self._device_id},
            pin=pin,
            ccs2_body={"command": "stop"},
        )

    async def async_horn(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Sound the horn and flash the lights, as in the Australian app."""
        return await self.async_horn_light(vehicle_id, pin=pin)

    async def async_light(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Flash the lights."""
        return await self._async_vehicle_command(
            vehicle_id,
            "light",
            {"deviceId": self._device_id},
            pin=pin,
            ccs2_body={"command": "on"},
        )

    async def async_horn_light(self, vehicle_id: str, *, pin: str) -> dict[str, Any]:
        """Sound the horn and flash the lights."""
        return await self._async_vehicle_command(
            vehicle_id,
            "horn",
            {"deviceId": self._device_id},
            pin=pin,
            ccs2_body={"command": "on"},
            ccs2_command="hornlight",
        )

    async def async_open_windows(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Open the windows."""
        return await self._async_window_command(vehicle_id, 1, pin=pin)

    async def async_close_windows(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Close the windows."""
        return await self._async_window_command(vehicle_id, 0, pin=pin)

    async def async_ventilate_windows(
        self,
        vehicle_id: str,
        *,
        pin: str,
    ) -> dict[str, Any]:
        """Start window ventilation."""
        return await self._async_window_command(vehicle_id, 2, pin=pin)

    async def _async_window_command(
        self, vehicle_id: str, position: int, *, pin: str
    ) -> dict[str, Any]:
        """Select the window contract using the same capabilities as the app."""
        vehicle = await self._async_get_vehicle_record(vehicle_id)
        data = await self._async_request(
            "GET",
            f"/api/v1/spa/vehicles/{vehicle_id}/profile",
            ccs2=_ccs2_protocol(vehicle),
        )
        payload = data.get("resMsg")
        profiles = payload.get("vinInfo") if isinstance(payload, dict) else None
        if (
            not isinstance(profiles, list)
            or not profiles
            or not isinstance(profiles[0], dict)
        ):
            raise BluelinkConnectionError(
                "Hyundai did not return a vehicle profile for window control."
            )
        profile = profiles[0]
        options = profile.get("option") or {}
        service_options = profile.get("serviceOption") or {}
        old_windows = (
            _option_number(options, "windowSafetyOption") == 1
            and _option_number(options, "windowSafetyOption2") == -1
        )
        new_windows = _option_number(options, "windowSafetyOption2") == 3
        control_option = _option_number(service_options, "windowControlOption")
        if not (old_windows or new_windows):
            raise BluelinkConnectionError(
                "This vehicle does not report support for remote window control."
            )
        if position == 2 and not (new_windows or control_option in {2, 3}):
            raise BluelinkConnectionError(
                "This vehicle does not report support for window ventilation."
            )
        if old_windows and control_option == -1:
            action = "open" if position == 1 else "close"
            return await self._async_vehicle_command(
                vehicle_id,
                "window",
                {"deviceId": self._device_id, "action": action},
                pin=pin,
                ccs2_body={"command": action},
            )
        ccs2_body: dict[str, Any] = {
            "drvSeatWindow": position,
            "psgSeatWindow": position,
            "rlSeatWindow": position,
            "rrSeatWindow": position,
        }
        seat_location = options.get("drvSeatLoc")
        if seat_location:
            ccs2_body["drvSeatLoc"] = seat_location
        # Only request window movement. Absent curtain fields are omitted by
        # the app's serializer too; never send invented values or JSON nulls.
        return await self._async_vehicle_command(
            vehicle_id,
            "windowcurtain",
            {
                "deviceId": self._device_id,
                "frontLeft": position,
                "frontRight": position,
                "backLeft": position,
                "backRight": position,
            },
            pin=pin,
            ccs2_body=ccs2_body,
        )

    async def _async_vehicle_command(
        self,
        vehicle_id: str,
        command: str,
        body: dict[str, Any],
        *,
        pin: str,
        ccs2_body: dict[str, Any] | None = None,
        ccs2_command: str | None = None,
    ) -> dict[str, Any]:
        """Execute a PIN-protected vehicle command."""
        vehicle = await self._async_get_vehicle_record(vehicle_id)
        ccs2 = _ccs2_protocol(vehicle)
        path = (
            f"/api/v2/spa/vehicles/{vehicle_id}/ccs2/control/{ccs2_command or command}"
            if ccs2
            else f"/api/v2/spa/vehicles/{vehicle_id}/control/{command}"
        )
        return await self._async_control_request(
            "POST",
            path,
            json_data=ccs2_body if ccs2 and ccs2_body is not None else body,
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
        ccs2: int = 0,
    ) -> dict[str, Any]:
        """Call a control endpoint with a short-lived control token."""
        control_token = await self._async_get_control_token(pin, ccs2=ccs2)
        headers = self._api_headers(control_token, ccs2=ccs2)
        return await self._async_request(
            method,
            path,
            json_data=json_data,
            headers=headers,
            authenticated=False,
        )

    async def _async_get_control_token(self, pin: str | None, *, ccs2: int = 0) -> str:
        """Return a short-lived remote control token."""
        if pin is None:
            raise BluelinkAuthenticationError("Remote control PIN is required.")
        data = await self._async_request(
            "PUT",
            "/api/v1/user/pin",
            json_data={"deviceId": self._device_id, "pin": pin},
            ccs2=ccs2,
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

    async def _async_ensure_session(self) -> bool:
        """Ensure valid tokens and return whether a fresh login was needed."""
        async with self._auth_lock:
            if self._authentication_error is not None:
                raise self._authentication_error
            if int(self._tokens.get("expires_at") or 0) > int(time.time()):
                return False
            refresh_token = self._tokens.get("refresh_token")
            if refresh_token:
                try:
                    self._tokens = await self._async_refresh_token(str(refresh_token))
                    return False
                except BluelinkAuthenticationError:
                    # Only rejected credentials warrant a fresh login. Let outages
                    # propagate as connection errors so Home Assistant retries later.
                    pass
            await self._async_login()
            return True

    async def _async_reauthenticate(self, rejected_tokens: dict[str, Any]) -> None:
        """Replace a rejected session once, sharing recovery across requests."""
        async with self._auth_lock:
            if self._tokens is rejected_tokens:
                await self._async_login()

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
        ccs2: int = 0,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        """Make a Hyundai API request and validate the JSON response."""
        logged_in = False
        if authenticated:
            logged_in = await self._async_ensure_session()
        request_tokens = self._tokens
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
            if not authenticated or method != "GET" or not retry_auth or logged_in:
                raise
            await self._async_reauthenticate(request_tokens)
            return await self._async_request(
                method,
                path,
                data=data,
                json_data=json_data,
                headers=headers,
                authenticated=authenticated,
                ccs2=ccs2,
                retry_auth=False,
            )
        except BluelinkConnectionError:
            raise
        except (ClientError, TimeoutError) as exc:
            raise BluelinkConnectionError(str(exc)) from exc

    def _api_headers(
        self,
        token: str | None,
        *,
        ccs2: int = 0,
    ) -> dict[str, str]:
        """Return common Hyundai API headers."""
        headers = {
            "ccsp-service-id": CLIENT_ID,
            "ccsp-application-id": APP_ID,
            "Stamp": _make_stamp(),
            "Host": BASE_HOST,
            "Connection": "close",
            "Accept-Encoding": "gzip",
            "Ccuccs2protocolsupport": str(ccs2),
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
        if response.status in {401, 403}:
            raise BluelinkAuthenticationError(
                f"Hyundai returned HTTP {response.status}."
            ) from exc
        raise BluelinkConnectionError(
            f"Hyundai returned non-JSON HTTP {response.status}."
        ) from exc

    if response.status in {401, 403}:
        raise BluelinkAuthenticationError(
            f"Hyundai returned HTTP {response.status}: {_safe_json(data)}"
        )
    if response.status == 429 or response.status >= 500:
        raise BluelinkConnectionError(
            f"Hyundai returned HTTP {response.status}: {_safe_json(data)}"
        )

    if isinstance(data, dict):
        oauth_error = data.get("error") or data.get("error_description")
        if isinstance(oauth_error, str) and oauth_error in {
            "invalid_grant",
            "invalid_token",
            "invalid_client",
            "unauthorized_client",
            "access_denied",
        }:
            raise BluelinkAuthenticationError(f"Hyundai API error: {_safe_json(data)}")
        ret_code = str(data.get("retCode") or "").upper()
        res_code = str(data.get("resCode") or "").upper()
        failed = ret_code in {"F", "FAIL", "FAILED", "ERROR", "E"} or res_code in {
            "F",
            "FAIL",
            "FAILED",
            "ERROR",
            "E",
        }
        if res_code == "4004" and (response.status >= 400 or failed):
            raise BluelinkConnectionError(
                "Hyundai is still processing a previous remote command (4004). "
                "Wait for it to finish before trying again. The displayed vehicle "
                "status is the last known status and may be delayed."
            )
        if response.status >= 400 or oauth_error:
            raise BluelinkConnectionError(
                f"Hyundai returned HTTP {response.status}: {_safe_json(data)}"
            )
        if failed:
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


def _ccs2_protocol(vehicle: dict[str, Any]) -> int:
    """Preserve the reported protocol version in Hyundai request headers."""
    try:
        return max(0, int(vehicle.get("ccuCCS2ProtocolSupport") or 0))
    except (TypeError, ValueError):
        return 0


def _option_number(options: Any, key: str) -> int:
    """Read an integer capability, preserving the app's missing-value sentinel."""
    if not isinstance(options, dict):
        return -1
    try:
        return int(options.get(key, -1))
    except (TypeError, ValueError):
        return -1


def _safe_json(value: Any) -> str:
    """Return redacted JSON for error messages."""
    sensitive = {
        "access_token",
        "refresh_token",
        "authorization",
        "controltoken",
        "password",
        "pin",
    }

    def redact(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: (
                    "***redacted***" if str(key).lower() in sensitive else redact(inner)
                )
                for key, inner in item.items()
            }
        if isinstance(item, list):
            return [redact(inner) for inner in item]
        return item

    return json.dumps(redact(value), ensure_ascii=False)[:1200]
