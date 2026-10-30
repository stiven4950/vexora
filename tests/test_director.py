"""Presets, validador y reintento del director."""

from __future__ import annotations

from pathlib import Path

import pytest

from vfxglow.analysis.schema import MotionBrief, VideoMeta
from vfxglow.config import DirectorConfig
from vfxglow.director.director import CreativeDirector
from vfxglow.director.presets import list_presets, load_preset
from vfxglow.director.schema import EffectScript
from vfxglow.director.validator import ScriptError, validate_script

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "configs" / "presets"


def test_all_presets_validate() -> None:
    names = list_presets(PRESETS)
    assert {"avatar_fire", "neon_joints", "body_aura", "avatar_storm", "fight_comic", "doodle_dance", "paint_reveal"} <= set(names)
    for name in names:
        script = load_preset(PRESETS / f"{name}.yaml", frame_count=120)
        assert script.effects
        for effect in script.effects:
            if not effect.triggers:
                assert effect.time.end_frame == 119


def test_unknown_effect_type_is_rejected() -> None:
    script = load_preset(PRESETS / "avatar_fire.yaml", 10)
    broken = script.model_dump()
    broken["effects"][0]["type"] = "pix2pix"
    with pytest.raises(Exception):
        EffectScript.model_validate(broken)


def test_lightning_without_secondary_is_allowed() -> None:
    script = load_preset(PRESETS / "neon_joints.yaml", 10)
    data = script.model_dump()
    for effect in data["effects"]:
        if effect["type"] == "lightning":
            effect["target"]["secondary"] = None
    parsed = EffectScript.model_validate(data)
    validate_script(parsed)


def test_unknown_event_is_rejected() -> None:
    script = load_preset(PRESETS / "avatar_storm.yaml", 24)
    data = script.model_dump()
    data["effects"][0]["triggers"][0]["event"] = "teleport"
    parsed = EffectScript.model_validate(data)
    with pytest.raises(ScriptError, match="evento desconocido"):
        validate_script(parsed)


def test_director_repairs_invalid_json_once() -> None:
    good = load_preset(PRESETS / "body_aura.yaml", 24).model_dump_json()
    calls = {"n": 0}

    def complete(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "no es json"
        assert "Errores" in prompt
        return good

    brief = MotionBrief(
        video=VideoMeta(path="v.mp4", fps=24, width=64, height=64, frame_count=24, duration_s=1),
        person_id="person_0",
        anchors=["right_wrist", "left_wrist"],
        limbs=[],
        events=[],
        summary="La mano derecha se eleva.",
    )
    director = CreativeDirector(DirectorConfig(provider="openai"), PRESETS, complete=complete)
    script = director.create(brief)
    assert script.theme == "body_aura"
    assert calls["n"] == 2
