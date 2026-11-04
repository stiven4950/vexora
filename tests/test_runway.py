"""Piezas del desfile que van con la pose (engine/runway_fx.py): lucecitas en el pelo, anillos en las
articulaciones y el destello de la pisada."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from vfxglow.analysis.regions import HAIR, SKIN
from vfxglow.analysis.schema import MotionEvent
from vfxglow.engine.bodyglow import Body
from vfxglow.engine.runway_fx import hair_lights, joint_rings, step_glint

H, W = 400, 200
TINT = np.ones(3, np.float32)


def _runtime(labels=None, active: int = 5):
    return SimpleNamespace(frame_shape=(H, W), fps=30.0, swoosh={}, kernels={}, regions=labels, active_frames=active)


def _standing(**moved) -> dict[str, np.ndarray]:
    points = {
        "nose": (100, 60), "left_shoulder": (125, 110), "right_shoulder": (75, 110),
        "left_elbow": (135, 160), "right_elbow": (65, 160), "left_wrist": (138, 205), "right_wrist": (62, 205),
        "left_hip": (115, 210), "right_hip": (85, 210), "left_knee": (130, 290), "right_knee": (70, 290),
        "left_ankle": (132, 360), "right_ankle": (68, 360), "left_heel": (128, 368), "right_heel": (64, 368),
        "left_foot_index": (145, 372), "right_foot_index": (80, 372),
    }
    points.update(moved)
    return {k: np.asarray(v, np.float64) for k, v in points.items()}


def _event(name: str, target: str = "person_0") -> MotionEvent:
    return MotionEvent(name=name, target=target, start_frame=0, end_frame=20, confidence=1.0)


def test_the_hair_lights_sit_on_the_real_hair() -> None:
    labels = np.zeros((H, W), np.uint8)
    labels[10:50, 60:140] = HAIR  # el pelo, sobre la cabeza
    labels[50:90, 70:130] = SKIN
    body = Body(_standing(), None)
    runtime = _runtime(labels)
    layer = np.zeros((H, W, 4), np.float32)
    lines = hair_lights("hair_lights", body, None, 50.0, 0, runtime, layer, TINT, 1.0, _event("outfit_head"))
    centers = [line.mean(axis=0) for line, _tint in lines[::2]]
    assert len(centers) == 12
    on_hair = [labels[int(round(c[1])), int(round(c[0]))] == HAIR for c in centers]
    assert all(on_hair)


def test_an_elbow_off_the_person_gets_no_ring() -> None:
    labels = np.zeros((H, W), np.uint8)
    labels[100:380, 50:150] = SKIN  # la persona
    on = Body(_standing(), None)
    off = Body(_standing(right_elbow=(10, 160)), None)  # la pose inventa el codo que no se ve: en el aire
    draw = lambda body: joint_rings("joint_rings", body, None, 50.0, 0, _runtime(labels), np.zeros((H, W, 4), np.float32), TINT, 1.0, _event("outfit_joints"))
    assert len(draw(off)) == len(draw(on)) - 2  # sin las dos mitades de ese anillo


def test_knees_together_keep_only_the_front_ring() -> None:
    apart = Body(_standing(), None)
    together = Body(_standing(left_knee=(104, 290), right_knee=(96, 290), right_ankle=(95, 340)), None)  # el pie derecho atrás (más arriba)
    draw = lambda body: joint_rings("joint_rings", body, None, 50.0, 0, _runtime(), np.zeros((H, W, 4), np.float32), TINT, 1.0, _event("outfit_joints"))
    assert len(draw(together)) == len(draw(apart)) - 3  # sin las dos mitades del anillo de atrás ni su línea


def test_the_step_ring_opens_on_the_floor_under_the_shoe() -> None:
    labels = np.zeros((H, W), np.uint8)
    labels[100:385, 120:150] = SKIN  # la pierna y la bota izquierdas: la suela termina en y = 384
    body = Body(_standing(), None)
    event = _event("step", "person_0:left_ankle")
    lines = step_glint("step_glint", body, None, 50.0, 0, _runtime(labels, active=1), np.zeros((H, W, 4), np.float32), TINT, 1.0, event)
    ring = np.vstack([lines[1][0], lines[2][0]])
    assert abs(ring[:, 1].mean() - 384) < 2 and abs(ring[:, 0].mean() - 136.5) < 2
    assert step_glint("step_glint", body, None, 50.0, 0, _runtime(labels, active=20), np.zeros((H, W, 4), np.float32), TINT, 1.0, event) == []
