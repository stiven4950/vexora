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


def test_spinning_around_the_body_opens_outward() -> None:
    from vfxglow.engine import firebend

    st: dict = {}
    pivot = np.array([0.0, 0.0])
    for i in range(30):  # la mano gira a 1,2 anchos de hombros del eje, rápido
        a = i * 0.25
        anchor = pivot + np.array([np.cos(a), np.sin(a)]) * 1.2 * SCALE
        direction, _ = flame_physics(st, "llama", anchor, SCALE, pivot=pivot)
    out = (anchor - pivot) / np.linalg.norm(anchor - pivot)
    st2: dict = {}
    for i in range(30):  # mismo recorrido sin eje: sin centrífuga
        a = i * 0.25
        plain, _ = flame_physics(st2, "llama", pivot + np.array([np.cos(a), np.sin(a)]) * 1.2 * SCALE, SCALE)
    assert float(np.dot(direction, out)) > float(np.dot(plain, out)) + 0.05
    assert firebend.CENTRIFUGAL > 0


def test_close_flames_lean_toward_each_other() -> None:
    st: dict = {}
    for _ in range(20):
        direction, _ = flame_physics(st, "llama", np.array([0.0, 0.0]), SCALE, partner=np.array([50.0, 0.0]))
    assert direction[0] > 0.1  # hacia la otra llama (a la derecha)


def test_ambient_wind_bends_still_flames() -> None:
    st: dict = {}
    for _ in range(20):
        direction, _ = flame_physics(st, "llama", np.array([0.0, 0.0]), SCALE, wind=np.array([-0.8, 0.0]))
    assert direction[0] < -0.3


def _flame_mask(parts, size=(400, 300)):
    import cv2

    from vfxglow.engine.firebend import ribbon

    mask = np.zeros(size, np.uint8)
    for spine, widths in parts:
        poly = ribbon(spine, widths, 0, 3.0)(1.0)
        cv2.fillPoly(mask, [np.round(poly).astype(np.int32)], 1)
    return mask


def test_hand_flame_is_a_drop_not_a_needle_or_a_plant() -> None:
    import cv2

    from vfxglow.engine.firebend import flame_parts

    for seed in (0.3, 2.0, 3.7, 5.1):
        parts = flame_parts(np.array([150.0, 330.0]), np.array([0.0, -1.0]), 115.0, 25.0, 10, seed)
        mask = _flame_mask(parts)
        ys, xs = np.nonzero(mask)
        ratio = (ys.max() - ys.min()) / max(xs.max() - xs.min(), 1)
        assert 1.8 < ratio < 3.8, ratio  # gota (antes, 12:1)
        count, _ = cv2.connectedComponents(mask)
        assert count - 1 <= 2  # el cuerpo (y a lo sumo el trocito suelto): no hojas separadas


def test_fast_hand_turns_the_flame_into_a_swoosh() -> None:
    from vfxglow.engine.firebend import flame_parts

    base = np.array([200.0, 300.0])
    trail = [base + np.array([-12.0 * k, 0.0]) for k in range(7, -1, -1)]  # venía de la izquierda
    still = flame_parts(base, np.array([0.0, -1.0]), 115.0, 25.0, 0, 1.0)[0][0]
    fast = flame_parts(base, np.array([0.0, -1.0]), 115.0, 25.0, 0, 1.0, trail, 1.0)[0][0]
    assert abs(still[-1][0] - base[0]) < 30  # quieta: sube
    assert fast[-1][0] < base[0] - 60  # rápida: la punta queda tendida sobre el camino (atrás)
    assert np.allclose(fast[0], base, atol=1.0)  # la base sigue en la mano


def test_joined_hands_light_a_single_flame() -> None:
    from types import SimpleNamespace

    from vfxglow.engine import firebend

    class Body(dict):
        prefix = "p0"

    calls = []
    original = firebend.flame_parts
    firebend.flame_parts = lambda base, *a, **k: calls.append(base.copy()) or original(base, *a, **k)
    try:
        runtime = SimpleNamespace(effect=SimpleNamespace(triggers=[]), active_frames=10, swoosh={})
        frame = (np.array([200.0, 150.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
        joined = Body(left_wrist=np.array([200.0, 250.0]), right_wrist=np.array([201.0, 251.0]))
        layer = np.zeros((400, 400, 4), np.float32)
        try:
            firebend._hand_fire(joined, frame, 100.0, 5, runtime, layer, (255, 200, 80), 1.0, None)
        except (AttributeError, KeyError, TypeError):
            pass  # el resto del dibujo (brasas, luz) depende del motor; aquí importa cuántas llamas nacen
        assert len(calls) == 1  # una sola gota entre las dos manos
        calls.clear()
        apart = Body(left_wrist=np.array([120.0, 250.0]), right_wrist=np.array([280.0, 250.0]))
        try:
            firebend._hand_fire(apart, frame, 100.0, 5, runtime, layer, (255, 200, 80), 1.0, None)
        except (AttributeError, KeyError, TypeError):
            pass
        assert len(calls) == 2  # separadas: una llama por mano
    finally:
        firebend.flame_parts = original
