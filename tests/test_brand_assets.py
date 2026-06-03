"""Tests for bundled brand image assets."""

from __future__ import annotations

import struct
from pathlib import Path

BRAND_DIR = (
    Path(__file__).parents[1]
    / "custom_components"
    / "hyundai_bluelink"
    / "brand"
)


def _read_png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_brand_assets_are_available() -> None:
    """Validate Home Assistant/HACS brand assets are present."""
    for filename in ("icon.png", "logo.png"):
        path = BRAND_DIR / filename
        assert path.exists()
        assert _read_png_size(path) == (512, 512)
