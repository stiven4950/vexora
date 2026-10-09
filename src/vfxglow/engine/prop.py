"""Objeto protagonista (la gorra de video_33): su contorno exacto en neón.

- prop_outline: contorno de SAM 2 con núcleo blanco y halo de color, y relleno de tinte opcional
  (`style.fill`), como la gorra verde o azul de la referencia. Disparado por un evento, se pinta
  en el tramo del evento; sin trigger, en cada fotograma en que se ve el objeto.

Formas (`style.shapes`): `double` añade un segundo contorno algo más grande; `no_outline` deja
solo el relleno (para el modo tint); `worn` lo pinta también en la cabeza (puesto o
acomodándolo; por defecto no: la gorra puesta deja de ser protagonista); `spin` lo pinta
también mientras gira (por defecto no, si no va disparado: ahí manda el anillo).

- prop_spring: durante un `prop_transfer`, un resorte (cordón en espiral visto de lado) une el
  objeto con la mano que lo va a recibir. Se estira hasta quedar casi recto cuando la mano se
  aleja y se comprime con bucles grandes cuando el objeto llega (video_33, fotogramas 18-38).
  `rings` = bucles; `size` = radio de los bucles comprimidos, en torsos. Conviene adelantarlo
  al evento con `trigger.lead`: en la referencia aparece antes de soltar la gorra.
- prop_rings: mientras el objeto gira en las manos (`prop_spin`), un anillo elíptico lo recorre
  a lo largo de su eje: sube con el color principal y baja con el acento (video_33, fotogramas
  70-94). La mitad de atrás va tenue, como tapada por el objeto. `rings` = anillos a la vez;
  `trail_frames` = fotogramas de una subida.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.props import _hand_point, _people
from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import neon_layers

# Puntos del contorno remuestreado y suavizado (en puntos) para que no se lea dentado.
RESAMPLE = 120
SMOOTH = 2.0
SHAPES = ("outline", "double", "no_outline", "worn", "spin")
# Anillos: ancho respecto al objeto en esa altura, inclinación (eje menor / mayor) y alfa de la
# mitad de atrás.
RING_WIDTH = 1.15
RING_TILT = 0.32
RING_BACK = 0.3
# Resorte: distancia (en torsos) a la que queda recto y muestras por bucle.
SPRING_STRAIGHT = 1.6
SPRING_SAMPLES = 28


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
    # Mientras gira, el protagonista es el anillo (prop_rings): el contorno se aparta.
    if track.prop.spinning and "spin" not in style.shapes and event is None:
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


def spring_curve(start: np.ndarray, end: np.ndarray, loops: int, radius: float) -> np.ndarray:
    """Hélice vista de lado entre dos puntos: bucles sobre la recta (como una "e" repetida).

    El radio se anula en los extremos para que el cordón nazca recto del objeto y de la mano.
    """
    delta = end - start
    length = float(np.linalg.norm(delta))
    if length < 1e-6:
        return np.stack([start, end])
    along = delta / length
    side = np.array([along[1], -along[0]])
    if side[1] > 0:  # los bucles, hacia arriba de la pantalla
        side = -side
    t = np.linspace(0.0, 1.0, max(loops, 1) * SPRING_SAMPLES + 1)
    theta = 2.0 * np.pi * max(loops, 1) * t
    r = radius * np.sin(np.pi * t) ** 0.35
    offset_along = t * length - r * 0.9 * np.sin(theta)
    offset_side = r * (1.0 - np.cos(theta))
    return start + np.outer(offset_along, along) + np.outer(offset_side, side)


def draw_prop_spring(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    style = runtime.effect.style
    if envelope <= 0 or event is None or track is None or track.prop is None or "_to_" not in event.kind:
        return
    width = layer.shape[1]
    polygon = prop_polygon(track, width, height)
    person = next((p for p in _people(track) if p.person_id == event.target.split(":")[0]), None)
    if polygon is None or person is None:
        return
    hand, _ = _hand_point(person, event.kind.split("_to_")[1], width, height)
    if hand is None:
        return
    anchor = polygon[int(np.argmin(np.linalg.norm(polygon - hand, axis=1)))]
    torso = torso_pixels(points, height)
    size = float(np.sqrt(max(np.ptp(polygon[:, 0]) * np.ptp(polygon[:, 1]), 1.0)))
    distance = float(np.linalg.norm(hand - anchor))
    # Llegó: el resorte se recoge.
    arrive = float(np.clip(distance / (size * 0.8), 0.0, 1.0))
    if arrive <= 0:
        return
    stretch = float(np.clip(1.0 - distance / (SPRING_STRAIGHT * torso), 0.0, 1.0))
    curve = spring_curve(anchor, hand, style.rings, style.size * torso * stretch)
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    stroke_batch(layer, neon_layers(curve, color, line, envelope * arrive), style.hdr_gain)


def object_axis(polygon: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Centro, eje de recorrido, eje transversal (unitarios) y media longitud del objeto.

    El recorrido es el eje principal (por momentos) más cercano a la vertical: en la referencia
    el anillo sube y baja en pantalla, también con la gorra de frente (eje largo horizontal).
    """
    center = polygon.mean(axis=0)
    cov = np.cov((polygon - center).T)
    _, vectors = np.linalg.eigh(cov)
    travel = max((vectors[:, 0], vectors[:, 1]), key=lambda axis: abs(axis[1]))
    if travel[1] > 0:  # el eje apunta hacia arriba de la pantalla
        travel = -travel
    across = np.array([-travel[1], travel[0]])
    half = float(np.ptp((polygon - center) @ travel)) * 0.5
    return center, travel, across, max(half, 1.0)


def ring_at(polygon: np.ndarray, position: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, float] | None:
    """Elipse del anillo a la altura `position` (-1 abajo, 1 arriba) del eje del objeto:
    (centro, eje del ancho, eje de la profundidad, semiancho)."""
    center, major, minor, half = object_axis(polygon)
    along = (polygon - center) @ major
    level = position * half * 0.85
    near = np.abs(along - level) < half * 0.2
    across = (polygon - center) @ minor
    if near.sum() >= 2:
        low, high = float(across[near].min()), float(across[near].max())
    else:
        low, high = float(across.min()), float(across.max())
    radius = (high - low) * 0.5 * RING_WIDTH
    if radius < 2.0:
        return None
    mid = center + major * level + minor * (low + high) * 0.5
    return mid, minor, major, radius


def draw_prop_rings(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    style = runtime.effect.style
    if envelope <= 0 or track is None or track.prop is None:
        return
    polygon = prop_polygon(track, layer.shape[1], height)
    if polygon is None:
        return
    start = event.start_frame if event is not None else 0
    rise = max(style.trail_frames, 2)
    torso = torso_pixels(points, height)
    line = max(1.5, style.thickness * torso)
    strokes = []
    for ring in range(max(style.rings, 1)):
        # Va y vuelve: sube en `rise` fotogramas y baja en otros tantos.
        phase = ((frame_index - start) / rise + ring * 2.0 / max(style.rings, 1)) % 2.0
        going_up = phase < 1.0
        t = phase if going_up else 2.0 - phase
        shape = ring_at(polygon, 2.0 * t - 1.0)
        if shape is None:
            continue
        mid, width_axis, depth_axis, radius = shape
        color = np.asarray(style.colors[0 if going_up else 1 % len(style.colors)], dtype=np.float32)
        theta = np.linspace(0.0, 2.0 * np.pi, 73)
        ellipse = mid + np.outer(np.cos(theta) * radius, width_axis) + np.outer(np.sin(theta) * radius * RING_TILT, depth_axis)
        # Mitad de delante (hacia abajo del eje) entera; la de atrás, tenue.
        front = np.sin(theta) <= 0
        for mask, alpha in ((front, 1.0), (~front, RING_BACK)):
            pieces = np.split(np.arange(len(theta)), np.where(np.diff(mask.astype(int)) != 0)[0] + 1)
            for piece in pieces:
                if len(piece) >= 2 and mask[piece[0]]:
                    strokes += neon_layers(ellipse[piece], color, line, envelope * alpha)
    stroke_batch(layer, strokes, style.hdr_gain)
