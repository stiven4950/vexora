"""Efectos de pintura (referencia video_2, docs/referencias/video_2.md). Leen los datos de
`appearance.json` (analysis/paint.py) que el motor deja en `runtime.appearance`.

- paint_trace: la luz sigue al pincel. El contorno de la pintura recién puesta se dibuja a
  medida que aparece (cada punto según su edad), con un punto caliente y una llamita donde nace
  pintura ahora; lo que pasa de DRAW fotogramas se deshace en guiones y a los RECENT se apaga.
- paint_accents: la obra terminada. Trazos cortos sobre sus líneas pintadas, una zona a la vez
  (ojos, estrías, nariz, ojos, boca) y un color de `style.palette` por zona, cada SLOT_S.
- rising_sparks: chispas que suben con el humo desde la cabeza al empezar la escena de la obra
  (`style.size` = segundos que dura).
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.raster import splat, stroke_batch
from vfxglow.engine.swoosh import neon_layers

DRAW = 10
RECENT = 24
DASH = 6  # puntos por guion al deshacerse
SLOT_S = 0.45
ZONE_ORDER = ("eyes", "ribs", "nose", "eyes", "mouth")
MAX_LINES = 5
ACCENT_LENGTH = 0.22
WHITE = np.array([1.0, 1.0, 1.0], dtype=np.float32)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Tramos seguidos de True: (inicio, fin exclusivo)."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(np.int8), [0]])))
    return list(zip(edges[::2], edges[1::2]))


def draw_paint_trace(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    appearance = getattr(runtime, "appearance", None)
    if envelope <= 0 or appearance is None:
        return
    data = appearance.paint.get(frame_index)
    if not data:
        return
    width = layer.shape[1]
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * height * 0.05)
    strokes = []
    for stroke in data["strokes"]:
        pts = np.array(stroke, dtype=np.float64)
        if len(pts) < 3:
            continue
        xy = pts[:, :2] * [width, height]
        age = pts[:, 2]
        fresh = age < DRAW
        for a, b in _runs(fresh):
            if b - a >= 2:
                alpha = 1.0 - 0.4 * float(age[a:b].mean()) / DRAW
                strokes += neon_layers(xy[a:b], color, line, envelope * alpha)
        # Lo que ya no es nuevo se deshace en guiones y se apaga.
        fading = (age >= DRAW) & (age < RECENT)
        for a, b in _runs(fading):
            for start in range(a, b, DASH * 2):
                piece = xy[start : min(start + DASH, b)]
                if len(piece) >= 2:
                    alpha = 1.0 - (float(age[start]) - DRAW) / (RECENT - DRAW)
                    strokes += neon_layers(piece, color, line * 0.8, envelope * alpha * 0.8)
    # Línea fina: el recorrido de la punta del pincel, encendido y más fresco cerca de la punta.
    trail = data.get("trail") or []
    if len(trail) >= 3:
        pts = np.array(trail, dtype=np.float64)
        xy = pts[:, :2] * [width, height]
        bounds = np.linspace(0, len(xy) - 1, min(len(xy) - 1, 6) + 1).astype(int)
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b > a:
                alpha = 1.0 - float(pts[a:b + 1, 2].mean()) / max(len(trail), 1)
                strokes += neon_layers(xy[a:b + 1], color, line * 0.7, envelope * (0.35 + 0.65 * alpha))
    if data["tip"] is not None:
        tip = np.array(data["tip"]) * [width, height]
        flicker = 0.85 + 0.15 * np.sin(frame_index * 1.7)
        splat(layer, float(tip[0]), float(tip[1]), line * 4.0 * flicker, WHITE * 1.4, envelope, runtime.kernels)
        splat(layer, float(tip[0]), float(tip[1]), line * 9.0, color * 1.2, envelope * 0.6, runtime.kernels)
        flame = np.array([tip + [-line * 1.6, 0.0], tip + [0.0, -line * 7.0 * flicker], tip + [line * 1.6, 0.0]])
        strokes += neon_layers(flame, color, line * 0.8, envelope)
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)


def draw_paint_accents(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    appearance = getattr(runtime, "appearance", None)
    if envelope <= 0 or appearance is None or not appearance.accents:
        return
    data = appearance.accents.get(frame_index)
    if not data:
        return
    width = layer.shape[1]
    start = min(appearance.accents)
    slot_frames = max(int(SLOT_S * runtime.fps), 4)
    slot, inside = divmod(frame_index - start, slot_frames)
    zone = ZONE_ORDER[slot % len(ZONE_ORDER)]
    palette = style.palette or style.colors
    color = np.asarray(palette[slot % len(palette)], dtype=np.float32)
    u = inside / slot_frames
    grow = min(u / 0.4, 1.0)  # se dibuja en el primer 40%
    fade = min((1.0 - u) / 0.25, 1.0)  # se apaga en el último 25%
    lines = [line for line in data["lines"] if line["zone"] == zone]
    lines = sorted(lines, key=lambda line: -len(line["points"]))[:MAX_LINES]
    width_px = max(1.5, style.thickness * height * 0.05)
    strokes = []
    for line in lines:
        pts = np.array(line["points"], dtype=np.float64) * [width, height]
        # Medio contorno: un trazo (arco, raya) y no un anillo cerrado; y corto, como las marcas
        # de la referencia: como mucho ACCENT_LENGTH del alto de la cabeza, del centro del trazo.
        half = pts[: max(len(pts) // 2, 2)]
        seg = np.linalg.norm(np.diff(half, axis=0), axis=1)
        limit = ACCENT_LENGTH * (data["head"][3] - data["head"][1]) * height
        if seg.sum() > limit and len(half) > 3:
            arc = np.concatenate([[0.0], np.cumsum(seg)])
            middle = arc[-1] / 2
            keep = (arc >= middle - limit / 2) & (arc <= middle + limit / 2)
            half = half[keep] if keep.sum() >= 2 else half
        shown = half[: max(int(len(half) * grow), 2)]
        strokes += neon_layers(shown, color, width_px, envelope * fade)
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)


def draw_rising_sparks(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    appearance = getattr(runtime, "appearance", None)
    if envelope <= 0 or appearance is None or not appearance.accents:
        return
    start = min(appearance.accents)
    elapsed = (frame_index - start) / runtime.fps
    duration = max(style.size, 0.5)
    data = appearance.accents.get(frame_index)
    if elapsed < 0 or elapsed > duration or not data:
        return
    width = layer.shape[1]
    x0, y0, x1, _ = data["head"]
    top = np.array([(x0 + x1) / 2 * width, y0 * height])
    span = (x1 - x0) * width
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:sparks:{start}".encode()) & 0xFFFFFFFF)
    fade = envelope * min((duration - elapsed) / 0.6, 1.0)
    for k in range(40):
        born = rng.uniform(0, duration * 0.8)
        life = rng.uniform(0.6, 1.2)
        t = (elapsed - born) / life
        if not 0 <= t <= 1:
            continue
        x = top[0] + rng.uniform(-0.45, 0.45) * span + np.sin(t * 6 + k) * span * 0.05
        y = top[1] + span * 0.25 - t * span * rng.uniform(0.9, 1.6)
        twinkle = 0.5 + 0.5 * np.sin(frame_index * 0.9 + k)
        color = np.asarray(style.colors[k % len(style.colors)], dtype=np.float32)
        splat(layer, float(x), float(y), span * 0.012 * (1 + twinkle), WHITE * 1.3, fade * (1 - t), runtime.kernels)
        splat(layer, float(x), float(y), span * 0.03, color, fade * (1 - t) * 0.6, runtime.kernels)
