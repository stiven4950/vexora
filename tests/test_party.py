"""Fiesta: frenesí → discoteca, golpes de música → pulso de la silueta y ecualizador."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.attention import frenzy_events
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine

W, H, FPS = 400, 800, 30.0
BASE = {"left_shoulder": (0.42, 0.3), "right_shoulder": (0.58, 0.3), "left_hip": (0.44, 0.55), "right_hip": (0.56, 0.55),
        "left_elbow": (0.36, 0.4), "right_elbow": (0.64, 0.4), "left_wrist": (0.34, 0.5), "right_wrist": (0.66, 0.5),
        "left_knee": (0.45, 0.7), "right_knee": (0.55, 0.7), "left_ankle": (0.45, 0.9), "right_ankle": (0.55, 0.9),
        "left_heel": (0.45, 0.91), "right_heel": (0.55, 0.91)}
MOVING = ("left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_knee", "right_knee", "left_ankle", "right_ankle")


def _record(i: int, amount: float) -> FrameRecord:
    pose = []
    for name, (x, y) in BASE.items():
        wobble = amount * np.sin(i * 1.3 + len(name)) if name in MOVING else 0.0
        pose.append(Landmark(name=name, x=x + wobble, y=y, c=0.95))
    contour = [(0.5 + 0.15 * np.cos(t), 0.55 + 0.4 * np.sin(t)) for t in np.linspace(0, 2 * np.pi, 40, endpoint=False)]
    return FrameRecord(frame=i, time_s=i / FPS, pose=pose, body_contour=contour)


def test_frenzy_when_the_whole_body_moves_far_more_than_usual() -> None:
    frames = [_record(i, 0.03 if 60 <= i < 90 else 0.005) for i in range(150)]
    events = frenzy_events(frames, FPS, W, H)
    assert len(events) == 1 and 55 <= events[0].start_frame <= 70


def _render(effect: Effect, events: list[MotionEvent], frames: int = 12) -> np.ndarray:
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect], extra_events=[e for e in events if e.name == "beat"]), EngineConfig(), events=[e for e in events if e.name != "beat"])
    layer = None
    for i in range(frames):
        layer = engine.render_frame(_record(i, 0.01), i, W, H, 60)[0][2]
    return layer


def test_disco_shoots_sparks_around_the_body() -> None:
    effect = Effect(id="d", type="disco_fx", target=EffectTarget(kind="joint", id="body"), triggers=[{"event": "frenzy", "hold": 20, "fade_in": 0}])
    layer = _render(effect, [MotionEvent(name="frenzy", target="person_0", start_frame=0, end_frame=30, confidence=1.0)])
    ys, xs = np.nonzero(layer[..., 3] > 0.3)
    assert xs.size and (xs.min() < 0.3 * W or xs.max() > 0.7 * W)


def test_beat_pulse_and_equalizer_follow_the_music() -> None:
    beats = [MotionEvent(name="beat", target="music", start_frame=f, end_frame=f, confidence=1.0) for f in (2, 6, 10)]
    pulse = Effect(id="p", type="beat_pulse", target=EffectTarget(kind="joint", id="body"), triggers=[{"event": "beat", "hold": 6, "fade_in": 0, "fade_out": 6}])
    assert _render(pulse, beats, frames=11)[..., 3].max() > 0.3
    eq = Effect(id="e", type="equalizer", target=EffectTarget(kind="joint", id="body"), style=EffectStyle())
    layer = _render(eq, beats, frames=11)
    ys, _ = np.nonzero(layer[..., 3] > 0.3)
    assert ys.size and ys.mean() > 0.75 * H  # en el piso


def test_mirror_ball_hangs_on_top_and_rains_light() -> None:
    effect = Effect(id="b", type="mirror_ball", target=EffectTarget(kind="joint", id="body"), triggers=[{"event": "frenzy", "hold": 20, "fade_in": 0}])
    layer = _render(effect, [MotionEvent(name="frenzy", target="person_0", start_frame=0, end_frame=30, confidence=1.0)])
    top = layer[: int(0.18 * H), ..., 3].max()
    ys, _ = np.nonzero(layer[..., 3] > 0.3)
    assert top > 0.5 and ys.max() > 0.5 * H  # la bola arriba y la lluvia baja
