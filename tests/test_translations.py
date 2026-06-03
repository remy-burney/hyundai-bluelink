from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

TRANSLATIONS_DIR = Path("custom_components/hyundai_bluelink/translations")


def test_translation_files_match_english_keys() -> None:
    english = _load_translation("en.json")
    english_keys = set(_leaf_paths(english))

    translation_files = sorted(TRANSLATIONS_DIR.glob("*.json"))

    assert len(translation_files) >= 50
    for translation_file in translation_files:
        translation = _load_translation(translation_file.name)
        assert set(_leaf_paths(translation)) == english_keys, translation_file.name


def _load_translation(filename: str) -> dict[str, Any]:
    return json.loads((TRANSLATIONS_DIR / filename).read_text(encoding="utf-8"))


def _leaf_paths(value: Any, prefix: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _leaf_paths(item, next_prefix)
        return

    yield prefix
