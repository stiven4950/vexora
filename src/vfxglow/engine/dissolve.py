"""Desintegración fluida de los dibujos (pedido del usuario: figuritas más pequeñas, con más expansión
y más fluido).

El dibujo no se apaga: se suelta en polvo de luz. Cada grano nace sobre una línea, de afuera hacia
adentro, y sale empujado por una corriente: se expande mucho más allá de la cara, se curva con un
remolino suave y sube al irse. Uno de cada tantos granos es una figurita diminuta (murciélago,
calabaza, fantasma, estrella) de línea finísima, sin el neón grueso que la volvería una mancha.

- disintegrate: el dibujo como polvo, con `k` de 0 (entero) a 1 (ya se fue).
- melt: lo mismo para un efecto con fase `u`: solo actúa en su último tramo.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.raster import splat, stroke_batch

TAU = 2.0 * np.pi
# Un grano cada tantas unidades de cara a lo largo de las líneas, y el tope por fotograma.
GRAIN_EVERY = 0.03
GRAINS_MAX = 620
# Hasta dónde llegan los granos (en unidades de cara, la distancia entre los ojos).
REACH = 4.4
LIFT = 1.3
SWIRL = 1.1
# De cada tantos granos, uno es figurita; su tamaño (unidades de cara).
FIGURE_EVERY = 7
FIGURE_SIZE = (0.03, 0.06)
GRAIN_SIZE = (0.008, 0.024)
FIGURES = ("bat", "star", "pumpkin", "star", "ghost", "star")
# En `melt`, la fracción del efecto donde empieza a soltarse.
MELT_AT = 0.76


def fine(curves: list, tint, alpha: float, layer: np.ndarray, gain: float = 1.6, width: float = 1.0) -> None:
    """Línea finísima con apenas halo: en una figura diminuta el neón grueso la vuelve una mancha."""
    strokes: list = []
    for curve in curves:
        strokes.append((curve, tint, width * 3.0, alpha * 0.3, 1.5))
        strokes.append((curve, tint, width, alpha))
    if strokes:
        stroke_batch(layer, strokes, gain)


def _sample(sources: list) -> tuple[np.ndarray, np.ndarray]:
    """Puntos repartidos a lo largo de las líneas y el color de cada uno."""
    points, tints = [], []
    for curve, tint in sources:
        curve = np.asarray(curve, dtype=np.float64)
        if len(curve) < 2:
            continue
        points.append(curve)
        tints.append(np.tile(np.asarray(tint, np.float32), (len(curve), 1)))
    if not points:
        return np.zeros((0, 2)), np.zeros((0, 3), np.float32)
    return np.vstack(points), np.vstack(tints)


def _spread(points: np.ndarray, tints: np.ndarray, unit: float) -> tuple[np.ndarray, np.ndarray]:
    """Rellena las polilíneas: un grano cada GRAIN_EVERY a lo largo de cada tramo."""
    if len(points) < 2:
        return points, tints
    gaps = np.linalg.norm(np.diff(points, axis=0), axis=1)
    near = gaps < 0.8 * unit  # el salto de una línea a la siguiente no se rellena
    counts = np.where(near, np.clip((gaps / (GRAIN_EVERY * unit)).astype(int), 1, 24), 1)
    index = np.repeat(np.arange(len(gaps)), counts)
    within = np.concatenate([np.arange(c) / c for c in counts])[:, None]
    filled = points[index] + (points[index + 1] - points[index]) * within
    return filled, tints[index]


def disintegrate(sources: list, k: float, unit: float, layer: np.ndarray, alpha: float, kernels: dict, seed: int, lines: list | None = None, gain: float = 1.6, figure=None) -> list:
    """El dibujo `sources` [(curva, color)] soltándose en polvo. Dibuja el polvo en `layer` y devuelve
    lo que queda de las líneas (`lines` si lo que se ve no son las líneas de partida). `figure(centro,
    tamaño, giro)` cambia las figuritas por otra forma (las plumas del cuervo)."""
    from vfxglow.engine.hand_props import _dashed
    from vfxglow.engine.season import object_outline

    points, tints = _spread(*_sample(sources), unit)
    if not len(points) or alpha <= 0:
        return []
    if len(points) > GRAINS_MAX:
        keep = np.linspace(0, len(points) - 1, GRAINS_MAX).astype(int)
        points, tints = points[keep], tints[keep]
    n = len(points)
    rng = np.random.default_rng(seed & 0xFFFFFFFF)
    speed, phase, turn, sized = rng.uniform(0.35, 1.0, n), rng.uniform(0, TAU, n), rng.choice([-1.0, 1.0], n), rng.uniform(0, 1, n)
    center = points.mean(axis=0)
    away = points - center
    dist = np.linalg.norm(away, axis=1)
    away = away / np.maximum(dist, 1e-6)[:, None]
    # Se suelta primero lo de afuera; cada grano vive un tramo largo de `k`.
    delay = (1.0 - dist / max(float(dist.max()), 1e-6)) * 0.34 + rng.uniform(0, 0.12, n)
    t = np.clip((k - delay) / 0.54, 0.0, 1.0)
    glide = 1.0 - (1.0 - t) ** 2.4  # sale rápido y se va frenando, sin cortes
    side = np.stack([-away[:, 1], away[:, 0]], axis=1)
    curl = np.sin(phase + t * 5.0) * turn * SWIRL * glide
    moved = points + (away * (REACH * speed * glide)[:, None] + side * curl[:, None] - np.array([[0.0, LIFT]]) * glide[:, None]) * unit
    live = (t > 0.0) & (t < 1.0)
    fades = np.sin(np.pi * np.minimum(t * 3.0, 1.0) / 2.0) * (1.0 - t) ** 0.7
    strokes: list = []
    for i in np.flatnonzero(live):
        x, y = float(moved[i, 0]), float(moved[i, 1])
        tint = tints[i] * 1.3
        a = alpha * float(fades[i])
        if i % FIGURE_EVERY == 0:
            size = (FIGURE_SIZE[0] + (FIGURE_SIZE[1] - FIGURE_SIZE[0]) * sized[i]) * unit * float(np.sin(np.pi * min(t[i] * 1.6, 1.0)) * 0.5 + 0.6)
            name = FIGURES[(i // FIGURE_EVERY) % len(FIGURES)]
            curves = figure(moved[i], size, float(t[i]) * 6.0 + i) if figure else object_outline(name, moved[i], size, age=float(t[i]) + i * 0.1, spin=float(i))
            for curve in curves:
                strokes.append((curve, tint, 3.0, a * 0.3, 1.5))
                strokes.append((curve, tint, 0.9, a))
        else:
            radius = (GRAIN_SIZE[0] + (GRAIN_SIZE[1] - GRAIN_SIZE[0]) * sized[i]) * unit + 0.5
            splat(layer, x, y, radius, tint, a, kernels)
    if strokes:
        stroke_batch(layer, strokes, gain)
    keep_part = max(1.0 - k * 1.6, 0.0)
    left = []
    if keep_part > 0.0:
        for curve, tint in lines if lines is not None else sources:
            left += [(piece, np.asarray(tint, np.float32) * (0.4 + 0.6 * keep_part)) for piece in _dashed(np.asarray(curve, dtype=np.float64), keep_part, 0.09 * unit)]
    return left


def melt(items: list, u: float, face, layer: np.ndarray, color, alpha: float, kernels: dict, seed: int, start: float = MELT_AT) -> list:
    """Un dibujo que se suelta en polvo en el último tramo de su fase. `items` son curvas o (curva, color)."""
    if u < start or not items:
        return items
    pairs = [item if isinstance(item, tuple) else (item, color) for item in items]
    k = float(np.clip((u - start) / max(1.0 - start, 1e-6), 0.0, 1.0))
    return disintegrate(pairs, k, face.unit, layer, alpha, kernels, seed)
