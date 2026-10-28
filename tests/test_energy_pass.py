"""Pase de energía (video_41, unpair_dance): de una mano a la otra, entre las manos y entre personas."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.energy_pass import ENERGY_PASS, _partner

POSE = {"nose": (110, 60), "left_shoulder": (140, 95), "right_shoulder": (80, 95), "left_elbow": (160, 135), "right_elbow": (60, 135),
        "left_wrist": (165, 170), "right_wrist": (55, 170), "left_hip": (130, 185), "right_hip": (90, 185),
        "left_knee": (132, 240), "right_knee": (88, 240), "left_ankle": (134, 295), "right_ankle": (86, 295)}


def _people(*offsets: int) -> dict[str, np.ndarray]:
    return {f"person_{k}:{name}": np.array([x + dx, y], float) for k, dx in enumerate(offsets) for name, (x, y) in POSE.items()}


def _lit(shape: str, points: dict[str, np.ndarray], frames: range) -> list[np.ndarray]:
    """La capa de cada fotograma (alfa) dibujando `shape` para person_0."""
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "x", "hold": 10}])
    event = MotionEvent(name="x", target="person_0:left", start_frame=0, end_frame=29, confidence=1.0, kind="left")
    runtime = EffectRuntime(effect, 1, 10)
    out = []
    for f in frames:
        runtime.active_frames = f
        body = Body(points, "person_0")
        layer = np.zeros((320, 420, 4), np.float32)
        adornment(shape, body, body.frame(), 60.0, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        out.append(layer[..., 3])
    return out


@pytest.mark.parametrize("shape", ENERGY_PASS)
def test_every_pass_draws(shape: str) -> None:
    assert max(float(a.max()) for a in _lit(shape, _people(0, 200), range(0, 30, 3))) > 0.3


def test_arm_relay_travels_from_the_gesture_hand_to_the_other() -> None:
    early, late = _lit("arm_relay", _people(0), [6, 33])
    left_hand, right_hand = (170, 165), (170, 55)
    assert early[left_hand] > early[right_hand]  # sale de la mano del gesto (la izquierda)
    assert late[right_hand] > late[left_hand]  # y llega a la otra


def test_person_relay_reaches_the_partner() -> None:
    points = _people(0, 200)
    assert _partner(Body(points, "person_0")) == "person_1:"
    last = _lit("person_relay", points, [37])[0]
    assert last[:, 230:].max() > 0.3  # termina en la otra persona
    assert _partner(Body(_people(0), "person_0")) is None
