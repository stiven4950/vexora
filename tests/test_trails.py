"""Manchas que siguen al movimiento: el pie que barre el piso y el objeto lanzado."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import FrameRecord, Landmark, Prop
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine

W, H = 400, 800


def _record(i: int, foot_x: float, foot_y: float, prop_x: float | None = None) -> FrameRecord:
    pts = {"left_shoulder": (0.42, 0.3), "right_shoulder": (0.58, 0.3), "left_hip": (0.44, 0.55), "right_hip": (0.56, 0.55),
           "left_ankle": (foot_x, foot_y - 0.01), "left_heel": (foot_x, foot_y), "left_foot_index": (foot_x + 0.02, foot_y),
           "right_ankle": (0.56, 0.89), "right_heel": (0.56, 0.9), "right_foot_index": (0.58, 0.9)}
    prop = None
    if prop_x is not None:
        prop = Prop(label="cap", contour=[(prop_x, 0.2), (prop_x + 0.05, 0.2), (prop_x + 0.05, 0.23), (prop_x, 0.23)], box=(prop_x, 0.2, prop_x + 0.05, 0.23), state="air")
    return FrameRecord(frame=i, time_s=i / 30, pose=[Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in pts.items()], prop=prop)


def _alpha(effect: Effect, records: list[FrameRecord]) -> list[float]:
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[])
    return [float(engine.render_frame(r, r.frame, W, H, 60)[0][2][..., 3].max()) for r in records]


def test_foot_paints_only_while_sliding_on_the_floor() -> None:
    effect = Effect(id="f", type="foot_paint", target=EffectTarget(kind="joint", id="legs"), style=EffectStyle(size=0.3, trail_frames=10))
    sliding = [_record(i, 0.3 + 0.02 * i, 0.9) for i in range(20)]
    lifted = [_record(i, 0.3 + 0.02 * i, 0.6) if i > 2 else _record(i, 0.3, 0.9) for i in range(20)]
    still = [_record(i, 0.3, 0.9) for i in range(20)]
    assert _alpha(effect, sliding)[-1] > 0.5
    assert _alpha(effect, lifted)[-1] == 0.0
    assert _alpha(effect, still)[-1] == 0.0


def test_prop_swoosh_follows_a_fast_object() -> None:
    effect = Effect(id="s", type="prop_swoosh", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(min_speed=0.09, size=0.9, trail_frames=8))
    fast = [_record(i, 0.3, 0.9, 0.1 + 0.05 * i) for i in range(12)]
    slow = [_record(i, 0.3, 0.9, 0.3 + 0.001 * i) for i in range(12)]
    assert _alpha(effect, fast)[-1] > 0.5
    assert _alpha(effect, slow)[-1] == 0.0
