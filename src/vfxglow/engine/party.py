"""Efectos de fiesta: la energía de la escena y la música.

- disco_fx (`frenzy`): con mucho movimiento, destellos de neón disparados desde el cuerpo en
  todas direcciones y dos haces de luz que barren desde arriba, como en una discoteca.
- beat_pulse (`beat`): la silueta del cuerpo late en cada golpe de la música.
- mirror_ball: bola de espejos colgada arriba que lanza haces rectos de colores y destellos que
  caen por ellos como lluvia.
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


# Bola de espejos: radio (fracción del ancho), haces y destellos por haz.
BALL_RADIUS = 0.07
BEAMS = 9
DROPS = 5


def draw_mirror_ball(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    """Bola de espejos colgada arriba: facetas que giran, haces rectos de colores en abanico que
    barren despacio y destellos que caen en línea recta por esos haces, como lluvia de luz."""
    style = runtime.effect.style
    if envelope <= 0:
        return
    width = layer.shape[1]
    center = np.array([width * 0.5, height * 0.1])
    radius = width * BALL_RADIUS
    white = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    strokes = [(np.array([[center[0], 0.0], [center[0], center[1] - radius]]), white, 1.5, 0.6 * envelope)]
    theta = np.linspace(0, 2 * np.pi, 40)
    strokes += neon_layers(center + np.stack([np.cos(theta), np.sin(theta)], axis=1) * radius, white, 2.0, envelope)
    # Facetas: meridianos que avanzan (giro) y paralelos fijos.
    turn = frame_index * 0.08
    for k in range(6):
        phase = (turn + k * np.pi / 6) % np.pi
        squeeze = np.cos(phase)
        if abs(squeeze) > 0.98:
            continue
        lat = np.linspace(-np.pi / 2, np.pi / 2, 16)
        meridian = center + np.stack([np.cos(lat) * squeeze * radius, np.sin(lat) * radius], axis=1)
        strokes += [(meridian, white, 1.2, 0.5 * envelope)]
    for level in (-0.5, 0.0, 0.5):
        half = np.sqrt(1 - level**2) * radius
        strokes += [(np.array([center + [-half, level * radius], center + [half, level * radius]]), white, 1.2, 0.5 * envelope)]
    # Haces rectos de colores en abanico hacia abajo, que barren despacio.
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:ball".encode()) & 0xFFFFFFFF)
    reach = height * 1.1
    for beam in range(BEAMS):
        angle = np.pi / 2 + (beam - (BEAMS - 1) / 2) * 0.22 + 0.25 * np.sin(frame_index * 0.05 + beam)
        direction = np.array([np.cos(angle), np.sin(angle)])
        color = np.asarray(style.colors[beam % len(style.colors)], dtype=np.float32)
        start = center + direction * radius
        side = np.array([-direction[1], direction[0]]) * width * 0.025
        end = start + direction * reach
        fill_polygon(layer, np.array([start, end - side, end + side]), color, 0.07 * envelope, 1.0, feather=width * 0.01)
        # Lluvia: destellos cortos que viajan en línea recta por el haz.
        for drop in range(DROPS):
            u = (frame_index * 0.035 + drop / DROPS + rng.uniform(0, 1)) % 1.0
            head = start + direction * reach * u
            tail = head - direction * height * 0.04
            strokes += neon_layers(np.stack([tail, head]), color, 1.6, envelope * (1.0 - 0.5 * u))
    stroke_batch(layer, strokes, style.hdr_gain)
