"""La composición por recuadros da los mismos bits que calcular el cuadro entero."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.composite.color import ROUND_TRIP, linear_to_srgb, plate_to_linear, srgb_to_linear
from vfxglow.composite.composite import composite_frame
from vfxglow.composite.glow import bloom
from vfxglow.director.schema import Effect, Grade
from vfxglow.engine.raster import _stamp


def _effect(effect_id: str, blend: str, **render) -> Effect:
    return Effect.model_validate({"id": effect_id, "type": "particles", "target": {"kind": "joint", "id": "nose"}, "render": {"blend": blend, **render}})


def _plate(rng: np.random.Generator) -> np.ndarray:
    return rng.integers(0, 256, (60, 80, 3), dtype=np.uint8)


def _blob(rng: np.random.Generator, x: int, y: int, gain: float = 2.0) -> np.ndarray:
    layer = np.zeros((60, 80, 4), np.float32)
    layer[y : y + 10, x : x + 14] = rng.random((10, 14, 4)).astype(np.float32) * np.array([gain, gain, gain, 1.0], np.float32)
    return layer


@pytest.mark.parametrize("blend", ["add", "screen", "multiply", "tint", "over"])
@pytest.mark.parametrize("glow", [2, 5])
def test_regions_match_the_whole_frame(blend: str, glow: int) -> None:
    rng = np.random.default_rng(7)
    plate = _plate(rng)
    layers = [(_effect("a", blend, glow_layers=glow), _blob(rng, 4, 6)), (_effect("b", "add", glow_layers=glow), _blob(rng, 50, 40))]
    # Con `parts` cada efecto se calcula sobre el cuadro entero.
    whole = composite_frame(plate, [(e, l.copy()) for e, l in layers], Grade(), parts=[])
    assert np.array_equal(composite_frame(plate, layers, Grade()), whole)


def test_refraction_matches_the_whole_frame() -> None:
    rng = np.random.default_rng(3)
    plate = _plate(rng)
    layer = np.zeros((60, 80, 4), np.float32)
    layer[20:40, 20:40, :2] = 3.0
    layer[20:40, 20:40, 3] = 0.8
    layers = [(_effect("r", "refract"), layer), (_effect("a", "add"), _blob(rng, 50, 40))]
    assert np.array_equal(composite_frame(plate, layers, Grade()), composite_frame(plate, layers, Grade(), parts=[]))


def test_a_frame_without_layers_only_passes_through_the_color_tables() -> None:
    plate = _plate(np.random.default_rng(1))
    expected = np.round(linear_to_srgb(srgb_to_linear(plate[..., ::-1].astype(np.float32) / 255.0)) * 255.0).astype(np.uint8)
    assert np.array_equal(composite_frame(plate, [], Grade()), expected)
    assert ROUND_TRIP.shape == (256, 1)


def test_the_plate_table_gives_the_same_bits_as_the_formula() -> None:
    plate = _plate(np.random.default_rng(2))
    assert np.array_equal(plate_to_linear(plate), srgb_to_linear(plate[..., ::-1].astype(np.float32) / 255.0))


def test_bloom_finds_the_same_hot_region_when_only_alpha_passes_the_threshold() -> None:
    layer = np.zeros((40, 40, 4), np.float32)
    layer[10:20, 10:20, 3] = 1.0  # solo alfa: no irradia
    assert bloom(layer, 6.0, 0.5, 1.0) is layer


def test_stamp_matches_the_interleaved_formula() -> None:
    rng = np.random.default_rng(5)
    rgba = rng.integers(0, 256, (30, 40, 4), dtype=np.uint8)
    rgba[5:10, 5:10] = 0
    base = rng.random((30, 40, 4)).astype(np.float32) * 0.5
    gain = 1.7
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    straight = np.divide(rgba[..., :3].astype(np.float32) / 255.0, np.maximum(alpha, 1e-4))
    peak = straight.max(axis=-1, keepdims=True)
    saturation = (peak - straight.min(axis=-1, keepdims=True)) / np.maximum(peak, 1e-4)
    expected = base.copy()
    expected[..., :3] += straight * (1.0 + np.float32(gain - 1.0) * saturation) * alpha
    expected[..., 3] = 1.0 - (1.0 - expected[..., 3]) * (1.0 - alpha[..., 0])
    layer = base.copy()
    _stamp(layer, rgba, gain)
    assert np.array_equal(layer, expected)
