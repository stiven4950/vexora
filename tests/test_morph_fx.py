"""Dibujos que se convierten en otros (engine/morph.py) y los efectos de video_52 que los usan."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.morph import chain, morph_lines
from vfxglow.engine.morph_fx import MORPH_FX

POSE = {"nose": (150, 90), "left_eye": (158, 84), "right_eye": (142, 84), "left_ear": (167, 90), "right_ear": (133, 90),
        "left_shoulder": (180, 130), "right_shoulder": (120, 130), "left_elbow": (200, 175), "right_elbow": (100, 175),
        "left_wrist": (205, 120), "right_wrist": (95, 120), "left_hip": (172, 225), "right_hip": (128, 225),
        "left_knee": (175, 275), "right_knee": (125, 275), "left_ankle": (178, 322), "right_ankle": (122, 322)}


def test_morph_goes_from_one_drawing_to_the_other() -> None:
    line = [np.array([[0.0, 0.0], [10.0, 0.0]])]
    other = [np.array([[0.0, 10.0], [10.0, 10.0]]), np.array([[0.0, 20.0], [10.0, 20.0]])]
    assert np.allclose(morph_lines(line, other, 0.0)[0], line[0])
    half = morph_lines(line, other, 0.5)
    assert len(half) == 2 and np.allclose(half[0][:, 1], 5.0)  # a mitad de camino; la línea se reparte
    lines, stage = chain([(0.0, line), (0.5, other)], 0.9)
    assert stage == 1 and np.allclose(lines[1][:, 1], 20.0)


def _items(shape: str, frames, kind: str = "right", pose: dict | None = None):
    points = {k: np.array(v, float) for k, v in (pose or POSE).items()}
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape], colors=[(0, 1, 0), (1, 0, 1)]), triggers=[{"event": "x", "hold": 10}])
    event = MotionEvent(name="x", target=f"person_0:{kind}", start_frame=0, end_frame=29, confidence=1.0, kind=kind)
    runtime = EffectRuntime(effect, 1, 10)
    out = []
    for f in frames:
        runtime.active_frames = f
        layer = np.zeros((360, 320, 4), np.float32)
        body = Body(points, None)
        out.append((adornment(shape, body, body.frame(), 60.0, f, 1, runtime, layer, np.array([0, 1, 0], np.float32), 1.0, event=event), layer))
    return out


@pytest.mark.parametrize("shape", MORPH_FX)
def test_every_morph_effect_draws(shape: str) -> None:
    assert any(items or layer[..., 3].max() > 0.3 for items, layer in _items(shape, range(0, 36, 3)))


def test_horns_end_as_x_eyes_of_the_other_color() -> None:
    items, _ = _items("horns_morph", [38])[0]
    assert items and all(isinstance(item, tuple) for item in items)
    assert np.allclose(items[0][1], (1, 0, 1))  # cambió al segundo color
    curve = items[0][0]
    assert abs(curve[:, 1].mean() - 84) < 10  # sobre los ojos


def test_swords_come_out_only_when_the_hands_reach_them() -> None:
    low = {**POSE, "left_wrist": (205, 215), "right_wrist": (95, 215)}
    sheathed = _items("samurai_swords", range(0, 10), pose=low)[-1][0]
    up = {**POSE, "left_wrist": (172, 98), "right_wrist": (128, 98), "left_elbow": (195, 120), "right_elbow": (105, 120)}
    drawn = _items("samurai_swords", range(0, 10), pose=up)[-1][0]
    assert sum(len(line) == 2 for line in sheathed) == 4  # dos empuñaduras con su guarda, en la espalda
    assert any(len(line) == 4 for line in drawn)  # con las manos junto a la cabeza, salen las hojas
