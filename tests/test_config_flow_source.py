"""Source checks for Home Assistant config-flow compatibility."""

from __future__ import annotations

from pathlib import Path

CONFIG_FLOW = (
    Path(__file__).parents[1]
    / "custom_components"
    / "hyundai_bluelink"
    / "config_flow.py"
)


def test_options_flow_uses_home_assistant_config_entry_property() -> None:
    """The OptionsFlow handler must not assign Home Assistant's config_entry."""
    source = CONFIG_FLOW.read_text(encoding="utf-8")

    assert "return HyundaiBluelinkOptionsFlow()" in source
    assert "self.config_entry =" not in source
