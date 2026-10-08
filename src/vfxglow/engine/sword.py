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
from vfxglow.engine.raster import fill_polygon, splat, stroke_batch
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


# Materiales de la hoja: cada activación sortea uno de style.shapes.
BLADE_MATERIALS = ("neon", "lightning", "fire", "chainsaw")


def draw_blade_glow(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """La hoja encendida: neón, rayo, fuego o motosierra (uno por activación, de style.shapes).

    Disparada por un tajo, solo se enciende la hoja de ese tajo.
    """
    effect = runtime.effect
    style = effect.style
    if envelope <= 0:
        return
    width_px = layer.shape[1]
    torso = torso_pixels(points, height)
    names = [name for name in style.shapes if name in BLADE_MATERIALS] or ["neon"]
    key = event.start_frame if event is not None else frame_index // max(style.palette_every, 1)
    seed = zlib.crc32(f"{style.seed_offset}:blade:{key}".encode()) & 0xFFFFFFFF
    material = names[int(np.random.default_rng(seed).integers(0, len(names)))]
    flicker = np.random.default_rng(seed + frame_index)
    strokes = []
    for blade, hilt, tip in _blades(track, width_px, height, style.people):
        if event is not None and event.target != f"{blade.person}:blade_{blade.hand}_tip":
            continue
        # Una estimación (prior) se pinta más tenue que una hoja vista.
        alpha = envelope * (1.0 if blade.source != "prior" else 0.6)
        width = max(2.0, style.thickness * torso)
        color = _hand_color(style, blade.hand)
        draw = {"neon": _neon_blade, "lightning": _lightning_blade, "fire": _fire_blade, "chainsaw": _chainsaw_blade}[material]
        strokes += draw(hilt, tip, color, width, alpha, frame_index, flicker, runtime, layer)
    stroke_batch(layer, strokes, style.hdr_gain)


def _neon_blade(hilt, tip, color, width, alpha, frame_index, rng, runtime, layer) -> list:
    return neon_layers(np.stack([hilt, tip]), color, width, alpha)


def _axes(hilt: np.ndarray, tip: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    d = tip - hilt
    length = max(float(np.linalg.norm(d)), 1e-6)
    u = d / length
    return u, np.array([-u[1], u[0]]), length


def _jagged(a: np.ndarray, b: np.ndarray, amplitude: float, rng: np.random.Generator, depth: int = 5) -> np.ndarray:
    """Rayo por desplazamiento del punto medio: cada nivel parte los tramos y los empuja de lado."""
    pts = [a, b]
    amp = amplitude
    for _ in range(depth):
        out = [pts[0]]
        for p, q in zip(pts, pts[1:]):
            d = q - p
            n = np.array([-d[1], d[0]]) / max(float(np.linalg.norm(d)), 1e-6)
            out += [(p + q) / 2 + n * rng.normal(0, amp), q]
        pts, amp = out, amp * 0.55
    return np.array(pts)


def _lightning_blade(hilt, tip, color, width, alpha, frame_index, rng, runtime, layer) -> list:
    """Hilo claro en el eje y descargas quebradas que se redibujan cada fotograma, con ramas."""
    u, n, length = _axes(hilt, tip)
    core = color * 0.6 + 0.4
    strokes = neon_layers(np.stack([hilt, tip]), core, width * 0.25, alpha * 0.7)
    for _ in range(2):
        bolt = _jagged(hilt, tip, max(width * 3.0, length * 0.05), rng, depth=4)
        strokes += neon_layers(bolt, color, width * 0.4, alpha)
    for _ in range(int(rng.integers(2, 5))):
        start = hilt + u * length * float(rng.uniform(0.25, 0.95))
        angle = float(rng.choice([-1.0, 1.0])) * float(rng.uniform(0.4, 1.1))
        direction = u * np.cos(angle) + n * np.sin(angle)
        branch = _jagged(start, start + direction * length * float(rng.uniform(0.15, 0.35)), width * 1.5, rng, depth=3)
        strokes += neon_layers(branch, color, width * 0.3, alpha * 0.8)
    splat(layer, float(tip[0]), float(tip[1]), width * 2.5, np.asarray(color, dtype=np.float32), alpha * 0.6, runtime.kernels)
    return strokes


def _fire_blade(hilt, tip, color, width, alpha, frame_index, rng, runtime, layer) -> list:
    """Hoja al rojo con lenguas que suben de su filo (hacia arriba de la imagen) y brasas."""
    from vfxglow.engine.burst import flame_tongue

    u, n, length = _axes(hilt, tip)
    strokes = neon_layers(np.stack([hilt, tip]), color, width * 0.8, alpha)
    up = -np.pi / 2
    for k in range(9):
        t = (k + 0.5) / 9
        base = hilt + u * length * t
        tongue_len = length * float(rng.uniform(0.2, 0.38)) * (0.6 + 0.4 * t)
        angle = up + float(rng.normal(0, 0.35))
        tongue = flame_tongue(base, angle, tongue_len, tongue_len * 0.28, float(rng.choice([-1.0, 1.0])) * 0.8, rng)
        strokes += neon_layers(tongue, color, width * 0.4, alpha * float(rng.uniform(0.6, 1.0)))
    for _ in range(4):
        start = hilt + u * length * float(rng.uniform(0.1, 1.0)) + np.array([0.0, -length * float(rng.uniform(0.15, 0.4))])
        strokes += neon_layers(np.stack([start, start + np.array([0.0, -width * 1.5])]), color, width * 0.3, alpha * 0.7)
    return strokes


def _chainsaw_blade(hilt, tip, color, width, alpha, frame_index, rng, runtime, layer) -> list:
    """Barra con dientes en el filo que corren hacia la punta, y chispas que saltan de ella."""
    u, n, length = _axes(hilt, tip)
    half = width * 1.4
    bar = [np.stack([hilt + n * half, tip + n * half]), np.stack([hilt - n * half, tip - n * half])]
    nose = tip + (np.cos(np.linspace(-np.pi / 2, np.pi / 2, 10))[:, None] * u + np.sin(np.linspace(-np.pi / 2, np.pi / 2, 10))[:, None] * n) * half
    strokes = []
    for line in bar + [nose]:
        strokes += neon_layers(line, color, width * 0.45, alpha)
    tooth = max(width * 3.5, length / 14)
    count = max(int(length / tooth), 4)
    phase = (frame_index * 0.35) % 1.0  # los dientes corren hacia la punta
    for side in (1.0, -1.0):
        teeth = []
        for k in range(count + 1):
            t = min((k + phase) / count, 1.0)
            base = hilt + u * length * t + n * half * side
            teeth += [base, base + n * side * tooth * 0.7 + u * tooth * 0.5]
        strokes += neon_layers(np.array(teeth), color, width * 0.45, alpha)
    for _ in range(5):
        angle = float(rng.uniform(-0.9, 0.9))
        direction = u * np.cos(angle) + n * np.sin(angle)
        start = tip + direction * half
        strokes += neon_layers(np.stack([start, start + direction * length * float(rng.uniform(0.08, 0.2))]), np.array([1.0, 0.85, 0.5], dtype=np.float32), width * 0.25, alpha)
    return strokes


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
