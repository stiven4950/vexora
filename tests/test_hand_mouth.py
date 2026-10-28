"""Mano en la boca (unpair_dance, video_41): el gesto y lo que se lleva a la boca."""

from __future__ import annotations

import numpy as np
import pytest

import vfxglow.analysis.gestures as G
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.hand_props import DRINKS, SMOKES, _liquid

W, H, FPS = 400, 800, 30.0
BASE = {"nose": (0.5, 0.2), "mouth_left": (0.51, 0.22), "mouth_right": (0.49, 0.22), "left_shoulder": (0.58, 0.3), "right_shoulder": (0.42, 0.3),
        "left_hip": (0.56, 0.55), "right_hip": (0.44, 0.55), "left_elbow": (0.64, 0.42), "right_elbow": (0.36, 0.42),
        "left_wrist": (0.66, 0.52), "right_wrist": (0.34, 0.52)}


def _record(i: int, **joints) -> FrameRecord:
    pts = dict(BASE, **joints)
    return FrameRecord(frame=i, time_s=i / FPS, pose=[Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in pts.items()])


def test_one_hand_at_the_mouth_is_detected() -> None:
    smoking = [_record(i, left_wrist=(0.53, 0.25)) for i in range(15)]
    events = G.hand_mouth_events(smoking, FPS, W, H)
    assert [(e.name, e.kind) for e in events] == [("hand_mouth", "left")]
    # Las dos manos en la cara es taparse la cara, no fumar ni beber.
    both = [_record(i, left_wrist=(0.53, 0.25), right_wrist=(0.47, 0.25)) for i in range(15)]
    assert G.hand_mouth_events(both, FPS, W, H) == []
    # Un instante no es un gesto.
    assert G.hand_mouth_events(smoking[:4] + [_record(i) for i in range(4, 15)], FPS, W, H) == []


def test_liquid_keeps_the_volume_with_a_flat_surface() -> None:
    square = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    half = _liquid(square, 0.5)
    assert abs(half[:, 1].min() - 5.0) < 0.1  # la superficie, a media altura
    assert len(_liquid(square, 0.0)) == 0


@pytest.mark.parametrize("shape", DRINKS + SMOKES)
def test_mouth_props_draw_and_fade_away(shape: str) -> None:
    pts = {k: np.array([x * 200, y * 200]) for k, (x, y) in dict(BASE, left_wrist=(0.6, 0.3)).items()}
    body = Body(pts, None)
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "hand_mouth", "hold": 10}])
    event = MotionEvent(name="hand_mouth", target="person_0:left", start_frame=0, end_frame=29, confidence=1.0, kind="left")
    runtime = EffectRuntime(effect, 1, 10)
    drawn = []
    for f in (5, 39):  # en pleno momento y al final (desdibujado)
        runtime.active_frames = f
        layer = np.zeros((200, 200, 4), np.float32)
        lines = adornment(shape, body, body.frame(), 30.0, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        drawn.append(sum(float(np.linalg.norm(np.diff(line, axis=0), axis=1).sum()) for line in lines))
    assert drawn[0] > 0
    assert drawn[1] < drawn[0]
