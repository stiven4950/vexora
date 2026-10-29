"""Efectos de solista de video_52 y un color por toma."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.choreography import build_chapters
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.solo_fx import SOLO_FX

POSE = {"nose": (150, 90), "left_ear": (165, 90), "right_ear": (135, 90), "left_shoulder": (180, 130), "right_shoulder": (120, 130),
        "left_elbow": (225, 130), "right_elbow": (100, 175), "left_wrist": (275, 130), "right_wrist": (95, 215),
        "left_hip": (172, 225), "right_hip": (128, 225), "left_knee": (175, 275), "right_knee": (125, 275),
        "left_ankle": (178, 322), "right_ankle": (122, 322)}


@pytest.mark.parametrize("shape", SOLO_FX)
def test_every_solo_effect_draws(shape: str) -> None:
    points = {k: np.array(v, float) for k, v in POSE.items()}
    points["vel:nose"] = np.array([6.0, 0.0])
    points["vel:left_ankle"] = np.array([6.0, 0.0])
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "x", "hold": 10}])
    event = MotionEvent(name="x", target="person_0:left", start_frame=0, end_frame=19, confidence=1.0, kind="left")
    runtime = EffectRuntime(effect, 1, 10)
    drawn = 0.0
    for f in range(0, 24, 2):
        runtime.active_frames = f
        layer = np.zeros((360, 320, 4), np.float32)
        lines = adornment(shape, Body(points, None), Body(points, None).frame(), 60.0, f, 1, runtime, layer, np.array([0, 1, 0], np.float32), 1.0, event=event)
        drawn = max(drawn, float(layer[..., 3].max()), 1.0 if lines else 0.0)
    assert drawn > 0.3


def test_every_camera_cut_opens_a_color_chapter() -> None:
    palette = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    chapters = build_chapters([], palette, 1, 30.0, 300, 0.8, cuts=[40, 55, 200])
    assert [c.start_frame for c in chapters] == [0, 40, 55, 200]
    colors = [c.colors[0] for c in chapters]
    assert all(a != b for a, b in zip(colors, colors[1:]))  # cada toma cambia de color
