"""Presets locales. Producen el mismo Effect Script que el director remoto."""

from __future__ import annotations

from pathlib import Path

import yaml

from vfxglow.director.schema import EffectScript, resolve_timing
from vfxglow.director.validator import validate_script


def load_preset(path: Path, frame_count: int) -> EffectScript:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    script = resolve_timing(EffectScript.model_validate(raw), frame_count)
    validate_script(script)
    return script


def list_presets(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.yaml"))
