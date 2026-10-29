"""Manchas que siguen al movimiento (docs/criterio_de_analisis.md, P2 y P5).

- foot_paint: el pie que se arrastra o barre el piso deja una mancha de pintura o agua que lo
  sigue y gira con él, con la cola que se desvanece (video_33 seg. 25-26: entre las piernas
  como una serpiente). Solo pinta mientras el pie está cerca del piso y se desplaza.
  `trail_frames` = largo de la cola; `size` = ancho de la mancha en torsos.
- prop_swoosh: el objeto protagonista que se mueve rápido (lanzado, sacudido) deja una mancha
  grande en forma de coma que sigue su recorrido (seg. 26,6-27,4). Solo con velocidad
  (`min_speed`, torsos por fotograma).
"""

from __future__ import annotations

from collections import deque

import numpy as np

from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.raster import stroke_batch
from vfxglow.engine.swoosh import neon_layers

WHITE = np.array([1.0, 1.0, 1.0], dtype=np.float32)
# Pie: cerca del piso (torsos sobre el pie más bajo visto hace poco) y desplazamiento mínimo.
FLOOR_REACH = 0.18
SLIDE_SPEED = 0.025
PIECES = 8


def _taper(path: np.ndarray, color: np.ndarray, width: float, alpha: float) -> list:
    """Mancha que engorda de la cola a la cabeza: relleno de color difuso y núcleo blanco."""
    strokes = []
    bounds = np.linspace(0, len(path) - 1, PIECES + 1).astype(int)
    for index in range(PIECES):
        piece = path[bounds[index] : bounds[index + 1] + 1]
        if len(piece) < 2:
            continue
        t = (index + 1) / PIECES
        w = width * (0.25 + 0.75 * t)
        a = alpha * t
        strokes += [(piece, color, w, 0.55 * a, w * 0.25), (piece, color, w * 0.55, 0.8 * a)]
        strokes += neon_layers(piece, color, max(w * 0.12, 1.5), a)
    return strokes


def draw_foot_paint(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    torso = torso_pixels(points, height)
    strokes = []
    for side in ("left", "right"):
        foot = [points.get(f"{side}_{name}") for name in ("foot_index", "heel", "ankle")]
        foot = [p for p in foot if p is not None]
        key = f"foot:{side}"
        trail = runtime.swoosh.setdefault(key, deque(maxlen=max(style.trail_frames, 4)))
        floor_key = f"floor:{side}"
        if not foot:
            trail.append(None)
            continue
        ground = np.mean(foot, axis=0)
        # Piso: el punto más bajo del pie visto hace poco (cae despacio si la persona sube).
        floor = max(runtime.swoosh_activity.get(floor_key, ground[1]) - torso * 0.01, ground[1])
        runtime.swoosh_activity[floor_key] = floor
        last = runtime.swoosh.setdefault(f"last:{side}", deque(maxlen=1))
        previous = last[0] if last else None
        last.append(ground)
        moving = previous is not None and float(np.linalg.norm(ground - previous)) / torso > SLIDE_SPEED
        on_floor = (floor - ground[1]) / torso < FLOOR_REACH
        trail.append(ground if (moving and on_floor and envelope > 0) else None)
        path = [p for p in trail if p is not None]
        if len(path) >= 3 and trail[-1] is not None:
            color = np.asarray(style.colors[0 if side == "left" else 1 % len(style.colors)], dtype=np.float32)
            strokes += _taper(np.array(path), color, style.size * torso, envelope)
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)


def draw_prop_swoosh(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    trail = runtime.swoosh.setdefault("prop", deque(maxlen=max(style.trail_frames, 4)))
    prop = track.prop if track is not None else None
    if prop is None or prop.state in ("worn", "fitting", "away"):
        trail.clear()
        return
    width, torso = layer.shape[1], torso_pixels(points, height)
    center = np.mean(np.array(prop.contour), axis=0) * [width, height]
    previous = trail[-1] if trail else None
    trail.append(center)
    speed = float(np.linalg.norm(center - previous)) / torso if previous is not None else 0.0
    activity = runtime.swoosh_activity.get("prop", 0.0)
    # Se enciende con velocidad y se apaga despacio (la cola termina de verse).
    activity = 1.0 if speed > style.min_speed else max(activity - 0.15, 0.0)
    runtime.swoosh_activity["prop"] = activity
    if activity <= 0 or envelope <= 0 or len(trail) < 3:
        return
    size = float(np.sqrt(max((prop.box[2] - prop.box[0]) * width * (prop.box[3] - prop.box[1]) * height, 1.0)))
    color = np.asarray(style.colors[0], dtype=np.float32)
    stroke_batch(layer, _taper(np.array(trail), color, size * style.size, envelope * activity), style.hdr_gain)
