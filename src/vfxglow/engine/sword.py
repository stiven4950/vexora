"""Efectos de espadas y acrobacias, sacados de las referencias video_38 y video_39.

- blade_glow: la hoja pintada de neón (tubo con núcleo claro) en cada fotograma.
- blade_echo: copias fantasma de la hoja en posiciones de hace unos fotogramas.
- body_outline: contorno de la silueta (Selfie Segmenter) en neón, entero o en guiones.
- ground_burst: salpicadura en abanico sobre el piso (aterrizaje, hoja contra el suelo).
- ground_cloud: anillo de humo de dibujo animado que se expande por el piso.
- floor_streak: raya larga sobre el piso que crece desde el punto del evento.
"""

from __future__ import annotations

import zlib
from collections import deque

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import neon_layers

TAU = 2.0 * np.pi
# Copias de la hoja: retrasos en fotogramas y velocidad mínima de la punta (torsos/fotograma).
ECHO_LAGS = (3, 7)
ECHO_SPEED = 0.12


def _hand_color(style, hand: str) -> np.ndarray:
    index = 0 if hand == "left" else 1
    return np.asarray(style.colors[index % len(style.colors)], dtype=np.float32)


def _blades(track: FrameRecord | None, width: int, height: int, people: list[str]):
    if track is None:
        return []
    scale = np.array([width, height], dtype=np.float64)
    return [
        (b, np.array(b.hilt) * scale, np.array(b.tip) * scale)
        for b in track.blades
        if not people or b.person in people
    ]


def draw_blade_glow(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """La hoja pintada de neón. Disparada por un tajo, solo la hoja de ese tajo se enciende."""
    effect = runtime.effect
    style = effect.style
    if envelope <= 0:
        return
    width_px = layer.shape[1]
    torso = torso_pixels(points, height)
    strokes = []
    for blade, hilt, tip in _blades(track, width_px, height, style.people):
        if event is not None and event.target != f"{blade.person}:blade_{blade.hand}_tip":
            continue
        # Una estimación (prior) se pinta más tenue que una hoja vista.
        alpha = envelope * (1.0 if blade.source != "prior" else 0.6)
        width = max(2.0, style.thickness * torso)
        strokes += neon_layers(np.stack([hilt, tip]), _hand_color(style, blade.hand), width, alpha)
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_blade_echo(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    effect = runtime.effect
    style = effect.style
    width_px = layer.shape[1]
    torso = torso_pixels(points, height)
    history: dict[str, deque] = runtime.swoosh
    strokes = []
    for blade, hilt, tip in _blades(track, width_px, height, style.people):
        key = f"{blade.person}:{blade.hand}"
        trail = history.setdefault(key, deque(maxlen=max(ECHO_LAGS) + 1))
        if trail and frame_index - trail[-1][0] > 2:
            trail.clear()
        trail.append((frame_index, hilt.copy(), tip.copy()))
        if envelope <= 0 or len(trail) < 2:
            continue
        # Disparado por un tajo: solo la hoja de ese tajo deja copias.
        if event is not None and event.target != f"{blade.person}:blade_{blade.hand}_tip":
            continue
        if blade.source == "prior":
            continue
        speed = float(np.linalg.norm(trail[-1][2] - trail[-2][2])) / max(torso, 1.0)
        if speed < ECHO_SPEED:
            continue
        color = _hand_color(style, blade.hand)
        width = max(1.5, style.thickness * torso * 0.8)
        for k, lag in enumerate(ECHO_LAGS):
            if lag >= len(trail):
                break
            _f, old_hilt, old_tip = trail[-1 - lag]
            # La copia se separa un poco del cuerpo: flota donde estuvo la hoja.
            strokes += neon_layers(np.stack([old_hilt, old_tip]), color, width, envelope * (0.7 - 0.2 * k))
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_body_outline(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    if envelope <= 0 or track is None or not track.body_contour:
        return
    width_px = layer.shape[1]
    contour = np.array(track.body_contour) * np.array([width_px, height])
    names = [name for name in style.shapes if name in ("outline", "dashes", "double")] or ["outline"]
    key = event.start_frame if event is not None else frame_index // max(style.palette_every, 1)
    seed = zlib.crc32(f"{style.seed_offset}:body:{key}".encode()) & 0xFFFFFFFF
    shape = names[int(np.random.default_rng(seed).integers(0, len(names)))]
    # Line boil: el contorno tiembla un poco cada `boil_frames`, como redibujado a mano.
    boil = np.random.default_rng(seed + frame_index // max(style.boil_frames, 1))
    torso = torso_pixels(points, height)
    contour = contour + boil.normal(0, torso * 0.008, contour.shape)
    color = np.asarray(style.colors[0], dtype=np.float32)
    width = max(1.2, style.thickness * torso)
    strokes = []
    if shape == "dashes":
        step = max(len(contour) // 18, 2)
        for start in range(0, len(contour) - 2, step):
            strokes += neon_layers(contour[start : start + max(step // 2, 2)], color, width, envelope)
    else:
        strokes += neon_layers(contour, color, width, envelope)
        if shape == "double":
            center = contour.mean(axis=0)
            strokes += neon_layers(center + (contour - center) * 1.06, color, width * 0.6, envelope * 0.6)
    stroke_batch(layer, strokes, style.hdr_gain)


def _event_point(runtime, event: MotionEvent | None, width: int, height: int) -> np.ndarray | None:
    if runtime.anchor_point is not None:
        return runtime.anchor_point
    if event is not None and event.position is not None:
        return np.array([event.position[0] * width, event.position[1] * height])
    return None


def _age(runtime, effect) -> float:
    hold = effect.triggers[0].hold if effect.triggers else 12
    return float(np.clip(runtime.active_frames / max(hold, 1), 0.0, 1.0))


def draw_ground_burst(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    """Abanico de puntas que salta del piso, con gotas cortas a los lados."""
    effect = runtime.effect
    style = effect.style
    origin = _event_point(runtime, event, layer.shape[1], height)
    if origin is None or envelope <= 0 or event is None:
        return
    torso = torso_pixels(points, height)
    size = style.size * torso
    age = _age(runtime, effect)
    grow = 1.0 - (1.0 - min(1.0, age * 3.0)) ** 2
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:burst:{event.start_frame}".encode()) & 0xFFFFFFFF)
    color = np.asarray(style.colors[0], dtype=np.float32)
    width = max(1.5, style.thickness * torso)
    strokes = []
    for k in range(7):
        # Abanico hacia arriba: de -150° a -30°, como una salpicadura en el suelo.
        angle = np.radians(-150 + 120 * k / 6) + float(rng.normal(0, 0.08))
        length = size * float(rng.uniform(0.5, 1.0)) * grow
        base = origin + np.array([np.cos(angle), np.sin(angle) * 0.35]) * size * 0.15
        spike = np.stack([base, base + np.array([np.cos(angle), np.sin(angle)]) * length])
        strokes += neon_layers(spike, color, width * (1.4 - 0.6 * age), envelope)
    for k in range(5):
        angle = float(rng.uniform(-np.pi, 0))
        start = origin + np.array([np.cos(angle), np.sin(angle) * 0.4]) * size * (0.6 + 0.6 * age)
        strokes += neon_layers(np.stack([start, start + np.array([np.cos(angle), np.sin(angle)]) * size * 0.12]), color, width * 0.8, envelope * (1 - age))
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_ground_cloud(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    """Humo de dibujo animado: anillo de bultos, aplanado por la perspectiva del piso, que crece."""
    effect = runtime.effect
    style = effect.style
    origin = _event_point(runtime, event, layer.shape[1], height)
    if origin is None or envelope <= 0 or event is None:
        return
    torso = torso_pixels(points, height)
    age = _age(runtime, effect)
    radius = style.size * torso * (0.4 + 0.9 * (1.0 - (1.0 - age) ** 2))
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:cloud:{event.start_frame}".encode()) & 0xFFFFFFFF)
    color = np.asarray(style.colors[0], dtype=np.float32)
    width = max(1.5, style.thickness * torso)
    theta = np.linspace(0, TAU, 160)
    lobes = int(rng.integers(9, 13))
    phase = float(rng.uniform(0, TAU))
    strokes = []
    rings = []
    for ring, scale in ((0, 1.0), (1, 0.35 + 0.35 * age)):
        bumps = 1.0 + 0.12 * np.abs(np.sin(theta * lobes / 2 + phase + ring))
        r = radius * scale * bumps
        outline = origin + np.stack([np.cos(theta) * r, np.sin(theta) * r * 0.32], axis=1)
        rings.append(outline)
        strokes += neon_layers(outline, color, width * (1.3 if ring == 0 else 0.9), envelope * (1.0 - 0.5 * age))
    # Relleno blanco del humo; el centro se abre a medida que la nube se expande.
    fade = envelope * (1.0 - 0.6 * age)
    fill_polygon(layer, rings[0], np.array([1.0, 0.97, 0.92], dtype=np.float32), 0.85 * fade, style.hdr_gain * 0.6, holes=[rings[1]])
    fill_polygon(layer, rings[0], color, 0.35 * fade, style.hdr_gain * 0.6, feather=6.0, holes=[rings[1]])
    for _ in range(4):
        angle = float(rng.uniform(0, TAU))
        center = origin + np.array([np.cos(angle), np.sin(angle) * 0.32]) * radius * 1.15
        arc = np.linspace(0, np.pi * 1.4, 12) + angle
        strokes += neon_layers(center + np.stack([np.cos(arc), np.sin(arc)], axis=1) * radius * 0.08, color, width * 0.7, envelope * (1 - age))
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_floor_streak(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    """Raya larga y recta sobre el piso que crece hacia los dos lados del evento."""
    effect = runtime.effect
    style = effect.style
    origin = _event_point(runtime, event, layer.shape[1], height)
    if origin is None or envelope <= 0 or event is None:
        return
    torso = torso_pixels(points, height)
    age = _age(runtime, effect)
    reach = style.size * torso * (0.3 + 0.7 * min(1.0, age * 2.5))
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:streak:{event.start_frame}".encode()) & 0xFFFFFFFF)
    tilt = float(rng.normal(0, 0.12))
    direction = np.array([np.cos(tilt), np.sin(tilt)])
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = np.stack([origin - direction * reach, origin + direction * reach])
    stroke_batch(layer, neon_layers(line, color, max(2.0, style.thickness * torso), envelope * (1 - 0.6 * age)), style.hdr_gain)
