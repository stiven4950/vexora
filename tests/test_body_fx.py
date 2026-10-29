"""Efectos de cuerpo entero: chaqueta metalera, rayos X, alas, rastro fantasma y huellas."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.gestures import step_events
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine

W, H, FPS = 400, 800, 30.0
BASE = {"nose": (0.5, 0.2), "left_ear": (0.53, 0.2), "right_ear": (0.47, 0.2), "left_shoulder": (0.58, 0.3), "right_shoulder": (0.42, 0.3),
        "left_elbow": (0.75, 0.3), "right_elbow": (0.25, 0.3), "left_wrist": (0.92, 0.3), "right_wrist": (0.08, 0.3),
        "left_hip": (0.56, 0.55), "right_hip": (0.44, 0.55), "left_knee": (0.56, 0.72), "right_knee": (0.44, 0.72),
        "left_ankle": (0.56, 0.9), "right_ankle": (0.44, 0.9), "left_heel": (0.56, 0.91), "right_heel": (0.44, 0.91)}


def _record(i: int, x_shift: float = 0.0, **joints) -> FrameRecord:
    pts = dict(BASE, **joints)
    contour = [(0.5 + x_shift + 0.12 * np.cos(t), 0.55 + 0.4 * np.sin(t)) for t in np.linspace(0, 2 * np.pi, 30, endpoint=False)]
    return FrameRecord(frame=i, time_s=i / FPS, pose=[Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in pts.items()], body_contour=contour)


def _alpha(effect: Effect, records: list[FrameRecord], events: list[MotionEvent] | None = None) -> np.ndarray:
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=events or [])
    layer = None
    for r in records:
        layer = engine.render_frame(r, r.frame, W, H, 90)[0][2]
    return layer[..., 3]


def test_body_costumes_draw_on_the_body() -> None:
    for kind, style in (("xray", EffectStyle()), ("wings", EffectStyle()), ("adornment", EffectStyle(shapes=["metal_jacket"]))):
        alpha = _alpha(Effect(id=kind, type=kind, target=EffectTarget(kind="joint", id="body"), style=style), [_record(i) for i in range(8)])
        assert alpha.max() > 0.5, kind
    wings = _alpha(Effect(id="w", type="wings", target=EffectTarget(kind="joint", id="body")), [_record(i) for i in range(8)])
    _, xs = np.nonzero(wings > 0.3)
    assert xs.min() < 0.15 * W and xs.max() > 0.85 * W  # siguen los brazos abiertos


def test_ghost_trail_draws_where_the_body_was() -> None:
    moving = [_record(i, x_shift=-0.3 + 0.03 * i) for i in range(12)]
    alpha = _alpha(Effect(id="g", type="ghost_trail", target=EffectTarget(kind="joint", id="body")), moving)
    _, xs = np.nonzero(alpha > 0.2)
    assert xs.size and xs.min() < (0.5 - 0.3 + 0.03 * 11 - 0.12) * W  # copias atrás de la silueta actual


def test_steps_leave_footprints() -> None:
    heights = [0.91] * 5 + [0.88, 0.86, 0.86, 0.88, 0.9, 0.91] + [0.91] * 10
    records = [_record(i, left_heel=(0.56, y), left_ankle=(0.56, y - 0.01)) for i, y in enumerate(heights)]
    steps = step_events(records, FPS, W, H)
    assert len(steps) == 1 and steps[0].kind == "left"
    alpha = _alpha(Effect(id="f", type="footprints", target=EffectTarget(kind="joint", id="legs")), records, steps)
    ys, _ = np.nonzero(alpha > 0.3)
    assert ys.size and ys.mean() > 0.8 * H


def test_a_step_with_the_arms_down_and_calm_is_walking() -> None:
    from vfxglow.analysis.gestures import walk_events

    heights = [0.91] * 15 + [0.88, 0.86, 0.86, 0.88, 0.9, 0.91] + [0.91] * 10
    arms_down = {"left_elbow": (0.6, 0.42), "right_elbow": (0.4, 0.42), "left_wrist": (0.6, 0.58), "right_wrist": (0.4, 0.58)}
    walking = [_record(i, left_heel=(0.56, y), left_ankle=(0.56, y - 0.01), **arms_down) for i, y in enumerate(heights)]
    assert [e.name for e in walk_events(walking, FPS, W, H)] == ["walk"]
    # El mismo paso con los brazos arriba (bailando) no es caminar.
    dancing = [_record(i, left_heel=(0.56, y), left_ankle=(0.56, y - 0.01)) for i, y in enumerate(heights)]
    assert step_events(dancing, FPS, W, H) and walk_events(dancing, FPS, W, H) == []
