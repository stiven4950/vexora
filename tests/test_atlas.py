"""Capas por pista (composite/atlas.py): distribución del mosaico, codificación y partes del compositor."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.composite.atlas import REST, MAX_LAYER_TRACKS, decode_energy, encode_energy, fold, plan_layout
from vfxglow.composite.color import linear_to_srgb, srgb_to_linear
from vfxglow.composite.composite import composite_frame
from vfxglow.director.schema import Effect, Grade


@pytest.mark.parametrize("size", [(720, 1280), (1920, 1080)])
def test_layout_fits_in_the_decoder_limit_without_overlaps(size: tuple[int, int]) -> None:
    keys = [f"t{i}" for i in range(MAX_LAYER_TRACKS)]
    layout = plan_layout(*size, 30.0, 300, keys, {k: True for k in keys} | {REST: True}, has_rest=True)
    assert layout.plate == (0, 0, 2 * layout.tile[0], 2 * layout.tile[1])
    assert layout.width <= 4096 and layout.height <= 4096
    tw, th = layout.tile
    boxes = [(0, 0, 2 * tw, 2 * th)]
    for ref in [*layout.tracks, layout.rest]:
        assert ref is not None and ref.a is not None
        boxes += [(*ref.c, tw, th), (*ref.a, tw, th)]
    assert len(layout.tracks) == MAX_LAYER_TRACKS
    for x, y, w, h in boxes:
        assert x >= 0 and y >= 0 and x + w <= layout.width and y + h <= layout.height
    for i, (x1, y1, w1, h1) in enumerate(boxes):
        for x2, y2, w2, h2 in boxes[i + 1 :]:
            assert x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1


def test_energy_roundtrip_keeps_a_small_relative_error() -> None:
    values = np.geomspace(0.001, 8.0, 200).astype(np.float32)
    back = decode_energy(encode_energy(np.stack([values] * 3, axis=-1)[None]))[0, :, 0]
    # 8 bits: lo muy oscuro pierde precisión absoluta, no relativa grande; se mide donde importa.
    relative = np.abs(back - values) / values
    assert relative[values >= 0.05].max() < 0.2
    assert np.abs(back - values).max() < 0.5


def _effect(effect_id: str, blend: str, **render) -> Effect:
    return Effect.model_validate({"id": effect_id, "type": "particles", "target": {"kind": "joint", "id": "nose"}, "render": {"blend": blend, **render}})


def _scene() -> tuple[np.ndarray, list[tuple[Effect, np.ndarray]]]:
    rng = np.random.default_rng(7)
    plate = rng.integers(20, 235, size=(12, 16, 3), dtype=np.uint8)
    layers = []
    for effect in (_effect("a", "add"), _effect("b", "over"), _effect("c", "tint"), _effect("d", "multiply"), _effect("e", "add"), _effect("g", "multiply", group="grade")):
        layer = rng.random((12, 16, 4)).astype(np.float32) * 0.8 + 0.2  # cubre todo el cuadro
        layers.append((effect, layer))
    return plate, layers


def _apply(plate: np.ndarray, parts) -> np.ndarray:
    acc = srgb_to_linear(plate[..., ::-1].astype(np.float32) / 255.0)
    for _id, a, c in parts:
        acc = acc * (1.0 - (0.0 if a is None else a[..., None] if a.ndim == 2 else a)) + c
    return np.round(linear_to_srgb(acc) * 255.0).astype(np.int16)


def test_parts_rebuild_the_composite() -> None:
    plate, layers = _scene()
    parts: list = []
    out = composite_frame(plate, layers, Grade(), parts=parts)
    assert {p[0] for p in parts} == {"a", "b", "c", "d", "e", "g"}
    assert np.abs(_apply(plate, parts) - out.astype(np.int16)).max() <= 1


def test_fold_equals_applying_parts_in_sequence() -> None:
    plate, layers = _scene()
    parts: list = []
    composite_frame(plate, layers, Grade(), parts=parts)
    key_of = {p[0]: "x" for p in parts}
    folded = fold(parts, key_of)
    assert set(folded) == {"x"}
    a, c = folded["x"]
    base = srgb_to_linear(plate[..., ::-1].astype(np.float32) / 255.0)
    one = base * (1.0 - (0.0 if a is None else a[..., None] if a.ndim == 2 else a)) + c
    seq = base
    for _id, pa, pc in parts:
        seq = seq * (1.0 - (0.0 if pa is None else pa[..., None] if pa.ndim == 2 else pa)) + pc
    assert np.abs(one - seq).max() < 1e-3 * max(1.0, float(seq.max()))
    # Dos pistas distintas: cada una conserva lo suyo.
    split = fold(parts, {p[0]: ("x" if i % 2 else "y") for i, p in enumerate(parts)})
    assert set(split) == {"x", "y"}
