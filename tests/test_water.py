"""Agua control (engine/waterbend.py): la física de la cinta y las gotas, y la pintura."""

from __future__ import annotations

import numpy as np

from vfxglow.engine import waterbend

H, W = 600, 400


def test_the_ribbon_keeps_its_volume_when_stretched() -> None:
    short = np.stack([np.linspace(100, 160, 20), np.full(20, 300.0)], axis=1)
    long = np.stack([np.linspace(100, 340, 20), np.full(20, 300.0)], axis=1)
    volume = 40.0 ** 2

    def area(pts):
        widths = waterbend.ribbon_widths(pts, volume)
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        return float(np.sum((widths[:-1] + widths[1:]) * seg))  # 2 · ancho medio · largo

    assert abs(area(long) - area(short)) / area(short) < 0.1  # el área (el agua) se conserva
    assert waterbend.ribbon_widths(long, volume).max() < waterbend.ribbon_widths(short, volume).max()  # estirada, más fina


def test_the_chain_follows_the_hand_like_a_rope() -> None:
    st: dict = {}
    for k in range(30):
        pts = waterbend.chain_step(st, np.array([100.0 + 8 * k, 300.0]), 20, 10.0, H)
    assert np.allclose(pts[-1], [100.0 + 8 * 29, 300.0])  # la cabeza va en la mano
    assert pts[0, 0] < pts[-1, 0] and pts[0, 1] > pts[-1, 1]  # la cola queda atrás y cuelga (gravedad)
    assert float(np.linalg.norm(pts[0] - pts[-1])) > 0.6 * 19 * 10.0  # extendida, no amontonada en la mano
    assert np.all(np.linalg.norm(np.diff(pts, axis=0), axis=1) <= 10.0 + 1e-6)  # no se estira más que la cuerda


def test_drops_fall_and_bounce_softly_on_the_floor() -> None:
    st = {"drops": [[np.array([200.0, 300.0]), np.array([0.0, 0.0]), 6.0, 0]]}
    ys = []
    for _ in range(25):
        drops = waterbend.step_drops(st, H, floor=400.0)
        ys.append(drops[0][0][1])
        if drops[0][0][1] >= 400.0:
            break
    assert ys[-1] == 400.0 and all(b >= a for a, b in zip(ys, ys[1:]))  # cae hasta el piso
    up = waterbend.step_drops(st, H, floor=400.0)[0][1][1]
    assert up < 0  # rebota hacia arriba...
    assert st["drops"][0][2] < 6.0 * 0.8  # ...repartida (más chica)


def test_a_stretched_tail_breaks_into_drops() -> None:
    st: dict = {}
    pts = waterbend.chain_step(st, np.array([100.0, 300.0]), 20, 30.0, H)
    for k in range(6):  # la mano sale disparada: la cola se estira
        pts = waterbend.chain_step(st, np.array([100.0 + 60 * (k + 1), 300.0]), 20, 30.0, H)
    widths = waterbend.ribbon_widths(pts, 20.0 ** 2)
    waterbend.shed_drops(st, pts, widths, H, 2.0)
    assert len(st.get("drops", [])) >= 2


def test_water_is_see_through_with_a_bright_rim() -> None:
    layer = np.zeros((H, W, 4), np.float32)
    a = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    waterbend._fill(layer, np.stack([200 + 80 * np.cos(a), 300 + 80 * np.sin(a)], axis=1), 1.0)
    waterbend.flush_water(layer, 3)
    center, rim = layer[300, 200], layer[300, 280 - 1]
    assert 0.2 < center[3] < 0.75  # el volumen deja ver el fondo
    assert rim[:3].max() > center[:3].max()  # el contorno brilla más que el centro
    refract = np.zeros((H, W, 4), np.float32)
    waterbend._refract(refract, 3, 0.012)
    assert refract[..., 3].max() > 0.5 and np.abs(refract[..., 0]).max() > 1.0  # la refracción del mismo cuadro
    assert refract[50, 50, 3] == 0.0  # fuera del agua no toca nada
