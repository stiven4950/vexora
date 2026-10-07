"""Marcas de intención: figuras de neón que siguen a la mano que empieza a moverse.

Cuando una persona anuncia lo que va a hacer (evento `intent`), la extremidad que se mueve se
resalta. La figura se sortea por activación entre `style.shapes`:

- rune: runa angular de trazos rectos junto a la mano (como el signo sobre el pecho).
- rays: rayas cortas que se desprenden del antebrazo hacia fuera.
- halo: garabato circular alrededor de la mano.
- spiral: espiral que gira en la mano.
- sparkle: tres destellos pequeños alrededor de la mano.
- cross: cruz de dos trazos (video_38: cruz sobre el pecho antes de un tajo).
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.burst import sparkle
from vfxglow.engine.raster import stroke_batch
from vfxglow.engine.swoosh import neon_layers

SHAPES = ("rune", "rays", "halo", "spiral", "sparkle", "cross")
TAU = 2.0 * np.pi


def draw_intent_mark(runtime, track: FrameRecord | None, points: dict[str, np.ndarray], frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    if envelope <= 0 or event is None or ":" not in event.target:
        return
    person, joint = event.target.split(":", 1)
    if style.people and person not in style.people:
        return
    hand = points.get(event.target)
    if hand is None:
        return
    side = joint.split("_", 1)[0]
    elbow = points.get(f"{person}:{side}_elbow")
    seed = zlib.crc32(f"{style.seed_offset}:mark:{event.target}:{event.start_frame}".encode()) & 0xFFFFFFFF
    shape_rng = np.random.default_rng(seed)
    names = [name for name in style.shapes if name in SHAPES] or ["halo"]
    shape = names[int(shape_rng.integers(0, len(names)))]
    boil = np.random.default_rng(seed + frame_index // max(style.boil_frames, 1))
    torso = torso_pixels(points, height)
    size = style.size * torso
    index = int(person.rsplit("_", 1)[-1]) if person[-1].isdigit() else 0
    color = np.asarray(style.colors[index % len(style.colors)], dtype=np.float32)
    width = max(1.2, style.thickness * torso)
    grow = float(np.clip(runtime.active_frames / 4.0, 0.0, 1.0))
    strokes = []
    for line in mark(shape, hand, elbow, size * grow, frame_index, shape_rng, boil):
        strokes += neon_layers(line, color, width, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


def mark(shape: str, hand: np.ndarray, elbow: np.ndarray | None, size: float, frame_index: int, shape_rng: np.random.Generator, boil: np.random.Generator) -> list[np.ndarray]:
    if size < 2.0:
        return []
    jitter = size * 0.04
    if shape == "rune":
        # Trazos ortogonales: un signo angular fijo por activación que tiembla un poco.
        steps = shape_rng.integers(3, 6)
        point = hand + np.array([size * 0.3, -size * 0.4])
        path = [point.copy()]
        horizontal = bool(shape_rng.integers(0, 2))
        for _ in range(int(steps)):
            length = size * float(shape_rng.uniform(0.35, 0.7)) * float(shape_rng.choice([-1.0, 1.0]))
            point = point + (np.array([length, 0.0]) if horizontal else np.array([0.0, abs(length)]))
            path.append(point.copy())
            horizontal = not horizontal
        line = np.asarray(path)
        return [line + boil.normal(0, jitter, line.shape)]
    if shape == "rays":
        base = elbow if elbow is not None else hand + np.array([0.0, size])
        axis = hand - base
        length = max(float(np.linalg.norm(axis)), 1e-6)
        axis /= length
        normal = np.array([-axis[1], axis[0]])
        lines = []
        for k in range(4):
            t = 0.2 + 0.2 * k
            origin = base + axis * length * t
            out = normal * (1.0 if k % 2 else -1.0) + axis * 0.4
            start = origin + out * size * 0.25
            lines.append(np.vstack([start, start + out * size * float(boil.uniform(0.35, 0.6))]))
        return lines
    if shape == "halo":
        theta = np.linspace(0, TAU * 1.15, 30)
        radius = size * 0.55 * (1 + boil.normal(0, 0.06, len(theta)))
        return [hand + np.stack([np.cos(theta), np.sin(theta) * 0.85], axis=1) * radius[:, None]]
    if shape == "spiral":
        theta = np.linspace(0, TAU * 2.2, 40)
        radius = size * 0.6 * theta / theta[-1]
        turn = theta + frame_index * 0.3
        return [hand + np.stack([np.cos(turn), np.sin(turn)], axis=1) * radius[:, None]]
    if shape == "cross":
        tilt = float(shape_rng.uniform(-0.3, 0.3))
        arms = []
        for angle in (tilt, tilt + np.pi / 2):
            d = np.array([np.cos(angle), np.sin(angle)])
            arms.append(np.vstack([hand - d * size * 0.6, hand + d * size * 0.6]) + boil.normal(0, jitter, (2, 2)))
        return arms
    angles = shape_rng.uniform(0, TAU, 3)
    return [
        sparkle(hand + np.array([np.cos(a), np.sin(a)]) * size * 0.7, size * float(shape_rng.uniform(0.18, 0.3)) * (0.8 + 0.2 * np.sin(frame_index + a)))
        for a in angles
    ]
