"""Tests for the bundled Bluelink API adapter."""

from __future__ import annotations

from custom_components.hyundai_bluelink.api import (
    _ccs2_supported,
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


def test_ccs2_supported() -> None:
    """Vehicle CCS2 support is parsed from Hyundai vehicle records."""
    assert _ccs2_supported({"ccuCCS2ProtocolSupport": 1}) is True
    assert _ccs2_supported({"ccuCCS2ProtocolSupport": 0}) is False
