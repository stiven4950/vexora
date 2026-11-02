"""Familia de ojos (engine/eye_family.py): base común, reacciones, fases y variaciones."""

from __future__ import annotations

import numpy as np
import pytest

from test_face_glow import H, W, _body
from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.eye_family import EXIT_AT, EYES, KNOBS, pick_knobs

EVENT = MotionEvent(name="x", target="person_0", start_frame=0, end_frame=59, confidence=1.0)
CYAN = np.array([0, 1, 1], np.float32)


def _runtime(shape: str, variants: dict | None = None) -> EffectRuntime:
    style = EffectStyle(shapes=[shape], variants=variants or {})
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=style, triggers=[{"event": "x", "hold": 0}])
    runtime = EffectRuntime(effect, 1, 10)
    runtime.frame_shape = (H, W)
    return runtime


def _frame(shape: str, runtime, frame: int, expressions: dict | None = None, body=None) -> tuple[np.ndarray, list]:
    runtime.active_frames = frame
    runtime.expressions = expressions or {}
    layer = np.zeros((H, W, 4), np.float32)
    lines = adornment(shape, body or _body(), (body or _body()).frame(), (body or _body()).scale, frame, 1, runtime, layer, CYAN, 1.0, event=EVENT)
    return layer, lines


def _ink(layer: np.ndarray, lines: list) -> float:
    """Lo dibujado directo más el largo de las líneas devueltas (las pinta el motor)."""
    length = sum(float(np.linalg.norm(np.diff(np.asarray(c[0] if isinstance(c, tuple) else c), axis=0), axis=1).sum()) for c in lines)
    return float(layer[..., 3].sum()) + length


@pytest.mark.parametrize("shape", EYES)
def test_every_variant_draws_with_and_without_the_mesh(shape: str) -> None:
    for body in (_body(), _body(mesh=False)):
        runtime = _runtime(shape)
        drawn = max(_ink(*_frame(shape, runtime, f, body=body)) for f in range(0, 30, 3))
        assert drawn > 1.0


@pytest.mark.parametrize("shape", EYES)
def test_the_iris_lines_come_first_one_per_visible_eye(shape: str) -> None:
    """La continuidad empareja las líneas en orden: iris con iris."""
    _, lines = _frame(shape, _runtime(shape), 20)
    first, second = (np.asarray(c[0]).mean(axis=0) for c in lines[:2])
    assert first[0] < second[0]  # el derecho de la persona queda a la izquierda del cuadro


@pytest.mark.parametrize("shape", [s for s in EYES if s != "eyes_scanner"])
def test_closing_the_eyes_shrinks_what_they_draw(shape: str) -> None:
    shut = {"eyeBlinkLeft": 0.95, "eyeBlinkRight": 0.95}
    open_runtime, shut_runtime = _runtime(shape), _runtime(shape)
    for f in range(20, 30):
        opened = _frame(shape, open_runtime, f)
        closed = _frame(shape, shut_runtime, f, shut)
    iris = lambda lines: float(np.ptp(np.asarray(lines[0][0]), axis=0).max())  # noqa: E731
    assert iris(closed[1]) < iris(opened[1]) * 0.6


def test_a_wink_releases_stars_from_that_eye() -> None:
    runtime = _runtime("eyes_galaxy")
    _frame("eyes_galaxy", runtime, 20)
    wink = {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.05}
    _frame("eyes_galaxy", runtime, 21, wink)
    sparks = runtime.swoosh["_eyes:eyes_galaxy:0:" + _body().prefix]["sparks"]
    assert sparks
    left_iris = _body().points["left_iris"]
    assert np.linalg.norm(sparks[0]["at"] - left_iris) < 2.0


def test_the_fire_flares_with_a_fixed_stare() -> None:
    calm, staring = _runtime("eyes_fire"), _runtime("eyes_fire")
    moving = [{"eyeLookOutLeft": 0.5 * (f % 2), "eyeLookInRight": 0.5 * (f % 2)} for f in range(40)]
    for f in range(40):
        a = _frame("eyes_fire", calm, f, moving[f])
        b = _frame("eyes_fire", staring, f)
    assert float(b[0][..., 3].sum()) > float(a[0][..., 3].sum())


def test_the_exit_turns_the_lines_into_dust() -> None:
    runtime = _runtime("eyes_void")
    span = EVENT.end_frame - EVENT.start_frame + 1
    _, early = _frame("eyes_void", runtime, int(span * 0.5))
    _, late = _frame("eyes_void", runtime, int(span * (EXIT_AT + 0.2)))
    assert sum(len(np.asarray(c[0])) for c in late) < sum(len(np.asarray(c[0])) for c in early)


def test_the_same_seed_draws_the_same_and_knobs_vary_between_moments() -> None:
    a, b = _frame("eyes_storm", _runtime("eyes_storm"), 12), _frame("eyes_storm", _runtime("eyes_storm"), 12)
    assert np.array_equal(a[0], b[0])
    seen = {tuple(sorted(pick_knobs("eyes_storm", "p0", start, {}).items())) for start in range(0, 2000, 37)}
    assert len(seen) > 10
    for name, values in KNOBS.items():
        assert {pick_knobs("eyes_storm", "p0", s, {})[name] for s in range(0, 4000, 13)} == set(values)


def test_the_catalog_can_limit_the_knobs() -> None:
    assert {pick_knobs("eyes_fire", "p0", s, {"intensity": [1.3]})["intensity"] for s in range(200)} == {1.3}
