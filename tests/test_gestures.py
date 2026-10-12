"""Gestos con significado: amago de lanzamiento y corte de cuello, y sus efectos."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.gestures import neck_slash_events, throw_events
from vfxglow.analysis.schema import FrameRecord, HandFrame, Landmark, MotionEvent
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine

W, H, FPS = 400, 800, 30.0
BASE = {
    "nose": (0.5, 0.2), "left_eye": (0.48, 0.19), "right_eye": (0.52, 0.19), "mouth_left": (0.49, 0.22), "mouth_right": (0.51, 0.22),
    "left_ear": (0.46, 0.2), "right_ear": (0.54, 0.2), "left_shoulder": (0.42, 0.3), "right_shoulder": (0.58, 0.3),
    "left_hip": (0.44, 0.55), "right_hip": (0.56, 0.55), "left_wrist": (0.38, 0.5), "right_wrist": (0.62, 0.5),
}


def _record(i: int, right_wrist: tuple[float, float], tip: tuple[float, float] | None = None) -> FrameRecord:
    pts = dict(BASE, right_wrist=right_wrist)
    pose = [Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in pts.items()]
    hand = HandFrame(landmarks=[Landmark(name="right_index_tip", x=tip[0], y=tip[1], c=1.0)], score=1.0) if tip else None
    return FrameRecord(frame=i, time_s=i / FPS, pose=pose, right_hand=hand)


def _throw_path() -> list[tuple[float, float]]:
    """Muñeca quieta abajo, sube y carga arriba, baja de golpe y se extiende hacia afuera."""
    path = [(0.62, 0.5)] * 10
    path += [(0.6, 0.5 - 0.03 * k) for k in range(8)]  # sube
    path += [(0.6, 0.26)] * 12  # carga arriba del hombro
    path += [(0.6 + 0.05 * k, 0.26 + 0.07 * k) for k in range(1, 6)]  # suelta hacia abajo y afuera
    path += [(0.85, 0.61)] * 15
    return path


def test_throw_needs_a_windup_and_an_extension() -> None:
    frames = [_record(i, w) for i, w in enumerate(_throw_path())]
    events = throw_events(frames, FPS, W, H)
    assert len(events) == 1 and events[0].kind == "right"
    assert events[0].start_frame < 20 < events[0].end_frame
    # Bajar el brazo pegado al cuerpo, sin carga, no es un lanzamiento.
    drop = [_record(i, (0.62, 0.3 + 0.05 * max(i - 10, 0))) for i in range(20)]
    assert throw_events(drop, FPS, W, H) == []


def test_neck_slash_is_a_quick_sweep_across_the_neck() -> None:
    sweep = [_record(i, (0.6, 0.3), (0.44 + 0.03 * (i - 5), 0.26) if 5 <= i < 10 else (0.8, 0.6)) for i in range(20)]
    events = neck_slash_events(sweep, FPS, W, H)
    assert len(events) == 1 and events[0].kind == "right"
    still = [_record(i, (0.6, 0.3), (0.5, 0.26)) for i in range(40)]  # mano quieta en el cuello 1,3 s
    assert neck_slash_events(still, FPS, W, H) == []


def test_throw_fx_charges_in_the_hand_then_releases() -> None:
    effect = Effect(id="t", type="throw_fx", target=EffectTarget(kind="joint", id="right_wrist"), style=EffectStyle(shapes=["ray"]), triggers=[{"event": "throw", "hold": 20, "fade_in": 0, "fade_out": 0}])
    event = MotionEvent(name="throw", target="person_0:right_wrist", start_frame=0, end_frame=10, confidence=1.0, position=(0.6, 0.5), direction_deg=0.0, kind="right")
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[event])
    record = _record(0, (0.6, 0.26), (0.6, 0.24))
    charge = engine.render_frame(record, 5, W, H, 60)[0][2]
    ys, xs = np.nonzero(charge[..., 3] > 0.5)
    assert xs.size and abs(xs.mean() - 0.6 * W) < 0.05 * W and abs(ys.mean() - 0.24 * H) < 0.04 * H
    for frame in range(6, 14):
        layer = engine.render_frame(record, frame, W, H, 60)[0][2]
    ys, xs = np.nonzero(layer[..., 3] > 0.5)
    assert xs.max() > 0.8 * W  # el rayo sale hacia la derecha desde la mano
