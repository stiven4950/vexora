"""Efectos de fiesta: la energía de la escena y la música.

- disco_fx (`frenzy`): con mucho movimiento, destellos de neón disparados desde el cuerpo en
  todas direcciones y dos haces de luz que barren desde arriba, como en una discoteca.
- beat_pulse (`beat`): la silueta del cuerpo late en cada golpe de la música.
- equalizer: barras de neón sobre el piso que saltan con los golpes de la música (siempre o en
  una ventana). Lee los golpes de `runtime.beats` (el motor los pone).
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import neon_layers

# Discoteca: destellos nuevos por fotograma, vida (fotogramas) y alcance (torsos).
DISCO_SPAWN = 3
DISCO_LIFE = 10
DISCO_REACH = 2.6
# Ecualizador: barras, alto máximo (torsos) y caída por fotograma tras un golpe.
BARS = 14
BAR_HEIGHT = 0.9
BAR_DECAY = 0.82


def _center(points) -> np.ndarray | None:
    names = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
    found = [points[n] for n in names if n in points]
    return np.mean(found, axis=0) if found else None


def draw_disco(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    center = _center(points)
    if envelope > 0 and center is not None:
        rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:disco:{frame_index}".encode()) & 0xFFFFFFFF)
        for _ in range(DISCO_SPAWN):
            angle = rng.uniform(0, 2 * np.pi)
            color = style.colors[int(rng.integers(len(style.colors)))]
            runtime.bits.append([center.copy(), angle, frame_index, np.asarray(color, dtype=np.float32)])
    runtime.bits = [bit for bit in runtime.bits if frame_index - bit[2] < DISCO_LIFE]
    if not runtime.bits:
        return
    torso = torso_pixels(points, height)
    strokes = []
    for origin, angle, born, color in runtime.bits:
        age = (frame_index - born) / DISCO_LIFE
        direction = np.array([np.cos(angle), np.sin(angle)])
        head = origin + direction * DISCO_REACH * torso * age**0.7
        tail = head - direction * torso * 0.25 * (1.0 - age)
        strokes += neon_layers(np.stack([tail, head]), color, 1.6, (1.0 - age) * max(envelope, 0.3))
    if envelope > 0:
        # Dos haces de luz que barren desde las esquinas de arriba.
        width = layer.shape[1]
        for k, corner in enumerate((np.array([0.0, 0.0]), np.array([float(width), 0.0]))):
            sweep = 0.5 + 0.5 * np.sin(frame_index * 0.12 + k * np.pi)
            target = np.array([width * (0.2 + 0.6 * sweep), height * 0.95])
            side = np.array([-(target - corner)[1], (target - corner)[0]])
            side = side / max(float(np.linalg.norm(side)), 1e-6) * width * 0.06
            color = np.asarray(style.colors[k % len(style.colors)], dtype=np.float32)
            fill_polygon(layer, np.array([corner, target - side, target + side]), color, 0.16 * envelope, 1.0, feather=width * 0.02)
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_beat_pulse(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    """La silueta late: el contorno del cuerpo un poco agrandado, que se apaga tras el golpe."""
    style = runtime.effect.style
    if envelope <= 0 or track is None or not track.body_contour:
        return
    width = layer.shape[1]
    contour = np.array(track.body_contour) * [width, height]
    center = contour.mean(axis=0)
    since = frame_index - event.start_frame if event is not None else 0
    grow = 1.0 + 0.04 * min(since, 6) / 6
    outline = center + (contour - center) * grow
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso_pixels(points, height))
    stroke_batch(layer, neon_layers(np.vstack([outline, outline[:1]]), color, line, envelope), style.hdr_gain)


def draw_equalizer(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    if envelope <= 0:
        return
    beats = [b for b in getattr(runtime, "beats", []) if b <= frame_index]
    if not beats:
        return
    width = layer.shape[1]
    feet = [points[n] for n in ("left_heel", "right_heel", "left_foot_index", "right_foot_index") if n in points]
    floor = max(p[1] for p in feet) + height * 0.02 if feet else height * 0.95
    torso = torso_pixels(points, height)
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:eq".encode()) & 0xFFFFFFFF)
    weights = rng.uniform(0.4, 1.0, size=(BARS, 8))
    strokes = []
    # Energía de la música: golpes recientes, cada uno decae; cada barra responde distinto.
    recent = [frame_index - b for b in beats[-8:]]
    for bar in range(BARS):
        energy = sum(weights[bar, k % 8] * BAR_DECAY**age for k, age in enumerate(recent))
        tall = min(energy, 1.6) / 1.6 * BAR_HEIGHT * torso
        x = width * (0.08 + 0.84 * bar / (BARS - 1))
        if tall < 2:
            continue
        color = np.asarray(style.colors[bar % len(style.colors)], dtype=np.float32)
        strokes += neon_layers(np.array([[x, floor], [x, floor - tall]]), color, max(2.0, width * 0.012), envelope * 0.8)
    stroke_batch(layer, strokes, style.hdr_gain)
