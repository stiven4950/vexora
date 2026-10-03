"""Efectos anclados a un contacto: grietas, ondas, carga y chispas de impacto."""

from __future__ import annotations

import math

import numpy as np

from vfxglow.analysis.schema import MotionEvent
from vfxglow.engine.anchors import resolve_anchor, torso_pixels
from vfxglow.engine.particles import Particle, draw_particles, step_particles
from vfxglow.engine.raster import sample_gradient, splat, stroke_gradient


def _origin(runtime, points) -> np.ndarray | None:
    effect = runtime.effect
    return resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)


def _event_age(event: MotionEvent | None, frame_index: int) -> int:
    if event is None:
        return 0
    return max(0, frame_index - event.start_frame)


def _fracture(origin: np.ndarray, noise, seed: int, rays: int, length: float) -> list[np.ndarray]:
    lines: list[np.ndarray] = []
    for i in range(rays):
        angle = (i / rays) * math.tau + noise.scalar(i * 3.1, seed * 0.17, 0.4, 2) * 0.4
        direction = np.array([math.cos(angle), math.sin(angle)], dtype=np.float64)
        pts = [origin.copy()]
        pos = origin.copy()
        steps = 7
        for step in range(steps):
            wobble = noise.scalar(i * 5.0 + step, seed * 0.3 + step, step * 0.2, 2)
            normal = np.array([-direction[1], direction[0]])
            pos = pos + direction * (length / steps) + normal * wobble * length * 0.12
            pts.append(pos.copy())
            if step in {2, 4}:
                branch_dir = direction + normal * (0.7 if step == 2 else -0.7)
                branch_dir = branch_dir / (float(np.linalg.norm(branch_dir)) + 1e-6)
                branch = [pts[-1].copy()]
                bpos = pts[-1].copy()
                for k in range(3):
                    bpos = bpos + branch_dir * (length * 0.18)
                    branch.append(bpos.copy())
                lines.append(np.stack(branch))
        lines.append(np.stack(pts))
    return lines


def draw_cracks(runtime, points, frame_index: int, height: int, envelope: float, layer, event: MotionEvent | None) -> None:
    origin = _origin(runtime, points)
    if origin is None or envelope <= 0:
        return
    key = (event.start_frame, event.target) if event is not None else ("free", runtime.effect.id)
    if runtime.crack_key != key or not runtime.crack_lines:
        runtime.crack_key = key
        length = torso_pixels(points, height) * (0.35 + 0.4 * (event.peak_speed if event else 0.3))
        runtime.crack_lines = _fracture(origin, runtime.noise, runtime.effect.style.seed_offset, 7, length)
    grow = max(envelope, 0.12)
    for line in runtime.crack_lines:
        n = max(2, int(math.ceil(len(line) * grow)))
        stroke_gradient(layer, line[:n], runtime.effect.style, max(1.2, runtime.effect.style.thickness * 40 * grow), envelope)


def draw_ripples(runtime, points, frame_index: int, height: int, envelope: float, layer, event: MotionEvent | None) -> None:
    origin = _origin(runtime, points)
    if origin is None or envelope <= 0:
        return
    age = _event_age(event, frame_index)
    base = torso_pixels(points, height)
    color = sample_gradient(runtime.effect.style.colors, 0.4) * runtime.effect.style.hdr_gain * envelope
    for ring in range(3):
        radius = max(8.0, base * 0.12) + max(0, age - ring * 4) * base * 0.035
        if radius > base * 1.6:
            continue
        fade = envelope * (1.0 - ring * 0.22) * max(0.15, 1.0 - age / 28.0)
        angles = np.linspace(0.0, math.tau, 48, endpoint=True)
        wobble = 1.0 + 0.08 * runtime.noise.scalar(ring, frame_index * 0.05, 0.2, 2)
        circle = np.stack(
            [origin[0] + np.cos(angles) * radius * wobble, origin[1] + np.sin(angles) * radius * wobble],
            axis=1,
        )
        stroke_gradient(layer, circle, runtime.effect.style, max(1.2, runtime.effect.style.thickness * 28 * (1.0 - ring * 0.2)), fade)
        splat(layer, float(origin[0]), float(origin[1]), radius * 0.15, color, fade * 0.15, runtime.kernels)


def draw_charge(runtime, points, frame_index: int, height: int, envelope: float, layer, event: MotionEvent | None) -> None:
    origin = _origin(runtime, points)
    if origin is None or envelope <= 0:
        return
    held = 1.0
    if event is not None:
        held = min(1.0, (event.end_frame - event.start_frame + 1) / 24.0)
    pulse = 0.65 + 0.35 * math.sin(frame_index * 0.35)
    radius = torso_pixels(points, height) * (0.12 + 0.1 * held) * pulse
    color = sample_gradient(runtime.effect.style.colors, 0.25 + 0.2 * pulse) * runtime.effect.style.hdr_gain
    for scale, fade in ((0.7, 0.55), (1.2, 0.28), (1.9, 0.12)):
        splat(layer, float(origin[0]), float(origin[1]), radius * scale, color, envelope * fade * held, runtime.kernels)
    angles = np.linspace(0.0, math.tau, 36, endpoint=True)
    ring = np.stack([origin[0] + np.cos(angles) * radius, origin[1] + np.sin(angles) * radius], axis=1)
    stroke_gradient(layer, ring, runtime.effect.style, max(1.4, runtime.effect.style.thickness * 22), envelope * 0.7 * held)


def draw_sparks(runtime, points, frame_index: int, height: int, envelope: float, layer, event: MotionEvent | None) -> None:
    origin = _origin(runtime, points)
    step_particles(runtime.particles)
    if origin is not None and envelope > 0:
        direction = np.array([0.0, -1.0])
        if event is not None:
            rad = math.radians(event.direction_deg)
            direction = -np.array([math.cos(rad), math.sin(rad)])
        width = max(2.0, runtime.effect.style.thickness * torso_pixels(points, height))
        room = max(0, 120 - len(runtime.particles))
        burst = 8 + int(10 * envelope)
        for _ in range(min(burst, room)):
            life = float(runtime.rng.uniform(5.0, 12.0))
            kick = runtime.rng.normal(0.0, 1.0, size=2)
            vel = direction * (4.0 + 8.0 * (event.peak_speed if event else 0.4)) + kick
            runtime.particles.append(
                Particle(
                    x=float(origin[0] + runtime.rng.normal(0.0, width * 0.2)),
                    y=float(origin[1] + runtime.rng.normal(0.0, width * 0.2)),
                    vx=float(vel[0]),
                    vy=float(vel[1]),
                    life=life,
                    max_life=life,
                    size=float(width * runtime.rng.uniform(0.2, 0.55)),
                    heat=float(runtime.rng.uniform(0.65, 1.0)),
                )
            )
    draw_particles(layer, runtime.particles, runtime.effect, max(envelope, 0.0), runtime.kernels)
