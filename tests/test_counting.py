"""Contar con los dedos (unpair_dance, seg. 16,3-19,5): el gesto y el número en la cara."""

from __future__ import annotations

import numpy as np

import vfxglow.analysis.gestures as G
from vfxglow.analysis.schema import FrameRecord, HandFrame, Landmark, MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.counting import current_count
from vfxglow.engine.effects import EffectRuntime

W, H, FPS = 400, 800, 30.0
BASE = {"nose": (0.5, 0.2), "left_ear": (0.54, 0.2), "right_ear": (0.46, 0.2), "left_shoulder": (0.58, 0.3), "right_shoulder": (0.42, 0.3),
        "left_hip": (0.56, 0.55), "right_hip": (0.44, 0.55), "left_elbow": (0.62, 0.35), "right_elbow": (0.38, 0.35),
        "left_wrist": (0.6, 0.28), "right_wrist": (0.4, 0.28)}
FINGERS = ("index", "middle", "ring", "pinky")


def _hand(side: str, wx: float, wy: float, up: int) -> HandFrame:
    """Una mano con la muñeca en (wx, wy) y los primeros `up` dedos estirados hacia arriba."""
    marks = [Landmark(name=f"{side}_wrist", x=wx, y=wy, c=1.0), Landmark(name=f"{side}_index_mcp", x=wx, y=wy - 0.03, c=1.0)]
    for k, finger in enumerate(FINGERS):
        x = wx + (k - 1.5) * 0.008
        tip_y = wy - (0.08 if k < up else 0.035)  # recogido: la punta vuelve hacia la palma
        marks += [Landmark(name=f"{side}_{finger}_pip", x=x, y=wy - 0.05, c=1.0), Landmark(name=f"{side}_{finger}_tip", x=x, y=tip_y, c=1.0)]
    marks += [Landmark(name=f"{side}_thumb_ip", x=wx - 0.015, y=wy - 0.025, c=1.0), Landmark(name=f"{side}_thumb_tip", x=wx - 0.004, y=wy - 0.028, c=1.0)]  # el pulgar, recogido contra la palma
    return HandFrame(landmarks=marks, score=1.0)


def _record(i: int, up: int, raised: bool = True) -> FrameRecord:
    pts = dict(BASE) if raised else dict(BASE, left_wrist=(0.6, 0.6))
    return FrameRecord(frame=i, time_s=i / FPS, pose=[Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in pts.items()],
                       left_hand=_hand("left", *pts["left_wrist"], up))


def test_counting_with_the_fingers_is_detected_with_each_change() -> None:
    frames = [_record(i, 1 + i // 12) for i in range(36)]  # 1, 2, 3
    events = G.finger_count_events(frames, FPS, W, H)
    assert len(events) == 1
    assert events[0].detail == "conteo=0:1,12:2,24:3"
    # Mostrar la mano quieta no es contar.
    assert G.finger_count_events([_record(i, 2) for i in range(36)], FPS, W, H) == []
    # Con la mano abajo tampoco.
    assert G.finger_count_events([_record(i, 1 + i // 12, raised=False) for i in range(36)], FPS, W, H) == []


def test_the_number_follows_the_count() -> None:
    event = MotionEvent(name="finger_count", target="person_0", start_frame=0, end_frame=35, confidence=1.0, detail="conteo=0:1,12:2,24:3")
    assert current_count(event, 5, 5)[0] == 1
    assert current_count(event, 13, 13) == (2, 1)
    assert current_count(event, 30, 30)[0] == 3
    assert current_count(None, 0, 30)[0] == 3  # fijado a mano: cuenta solo


def test_the_number_is_written_on_the_face() -> None:
    pts = {n: np.array([x * 200, y * 200]) for n, (x, y) in BASE.items()}
    body = Body(pts, None)
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["finger_number"]))
    runtime = EffectRuntime(effect, 1, 10)
    runtime.active_frames = 20
    layer = np.zeros((200, 200, 4), np.float32)
    lines = adornment("finger_number", body, body.frame(), 30.0, 20, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0)
    assert lines
    center = np.mean(np.vstack(lines), axis=0)
    assert np.linalg.norm(center - pts["nose"]) < 10  # sobre la cara
