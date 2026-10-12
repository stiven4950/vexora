"""Cierre (docs/criterio_de_analisis.md, P10): en el último tramo del video todo lo dibujado se
disipa en estrellas diminutas, en el lugar donde estaba (video_33 seg. 29: el sombrero y el
cinturón se vuelven estrellas), hasta que queda la persona sola.

El motor apaga los demás efectos en el primer FADE del cierre; closing_stars toma la foto de lo
que había encendido al empezar el cierre, siembra estrellas ahí (con su color) y las hace
titilar, subir un poco y apagarse. `style.size` = duración del cierre en segundos.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.burst import sparkle
from vfxglow.engine.raster import empty_layer, stroke_batch
from vfxglow.engine.swoosh import neon_layers

STARS = 70
# Fracción del cierre en que se apagan los demás efectos.
FADE = 0.4


def closing_window(effect, fps: float, frame_count: int) -> tuple[int, int]:
    length = max(int(round(effect.style.size * fps)), 1)
    return max(frame_count - length, 0), length


def other_gain(frame_index: int, start: int, length: int) -> float:
    if frame_index < start:
        return 1.0
    return float(max(0.0, 1.0 - (frame_index - start) / (length * FADE)))


def draw_closing(runtime, layers: list[np.ndarray], frame_index: int, start: int, length: int, width: int, height: int) -> np.ndarray:
    layer = empty_layer(height, width)
    if frame_index < start:
        runtime.bits = []
        return layer
    if frame_index == start or not runtime.bits:
        _seed(runtime, layers, height, width)
    if not runtime.bits:
        return layer
    progress = (frame_index - start) / max(length, 1)
    fade = (1.0 - progress) ** 0.7
    style = runtime.effect.style
    strokes = []
    for position, color, phase, size in runtime.bits:
        twinkle = 0.5 + 0.5 * np.sin(frame_index * 0.7 + phase)
        center = position - np.array([0.0, size * 3.0 * progress])
        star = sparkle(center, size * (0.6 + 0.6 * twinkle) * (1.0 - 0.5 * progress))
        strokes += neon_layers(star, color, 1.2, fade * (0.4 + 0.6 * twinkle))
    stroke_batch(layer, strokes, style.hdr_gain)
    return layer


def _seed(runtime, layers: list[np.ndarray], height: int, width: int) -> None:
    """Estrellas donde había efectos encendidos (más donde brillaba más), con su color."""
    if not layers:
        runtime.bits = []
        return
    alpha = np.max(np.stack([l[..., 3] for l in layers]), axis=0)
    energy = np.sum(np.stack([l[..., :3] for l in layers]), axis=0)
    ys, xs = np.nonzero(alpha > 0.3)
    if xs.size == 0:
        runtime.bits = []
        return
    rng = runtime.rng
    weights = alpha[ys, xs] / alpha[ys, xs].sum()
    picks = rng.choice(xs.size, size=min(STARS, xs.size), replace=False, p=weights)
    bits = []
    for k in picks:
        color = energy[ys[k], xs[k]]
        color = color / max(float(color.max()), 1e-6)
        bits.append((np.array([float(xs[k]), float(ys[k])]), color.astype(np.float32), float(rng.uniform(0, 6.28)), float(rng.uniform(0.006, 0.014) * height)))
    runtime.bits = bits
