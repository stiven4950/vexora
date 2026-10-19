"""Física de la llama: viento relativo, inercia con resorte, estiramiento y flotación."""

from __future__ import annotations

import numpy as np

from vfxglow.engine.firebend import flame_physics

SCALE = 100.0


def _run(path):
    st: dict = {}
    out = []
    for point in path:
        out.append(flame_physics(st, "llama", np.array(point, float), SCALE))
    return out


def test_still_flame_points_up() -> None:
    direction, stretch = _run([(0, 0)] * 20)[-1]
    assert direction[1] < -0.99 and abs(stretch - 1.0) < 0.05


def test_moving_right_leans_left_and_stretches() -> None:
    states = _run([(i * 12, 0) for i in range(15)])
    direction, stretch = states[-1]
    assert direction[0] < -0.3  # el aire la empuja en contra del movimiento
    assert stretch > 1.2


def test_stop_overshoots_then_settles() -> None:
    path = [(i * 12, 0) for i in range(15)] + [(14 * 12, 0)] * 40
    states = _run(path)
    after = [d[0] for d, _ in states[15:]]
    assert max(after) > 0.02  # al frenar se pasa de largo hacia el otro lado
    assert abs(after[-1]) < 0.05  # y termina vertical


def test_tracker_jump_is_ignored() -> None:
    direction, _ = _run([(0, 0)] * 10 + [(500, 0)])[-1]
    assert direction[1] < -0.95
