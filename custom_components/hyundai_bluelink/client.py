from __future__ import annotations

from typing import Any, Protocol

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_PIN, CONF_REGION, DEFAULT_REGION

try:
    from aiobluelink import AsyncBluelinkClient as _AsyncBluelinkClient
except ImportError:
    _AsyncBluelinkClient = None

try:
    from aiobluelink.exceptions import (
        BluelinkAuthenticationError,
        BluelinkConnectionError,
    )
except ImportError:

    class BluelinkAuthenticationError(Exception):
        """Authentication error raised by the upstream Bluelink client."""

    class BluelinkConnectionError(Exception):
        """Connection error raised by the upstream Bluelink client."""


class BluelinkClientMissingError(BluelinkConnectionError):
    """Raised when the upstream async Bluelink client is not installed."""


class BluelinkClientProtocol(Protocol):
    """Protocol for the upstream async Bluelink client."""

    account_id: str | None

    async def async_login(
        self,
        username: str,
        password: str,
        *,
        pin: str | None = None,
    ) -> None:
        """Authenticate with Bluelink."""

    async def async_close(self) -> None:
        """Close client resources."""

    async def async_get_vehicles(self) -> list[dict[str, Any]]:
        """Return vehicles for the account."""

    async def async_get_vehicle_status(self, vehicle_id: str) -> dict[str, Any]:
        """Return vehicle status."""

    async def async_get_vehicle_location(self, vehicle_id: str) -> dict[str, Any]:
        """Return vehicle location."""


async def async_create_client(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> BluelinkClientProtocol:
    """Create the upstream async Bluelink client."""
    if _AsyncBluelinkClient is None:
        raise BluelinkClientMissingError(
            "The aiobluelink package is not installed. Publish/install the upstream "
            "async client before loading this integration."
        )

    session = async_get_clientsession(hass)
    region = data.get(CONF_REGION, DEFAULT_REGION)
    try:
        return _AsyncBluelinkClient(region=region, session=session)
    except TypeError:
        return _AsyncBluelinkClient(session=session)


async def async_login_client(
    client: BluelinkClientProtocol,
    data: dict[str, Any],
) -> None:
    """Log in through the upstream client using config-entry data."""
    username = data[CONF_USERNAME]
    password = data[CONF_PASSWORD]
    pin = data.get(CONF_PIN) or None
    try:
        await client.async_login(username=username, password=password, pin=pin)
    except TypeError:
        await client.async_login(username, password, pin=pin)


async def async_close_client(client: BluelinkClientProtocol) -> None:
    """Close the upstream client if it exposes a close hook."""
    close = getattr(client, "async_close", None)
    if close is not None:
        await close()
