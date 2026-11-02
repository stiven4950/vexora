"""Símbolos de la cara (engine/face_symbols.py) y criaturas que acompañan a la cabeza
(engine/head_companions.py)."""

from __future__ import annotations

import numpy as np
import pytest

from test_eye_family import _frame, _ink, _runtime
from test_face_glow import _body
from vfxglow.engine.face_symbols import SYMBOLS
from vfxglow.engine.face_zone import coverage
from vfxglow.engine.head_companions import COMPANIONS


@pytest.mark.parametrize("shape", SYMBOLS + COMPANIONS)
def test_every_shape_draws_with_and_without_the_mesh(shape: str) -> None:
    for body in (_body(), _body(mesh=False)):
        runtime = _runtime(shape)
        assert max(_ink(*_frame(shape, runtime, f, body=body)) for f in range(0, 30, 3)) > 1.0


def _lit(layer: np.ndarray, box) -> float:
    x0, y0, x1, y1 = (int(v) for v in box)
    return float(layer[max(y0, 0) : y1, max(x0, 0) : x1, 3].sum())


def test_the_third_eye_opens_wider_when_the_brows_go_up() -> None:
    calm, raised = _runtime("third_eye"), _runtime("third_eye")
    rest = {"browInnerUp": 0.5}
    for f in range(30):
        a = _frame("third_eye", calm, f, rest)
        b = _frame("third_eye", raised, f, rest if f < 15 else {"browInnerUp": 0.95})
    assert _ink(*b) > _ink(*a)


def test_the_third_eye_does_not_fire_rays_when_it_appears() -> None:
    runtime = _runtime("third_eye")
    for f in range(8):
        _frame("third_eye", runtime, f, {"browInnerUp": 0.6})
    assert "rays" not in runtime.swoosh["_symbol:third_eye:0:" + _body().prefix]


def test_the_runes_reorganize_after_a_blink() -> None:
    runtime = _runtime("rune_shift")
    shut = {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}
    for f in range(20):
        _frame("rune_shift", runtime, f)
    state = runtime.swoosh["_symbol:rune_shift:0:" + _body().prefix]
    before = state["glyph"]
    _frame("rune_shift", runtime, 20, shut)
    assert state["glyph"] == before + 1


def _with_forehead():
    """La malla sintética deja el punto 10 (la frente) en el óvalo, a la altura de la mejilla: aquí va
    donde lo pone MediaPipe, arriba en la frente."""
    body = _body()
    left, right = body.points["left_iris"], body.points["right_iris"]
    body.points["forehead_top"] = (left + right) / 2 - np.array([0.0, 1.1 * float(np.linalg.norm(left - right))])
    return body


def test_the_crown_grows_with_a_smile_and_stays_above_the_eyes() -> None:
    calm, smiling = _runtime("light_crown"), _runtime("light_crown")
    body = _with_forehead()
    for f in range(20):
        a = _frame("light_crown", calm, f, body=body)
        b = _frame("light_crown", smiling, f, {"mouthSmileLeft": 0.9, "mouthSmileRight": 0.9}, body=body)
    eyes_y = min(body.points["left_iris"][1], body.points["right_iris"][1])
    assert _lit(b[0], (0, 0, 400, eyes_y)) > _lit(a[0], (0, 0, 400, eyes_y))
    rows = np.nonzero(b[0][..., 3].max(axis=1) > 0.05)[0]
    assert rows.max() < eyes_y  # nada de la corona baja a los ojos


def test_butterflies_leave_the_eyes_and_fly_above_them() -> None:
    runtime = _runtime("eye_butterflies")
    for f in range(40):
        layer, _ = _frame("eye_butterflies", runtime, f)
    eyes_y = min(_body().points["left_iris"][1], _body().points["right_iris"][1])
    rows = np.nonzero(layer[..., 3].max(axis=1) > 0.05)[0]
    assert rows.max() < eyes_y + 10  # por arriba: nunca sobre la boca o el mentón


def test_a_blink_releases_another_butterfly() -> None:
    runtime = _runtime("eye_butterflies")
    shut = {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}
    for f, expressions in enumerate([{}] * 20 + [shut, {}]):
        _frame("eye_butterflies", runtime, f, expressions)
    born = runtime.swoosh["_companion:eye_butterflies:0:" + _body().prefix]["born"]
    assert born[-1][0] == 20


def test_the_snake_stays_outside_the_face_and_comes_closer_with_the_mouth_open() -> None:
    body = _body()
    center = (body.points["left_iris"] + body.points["right_iris"]) / 2
    unit = float(np.linalg.norm(body.points["left_iris"] - body.points["right_iris"]))

    def closest(expressions) -> float:
        runtime = _runtime("holo_snake")
        for f in range(25):
            layer, _ = _frame("holo_snake", runtime, f, expressions)
        ys, xs = np.nonzero(layer[..., 3] > 0.2)
        return float(np.min(np.hypot(xs - center[0], ys - center[1]))) / unit

    shut_mouth, open_mouth = closest({}), closest({"jawOpen": 0.8})
    assert shut_mouth > 1.15
    assert open_mouth < shut_mouth


def test_symbols_and_companions_have_their_coverage() -> None:
    def cov(shape: str) -> str:
        return coverage({"type": "adornment", "style": {"shapes": [shape]}})

    assert cov("third_eye") == "low"
    assert cov("rune_shift") == "medium"
    assert {cov(s) for s in ("light_crown", "eye_butterflies", "holo_snake")} == {"peripheral"}
