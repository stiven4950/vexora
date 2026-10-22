"""Blend `refract`: la capa dobla el plano de detrás sin tocar fuera de la máscara."""

from __future__ import annotations

import numpy as np

from vfxglow.composite.composite import composite_frame
from vfxglow.director.schema import Effect, EffectRender, EffectTarget, Grade

H, W = 40, 60


def _plate() -> np.ndarray:
    plate = np.zeros((H, W, 3), dtype=np.uint8)
    plate[:, ::2] = 200  # franjas verticales de 1 px
    plate[:, 1::4] = 90
    return plate


def _effect() -> Effect:
    return Effect(
        id="water",
        type="distortion",
        target=EffectTarget(kind="mask", id="person"),
        render=EffectRender(blend="refract"),
    )


def _layer(dx: float, alpha: np.ndarray) -> np.ndarray:
    layer = np.zeros((H, W, 4), dtype=np.float32)
    layer[..., 0] = dx
    layer[..., 3] = alpha
    return layer


def test_refract_shifts_inside_and_keeps_outside() -> None:
    plate, grade = _plate(), Grade()
    mask = np.zeros((H, W), dtype=np.float32)
    mask[10:30, 20:40] = 1.0
    base = composite_frame(plate, [], grade)
    out = composite_frame(plate, [(_effect(), _layer(3.0, mask))], grade)
    outside = mask == 0
    assert np.array_equal(out[outside], base[outside])
    row = 20
    assert np.array_equal(out[row, 22:36], base[row, 25:39])


def test_refract_zero_alpha_is_identity() -> None:
    plate, grade = _plate(), Grade()
    base = composite_frame(plate, [], grade)
    out = composite_frame(plate, [(_effect(), _layer(3.0, np.zeros((H, W), dtype=np.float32)))], grade)
    assert np.array_equal(out, base)
