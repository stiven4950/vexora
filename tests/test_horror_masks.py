"""Rostros de terror en neón: de la cuadrícula de referencia a la máscara viva sobre la cara."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.horror_masks import HORROR_MASKS, _warp, load_mask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def test_the_grid_cell_gives_eyes_nose_mouth_and_lines() -> None:
    from mask_from_grid import extract

    mask = extract(1)
    roles = {s["role"] for s in mask["strokes"]}
    assert {"eye_right", "eye_left", "nose", "mouth", "line"} <= roles
    assert mask["anchors"]["eye_right"][0] == pytest.approx(-0.5, abs=0.01)
    assert mask["anchors"]["eye_left"][0] == pytest.approx(0.5, abs=0.01)
    assert mask["anchors"]["mouth"][1] > mask["anchors"]["nose"][1] > 0  # la boca debajo de la nariz


def test_the_mouth_screams_and_the_eyes_blink() -> None:
    mask = load_mask("ghostface")
    mouth = next(s for s in mask["strokes"] if s["role"] == "mouth")["points"]
    closed = _warp(mouth, "mouth", mask["anchors"], {"jawOpen": 0.0})
    open_ = _warp(mouth, "mouth", mask["anchors"], {"jawOpen": 1.0})
    assert np.ptp(open_[:, 1]) > np.ptp(closed[:, 1]) * 1.5
    eye = next(s for s in mask["strokes"] if s["role"] == "eye_left")["points"]
    shut = _warp(eye, "eye_left", mask["anchors"], {"eyeBlinkLeft": 1.0})
    assert np.ptp(shut[:, 1]) < np.ptp(eye[:, 1]) * 0.3


@pytest.mark.parametrize("shape", HORROR_MASKS)
def test_every_mask_draws_on_the_face(shape: str) -> None:
    points = {"nose": np.array([200.0, 130.0]), "right_iris": np.array([180.0, 110.0]), "left_iris": np.array([220.0, 110.0]),
              "left_shoulder": np.array([250.0, 200.0]), "right_shoulder": np.array([150.0, 200.0]),
              "left_hip": np.array([240.0, 330.0]), "right_hip": np.array([160.0, 330.0])}
    body = Body(points, None)
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "x", "hold": 10}])
    event = MotionEvent(name="x", target="person_0", start_frame=0, end_frame=39, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    sizes = []
    for f in (1, 30):  # al aparecer solo partículas y algún trazo; armada, todos
        runtime.active_frames = f
        layer = np.zeros((400, 400, 4), np.float32)
        items = adornment(shape, body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        sizes.append(len(items))
        assert layer[..., 3].max() > 0 or items
    assert sizes[1] > sizes[0]
    centers = np.vstack([c for c, _ in items])
    assert abs(float(np.median(centers[:, 0])) - 200.0) < 40  # sobre la cara
