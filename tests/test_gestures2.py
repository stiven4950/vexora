"""Gestos sostenidos (corazón, brazos arriba y abiertos, oído, ojos, giro) y sus efectos."""

from __future__ import annotations

import numpy as np

import vfxglow.analysis.gestures as G
from vfxglow.analysis.schema import FrameRecord, HandFrame, Landmark, MotionEvent
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectTarget
from vfxglow.engine.engine import EffectEngine

W, H, FPS = 400, 800, 30.0
BASE = {"nose": (0.5, 0.2), "left_eye": (0.52, 0.19), "right_eye": (0.48, 0.19), "left_ear": (0.56, 0.2), "right_ear": (0.44, 0.2),
        "mouth_left": (0.51, 0.22), "mouth_right": (0.49, 0.22), "left_shoulder": (0.58, 0.3), "right_shoulder": (0.42, 0.3),
        "left_hip": (0.56, 0.55), "right_hip": (0.44, 0.55), "left_elbow": (0.64, 0.42), "right_elbow": (0.36, 0.42),
        "left_wrist": (0.66, 0.52), "right_wrist": (0.34, 0.52), "left_ankle": (0.56, 0.9), "right_ankle": (0.44, 0.9)}


def _record(i: int, tip: tuple[float, float] | None = None, **joints) -> FrameRecord:
    pts = dict(BASE, **joints)
    hand = HandFrame(landmarks=[Landmark(name="right_index_tip", x=tip[0], y=tip[1], c=1.0)], score=1.0) if tip else None
    return FrameRecord(frame=i, time_s=i / FPS, pose=[Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in pts.items()], right_hand=hand)


def test_sustained_poses_are_detected() -> None:
    heart = [_record(i, left_wrist=(0.51, 0.4), right_wrist=(0.49, 0.4)) for i in range(20)]
    assert [e.name for e in G.heart_hands_events(heart, FPS, W, H)] == ["heart_hands"]
    up = [_record(i, left_wrist=(0.6, 0.05), right_wrist=(0.4, 0.05)) for i in range(15)]
    assert len(G.arms_up_events(up, FPS, W, H)) == 1
    open_ = [_record(i, left_wrist=(0.95, 0.3), right_wrist=(0.05, 0.3)) for i in range(15)]
    assert len(G.arms_open_events(open_, FPS, W, H)) == 1
    ear = [_record(i, tip=(0.435, 0.2)) for i in range(15)]
    assert [e.kind for e in G.hand_ear_events(ear, FPS, W, H)] == ["right"]
    eyes = [_record(i, tip=(0.5, 0.19)) for i in range(15)]
    assert len(G.cover_eyes_events(eyes, FPS, W, H)) == 1
    # Un instante no es un gesto sostenido.
    assert G.arms_up_events(up[:4] + [_record(i) for i in range(4, 15)], FPS, W, H) == []


def test_spin_is_a_quick_front_back_front() -> None:
    def facing(i: int) -> FrameRecord:
        back = 10 <= i < 25
        return _record(i, left_shoulder=(0.42, 0.3) if back else (0.58, 0.3), right_shoulder=(0.58, 0.3) if back else (0.42, 0.3))
    assert len(G.spin_body_events([facing(i) for i in range(40)], FPS, W, H)) == 1
    slow = [_record(i, left_shoulder=(0.42, 0.3), right_shoulder=(0.58, 0.3)) if 10 <= i < 70 else _record(i) for i in range(80)]
    assert G.spin_body_events(slow, FPS, W, H) == []  # de espaldas 2 s: se dio vuelta, no giró


def _draws(kind: str, event: MotionEvent, record: FrameRecord, frames: int = 10) -> float:
    effect = Effect(id=kind, type=kind, target=EffectTarget(kind="joint", id="body"), triggers=[{"event": event.name, "hold": 20, "fade_in": 0, "fade_out": 0}])
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[event])
    layer = None
    for i in range(frames):
        layer = engine.render_frame(record.model_copy(update={"frame": i}), i, W, H, 60)[0][2]
    return float(layer[..., 3].max())


def test_gesture_effects_draw() -> None:
    cases = {
        "heart_fx": (MotionEvent(name="heart_hands", target="person_0", start_frame=0, end_frame=20, confidence=1.0, kind="both"), _record(0, left_wrist=(0.51, 0.4), right_wrist=(0.49, 0.4))),
        "point_fx": (MotionEvent(name="point", target="person_0:right", start_frame=0, end_frame=20, confidence=1.0, kind="right"), _record(0, tip=(0.15, 0.4))),
        "confetti_fx": (MotionEvent(name="arms_up", target="person_0", start_frame=0, end_frame=20, confidence=1.0, kind="both"), _record(0)),
        "sound_waves": (MotionEvent(name="hand_ear", target="person_0:right", start_frame=0, end_frame=20, confidence=1.0, kind="right", position=(0.44, 0.2)), _record(0)),
        "whirl_fx": (MotionEvent(name="spin_body", target="person_0", start_frame=0, end_frame=20, confidence=1.0), _record(0)),
    }
    for kind, (event, record) in cases.items():
        assert _draws(kind, event, record) > 0.3, kind
