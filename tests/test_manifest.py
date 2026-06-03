"""Tests for the integration manifest."""

from __future__ import annotations

import json
from pathlib import Path

MANIFEST = (
    Path(__file__).parents[1]
    / "custom_components"
    / "hyundai_bluelink"
    / "manifest.json"
)


def test_manifest_does_not_require_unpublished_aiobluelink() -> None:
    """HACS setup must not fail by trying to install an unpublished package."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert "aiobluelink>=0.1.0" not in manifest["requirements"]
    assert manifest["version"] == "0.1.4"
