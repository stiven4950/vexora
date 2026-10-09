"""Objeto protagonista (la gorra de video_33): su contorno exacto en neón.

- prop_outline: contorno de SAM 2 con núcleo blanco y halo de color, y relleno de tinte opcional
  (`style.fill`), como la gorra verde o azul de la referencia. Disparado por un evento, se pinta
  en el tramo del evento; sin trigger, en cada fotograma en que se ve el objeto.

Formas (`style.shapes`): `double` añade un segundo contorno algo más grande; `no_outline` deja
solo el relleno (para el modo tint); `worn` lo pinta también en la cabeza (puesto o
acomodándolo; por defecto no: la gorra puesta deja de ser protagonista).
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import neon_layers

# Puntos del contorno remuestreado y suavizado (en puntos) para que no se lea dentado.
RESAMPLE = 120
SMOOTH = 2.0
SHAPES = ("outline", "double", "no_outline", "worn")


def prop_polygon(track: FrameRecord | None, width: int, height: int) -> np.ndarray | None:
    if track is None or track.prop is None or len(track.prop.contour) < 3:
        return None
    return _smooth(np.array(track.prop.contour, dtype=np.float64) * [width, height])


def _smooth(polygon: np.ndarray) -> np.ndarray:
    """Remuestreo por longitud de arco y suavizado circular."""
    closed = np.vstack([polygon, polygon[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    if arc[-1] <= 1e-6:
        return polygon
    t = np.linspace(0.0, arc[-1], RESAMPLE, endpoint=False)
    pts = np.stack([np.interp(t, arc, closed[:, 0]), np.interp(t, arc, closed[:, 1])], axis=1)
    radius = int(SMOOTH * 3)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / SMOOTH) ** 2)
    kernel /= kernel.sum()
    padded = np.vstack([pts[-radius:], pts, pts[:radius]])
    return np.stack([np.convolve(padded[:, axis], kernel, mode="valid") for axis in (0, 1)], axis=1)


def draw_prop_outline(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    style = runtime.effect.style
    if envelope <= 0 or track is None or track.prop is None:
        return
    if style.people and track.prop.person not in style.people:
        return
    if track.prop.state in ("worn", "fitting") and "worn" not in style.shapes:
        return
    width = layer.shape[1]
    polygon = prop_polygon(track, width, height)
    if polygon is None:
        return
    size = float(np.sqrt(max(np.ptp(polygon[:, 0]) * np.ptp(polygon[:, 1]), 1.0)))
    color = np.asarray(style.colors[0], dtype=np.float32)
    if style.fill > 0:
        fill_polygon(layer, polygon, color, style.fill * envelope, 0.9, feather=3.0)
    if "no_outline" in style.shapes:
        return
    boil = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:prop:{frame_index // max(style.boil_frames, 1)}".encode()) & 0xFFFFFFFF)
    line = max(1.5, style.thickness * size)
    strokes = []
    wobble = polygon + boil.normal(0, size * 0.006, polygon.shape)
    strokes += neon_layers(np.vstack([wobble, wobble[:1]]), color, line, envelope)
    if "double" in style.shapes:
        center = polygon.mean(axis=0)
        outer = center + (polygon - center) * 1.15
        second = np.asarray(style.colors[1 % len(style.colors)], dtype=np.float32)
        strokes += neon_layers(np.vstack([outer, outer[:1]]), second, line * 0.8, envelope * 0.7)
    stroke_batch(layer, strokes, style.hdr_gain)
