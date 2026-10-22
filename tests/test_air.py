"""Aire control (engine/airbend.py): corrientes translúcidas, cuchilla en medialuna y distorsión."""

from __future__ import annotations

import numpy as np

from vfxglow.engine import airbend

H, W = 600, 400


def test_a_streak_is_see_through_with_a_white_core_and_a_faint_tail() -> None:
    layer = np.zeros((H, W, 4), np.float32)
    spine = np.stack([np.linspace(60, 340, 30), np.full(30, 300.0)], axis=1)  # de la cola a la cabeza
    airbend.streak(layer, spine, 12.0, 1.0)
    airbend.flush_air(layer, 5)
    assert layer[..., 3].max() <= 0.86  # translúcida: nunca tapa del todo lo de atrás
    head, tail = layer[300, 230], layer[300, 80]
    assert head[3] > tail[3] * 2  # la cola, casi invisible
    assert head[:3].min() > 0.5 * head[:3].max()  # el núcleo tira a blanco (no azul saturado)


def test_the_slash_is_a_crescent_even_for_a_straight_strike() -> None:
    path = np.stack([np.linspace(100, 220, 8), np.full(8, 300.0)], axis=1)  # golpe recto
    blade = airbend.crescent(path, 40.0)
    chord = blade[-1] - blade[0]
    d = chord / np.linalg.norm(chord)
    rel = blade - blade[0]
    bulge = np.abs(d[0] * rel[:, 1] - d[1] * rel[:, 0]).max()  # distancia a la cuerda
    assert bulge > 0.15 * np.linalg.norm(chord)  # curvada, no una raya
    assert blade[len(blade) // 2, 1] < blade[0, 1]  # sin otra pista, se curva hacia arriba


def test_the_air_bends_the_background_only_where_it_passed() -> None:
    layer = np.zeros((H, W, 4), np.float32)
    spine = np.stack([np.linspace(60, 340, 30), np.full(30, 300.0)], axis=1)
    airbend.streak(layer, spine, 12.0, 1.0)
    airbend.flush_air(layer, 9)
    refract = np.zeros((H, W, 4), np.float32)
    airbend._refract(refract, 9, 0.006)
    assert refract[..., 3].max() > 0.3 and np.abs(refract[..., :2]).max() <= 0.006 * H + 1e-6  # poca
    assert refract[50, 50, 3] == 0.0
    later = np.zeros((H, W, 4), np.float32)
    airbend._refract(later, 10, 0.006)  # otro cuadro: no usa el aire viejo
    assert later[..., 3].max() == 0.0


def test_a_clean_tail_has_no_hooks() -> None:
    there = [(100.0 + 20 * k, 300.0) for k in range(6)]
    back = [(200.0 - 20 * k, 302.0) for k in range(1, 4)]
    tail = airbend._clean_tail(np.array(there + back))
    assert tail[:, 0].max() <= 200.0 + 1e-6 and len(tail) <= 5  # solo el tramo de vuelta
