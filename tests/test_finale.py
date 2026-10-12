"""Pisotón con globo, adornos nuevos (cadena, cinturón, sombreros) y cierre en estrellas."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.gestures import stomp_events
from vfxglow.analysis.schema import FrameRecord, Landmark
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import ADORNMENTS
from vfxglow.engine.engine import EffectEngine

W, H, FPS = 400, 800, 30.0


def _record(i: int, foot_y: float) -> FrameRecord:
    pts = {"nose": (0.5, 0.2), "left_ear": (0.47, 0.2), "right_ear": (0.53, 0.2), "left_eye": (0.48, 0.19), "right_eye": (0.52, 0.19),
           "left_shoulder": (0.58, 0.3), "right_shoulder": (0.42, 0.3), "left_hip": (0.56, 0.55), "right_hip": (0.44, 0.55),
           "left_ankle": (0.56, foot_y - 0.01), "left_heel": (0.56, foot_y), "left_foot_index": (0.58, foot_y),
           "right_ankle": (0.44, 0.89), "right_heel": (0.44, 0.9), "right_foot_index": (0.42, 0.9)}
    return FrameRecord(frame=i, time_s=i / FPS, pose=[Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in pts.items()])


def test_stomp_needs_a_lifted_foot_that_comes_down_fast() -> None:
    heights = [0.9] * 5 + [0.9 - 0.02 * k for k in range(1, 5)] + [0.82] * 4 + [0.82 + 0.03 * k for k in range(1, 4)] + [0.9, 0.9, 0.9, 0.9, 0.9]
    events = stomp_events([_record(i, y) for i, y in enumerate(heights)], FPS, W, H)
    assert len(events) == 1 and events[0].kind == "left"
    walking = [_record(i, 0.9 - 0.01 * abs(np.sin(i * 0.5))) for i in range(40)]
    assert stomp_events(walking, FPS, W, H) == []


def test_new_adornments_draw() -> None:
    record = _record(0, 0.9)
    for shape in ("chain", "belt", "top_hat", "fedora", "party_hat"):
        assert shape in ADORNMENTS
        effect = Effect(id=shape, type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]))
        engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[])
        for frame in range(8):
            layer = engine.render_frame(record.model_copy(update={"frame": frame}), frame, W, H, 60)[0][2]
        assert layer[..., 3].max() > 0.5, shape


def test_closing_turns_effects_into_stars_and_fades_them() -> None:
    hat = Effect(id="hat", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["top_hat"]))
    closing = Effect(id="end", type="closing_stars", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(size=0.5, focus=False))
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[closing, hat]), EngineConfig(), events=[])
    total = 40
    out = {}
    for frame in range(total):
        layers = {name: layer for name, _, layer in engine.render_frame(_record(frame, 0.9), frame, W, H, total)}
        out[frame] = layers
    start = total - 15
    assert out[start - 2]["end"][..., 3].max() == 0.0  # antes del cierre, nada
    assert out[start + 2]["end"][..., 3].max() > 0.3  # estrellas donde estaba el sombrero
    assert out[start + 10]["hat"][..., 3].max() == 0.0  # el sombrero ya se apagó
    ys, _ = np.nonzero(out[start + 2]["end"][..., 3] > 0.3)
    assert ys.mean() < 0.25 * H  # las estrellas quedan arriba, donde estaba el sombrero
