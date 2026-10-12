"""Efectos de gestos con significado (docs/criterio_de_analisis.md, P4).

- throw_fx, disparado por `throw`:
  - Carga (del inicio del evento a la suelta): una bola de energía crece y late en la mano.
  - Suelta (después de `end_frame`), una de `style.shapes` por activación:
    - `orb`: la bola sale volando en la dirección del lanzamiento con estela y revienta en
      chispas diminutas.
    - `ray`: un rayo sale de la mano en esa dirección y se apaga.
    - `burst`: explosión de partículas en el punto de suelta.
  Conviene un `trigger.hold` de ~0,7 s para que la suelta tenga tiempo de verse.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.schema import MotionEvent
from vfxglow.analysis.touch import _people, fingertips
from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import neon_layers

THROW_SHAPES = ("orb", "ray", "burst")
# Bola: radio máximo en torsos. Vuelo: distancia (torsos) y duración (s). Estallido: duración.
ORB_RADIUS = 0.09
FLIGHT = 2.2
FLIGHT_S = 0.35
BURST_S = 0.35
RAY_S = 0.45
SPARKS = 18


def _circle(center: np.ndarray, radius: float, points: int = 28) -> np.ndarray:
    theta = np.linspace(0.0, 2.0 * np.pi, points)
    return center + np.stack([np.cos(theta), np.sin(theta)], axis=1) * radius


def _orb(center: np.ndarray, radius: float, color: np.ndarray, envelope: float, line: float, layer: np.ndarray) -> list:
    """Bola de energía: relleno de color, centro blanco y aro de neón."""
    fill_polygon(layer, _circle(center, radius * 1.3), color, 0.5 * envelope, 1.2, feather=radius * 0.6)
    fill_polygon(layer, _circle(center, radius * 0.55), np.ones(3, np.float32), 0.85 * envelope, 1.0, feather=radius * 0.3)
    return neon_layers(_circle(center, radius), color, line, envelope)


def _sparks(center: np.ndarray, radius: float, progress: float, color: np.ndarray, envelope: float, rng: np.random.Generator) -> list:
    """Chispas diminutas que salen en todas direcciones y se apagan."""
    strokes = []
    fade = envelope * (1.0 - progress)
    for angle, speed in zip(rng.uniform(0, 2 * np.pi, SPARKS), rng.uniform(0.6, 1.0, SPARKS)):
        direction = np.array([np.cos(angle), np.sin(angle)])
        head = center + direction * radius * speed * (0.3 + 0.7 * progress)
        tail = head - direction * radius * 0.25 * (1.0 - progress)
        strokes += neon_layers(np.stack([tail, head]), color, 1.4, fade)
    return strokes


def draw_throw_fx(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    style = runtime.effect.style
    if envelope <= 0 or event is None or event.name != "throw" or track is None:
        return
    width = layer.shape[1]
    torso = torso_pixels(points, height)
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    seed = zlib.crc32(f"{style.seed_offset}:throw:{event.start_frame}".encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    names = [n for n in style.shapes if n in THROW_SHAPES] or list(THROW_SHAPES)
    shape = names[int(rng.integers(len(names)))]
    fps = runtime.fps
    strokes: list = []
    if frame_index <= event.end_frame:
        # Carga: la bola crece en la mano y late.
        person = next((p for p in _people(track) if p.person_id == event.target.split(":")[0]), None)
        tips = fingertips(person, event.kind, width, height) if person is not None else []
        if not tips:
            return
        grow = (frame_index - event.start_frame) / max(event.end_frame - event.start_frame, 1)
        pulse = 1.0 + 0.12 * np.sin(frame_index * 0.9)
        radius = ORB_RADIUS * torso * (0.35 + 0.65 * np.clip(grow, 0.0, 1.0)) * pulse
        strokes += _orb(np.mean(tips, axis=0), radius, color, envelope, line, layer)
    else:
        if event.position is None:
            return
        start = np.array(event.position) * [width, height]
        direction = np.array([np.cos(np.radians(event.direction_deg)), np.sin(np.radians(event.direction_deg))])
        elapsed = (frame_index - event.end_frame) / fps
        if shape == "orb":
            if elapsed <= FLIGHT_S:
                u = elapsed / FLIGHT_S
                head = start + direction * FLIGHT * torso * u
                trail = np.stack([start + direction * FLIGHT * torso * max(u - 0.35, 0.0), head])
                strokes += neon_layers(trail, color, line * 1.5, envelope)
                strokes += _orb(head, ORB_RADIUS * torso, color, envelope, line, layer)
            elif elapsed <= FLIGHT_S + BURST_S:
                end = start + direction * FLIGHT * torso
                strokes += _sparks(end, torso * 0.6, (elapsed - FLIGHT_S) / BURST_S, color, envelope, rng)
        elif shape == "ray":
            if elapsed <= RAY_S:
                u = elapsed / RAY_S
                reach = 3.5 * torso * min(u / 0.3, 1.0)
                fade = envelope * (1.0 - max(u - 0.3, 0.0) / 0.7)
                strokes += neon_layers(np.stack([start, start + direction * reach]), color, line * 2.0, fade)
        elif elapsed <= BURST_S * 1.5:
            strokes += _sparks(start, torso * 0.8, elapsed / (BURST_S * 1.5), color, envelope, rng)
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)
