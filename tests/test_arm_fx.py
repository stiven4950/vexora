"""Brazos, manos y lo que sostienen (video_41)."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.arm_fx import ARM_FX
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime

POSE = {"nose": (150, 90), "left_eye": (156, 86), "right_eye": (144, 86), "left_ear": (165, 90), "right_ear": (135, 90),
        "mouth_left": (155, 100), "mouth_right": (145, 100), "left_shoulder": (180, 130), "right_shoulder": (120, 130),
        "left_elbow": (225, 130), "right_elbow": (100, 175), "left_wrist": (270, 125), "right_wrist": (95, 215),
        "left_hip": (172, 225), "right_hip": (128, 225), "left_knee": (175, 275), "right_knee": (125, 275),
        "left_ankle": (178, 322), "right_ankle": (122, 322)}


def _drawn(shape: str, frames: range) -> list[float]:
    points = {k: np.array(v, float) for k, v in POSE.items()}
    points["vel:left_wrist"] = np.array([15.0, 0.0])
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "x", "hold": 10}])
    event = MotionEvent(name="x", target="person_0:left", start_frame=0, end_frame=19, confidence=1.0, kind="left")
    runtime = EffectRuntime(effect, 1, 10)
    out = []
    for f in frames:
        runtime.active_frames = f
        layer = np.zeros((360, 320, 4), np.float32)
        body = Body(points, None)
        lines = adornment(shape, body, body.frame(), 60.0, f, 1, runtime, layer, np.array([0, 1, 0], np.float32), 1.0, event=event)
        out.append(max(float(layer[..., 3].max()), 1.0 if lines else 0.0))
    return out


@pytest.mark.parametrize("shape", ARM_FX)
def test_every_arm_effect_draws(shape: str) -> None:
    assert max(_drawn(shape, range(0, 24, 2))) > 0.3


def test_the_ball_becomes_a_hook_and_the_bubble_pops() -> None:
    assert _drawn("hook_ball", [25])[0] > 0.3  # al final, el gancho
    assert _drawn("bubble_blow", [29])[0] < 0.3  # al final reventó: solo quedan gotitas que se apagan
