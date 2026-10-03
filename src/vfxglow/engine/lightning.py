"""Rayo fractal con continuidad temporal.

El eje va de la articulación al objetivo o, si no hay objetivo, a lo largo de la
velocidad de la mano. El quiebre sale de ruido 3D evaluado en (arco, rama, slot),
así el rayo cambia poco entre fotogramas y se re-siembra cada `reseed_every` con
fundido cruzado. Las ramas nacen en los puntos de subdivisión con grosor decreciente.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vfxglow.director.schema import Effect
from vfxglow.engine.anchors import joint_speed, joint_velocity, resolve_anchor, torso_pixels
from vfxglow.engine.noise import ValueNoise
from vfxglow.engine.particles import Particle, draw_particles, step_particles
from vfxglow.engine.raster import sample_gradient, stroke_gradient, stroke_polyline


@dataclass
class BoltTree:
    segments: list[np.ndarray]
    widths: list[float]
    tips: list[np.ndarray]


def _tip(origin: np.ndarray, effect: Effect, points: dict[str, np.ndarray], track, height: int) -> np.ndarray:
    if effect.target.secondary:
        other = resolve_anchor(points, "joint", effect.target.secondary)
        if other is not None:
            return other
    vx, vy = joint_velocity(track, effect.target.id)
    direction = np.array([vx, vy], dtype=np.float64)
    if float(np.linalg.norm(direction)) < 1e-4:
        direction = np.array([0.0, -1.0], dtype=np.float64)
    direction = direction / (float(np.linalg.norm(direction)) + 1e-6)
    speed = min(joint_speed(track, effect.target.id), 1.6)
    length = torso_pixels(points, height) * effect.style.lightning.reach * (0.4 + 0.7 * speed)
    return origin + direction * length


def _displace(a: np.ndarray, b: np.ndarray, noise: ValueNoise, slot: int, branch_id: int, depth: int, jitter: float, octaves: int) -> np.ndarray:
    pts = [a.astype(np.float64), b.astype(np.float64)]
    amp = float(np.linalg.norm(b - a)) * jitter
    for level in range(max(depth, 1)):
        nxt = [pts[0]]
        span = max(len(pts) - 1, 1)
        for i, (left, right) in enumerate(zip(pts, pts[1:])):
            mid = (left + right) * 0.5
            direction = right - left
            length = float(np.linalg.norm(direction)) + 1e-6
            normal = np.array([-direction[1], direction[0]]) / length
            t = (i + 0.5) / span
            sample = noise.scalar(
                t * 9.0 + branch_id * 13.0,
                level * 5.0 + slot * 0.02,
                slot * 0.37 + branch_id * 0.11,
                octaves,
            )
            nxt.append(mid + normal * sample * amp)
            nxt.append(right)
        pts = nxt
        amp *= 0.55
    return np.stack(pts)


def _branch(
    parent: np.ndarray,
    noise: ValueNoise,
    slot: int,
    depth: int,
    effect: Effect,
    segments: list[np.ndarray],
    widths: list[float],
    tips: list[np.ndarray],
) -> None:
    params = effect.style.lightning
    if depth > params.branch_depth:
        return
    count = max(1, params.branches - depth + 1)
    n = len(parent)
    for k in range(count):
        t = 0.35 + 0.5 * (0.5 + 0.5 * noise.scalar(k * 7.0, depth * 3.0, slot * 0.2 + k, 1))
        t = float(np.clip(t, 0.25, 0.85))
        idx = int(t * (n - 1))
        origin = parent[idx]
        tangent = parent[min(idx + 1, n - 1)] - parent[max(idx - 1, 0)]
        length = float(np.linalg.norm(tangent)) + 1e-6
        tangent = tangent / length
        normal = np.array([-tangent[1], tangent[0]])
        sign = 1.0 if k % 2 == 0 else -1.0
        angle = np.radians(params.branch_angle) * sign
        rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        direction = rot @ (tangent * 0.7 + normal * 0.2 * sign)
        reach = length * (0.55 / depth)
        tip = origin + direction / (float(np.linalg.norm(direction)) + 1e-6) * reach
        child = _displace(
            origin,
            tip,
            noise,
            slot,
            depth * 17 + k,
            max(1, params.branch_depth - depth + 1),
            params.jitter * 0.85,
            effect.style.noise.octaves,
        )
        segments.append(child)
        widths.append(0.5**depth)
        tips.append(child[-1])
        _branch(child, noise, slot, depth + 1, effect, segments, widths, tips)


def build_bolt(origin: np.ndarray, tip: np.ndarray, noise: ValueNoise, slot: int, effect: Effect) -> BoltTree:
    params = effect.style.lightning
    trunk = _displace(origin, tip, noise, slot, 0, params.branch_depth + 3, params.jitter, effect.style.noise.octaves)
    segments = [trunk]
    widths = [1.0]
    tips = [trunk[-1]]
    _branch(trunk, noise, slot, 1, effect, segments, widths, tips)
    return BoltTree(segments, widths, tips)


def _draw_tree(layer: np.ndarray, tree: BoltTree, effect: Effect, envelope: float, width: float) -> None:
    hot = sample_gradient(effect.style.colors, 0.0)
    for segment, scale in zip(tree.segments, tree.widths):
        stroke_gradient(layer, segment, effect.style, max(1.0, width * scale), envelope * (0.55 + 0.45 * scale))
        stroke_polyline(
            layer,
            segment,
            hot,
            max(1.0, width * scale * 0.28),
            effect.style.hdr_gain * envelope,
            envelope,
        )


def _spawn_sparks(runtime, tips: list[np.ndarray], envelope: float, width: float) -> None:
    count = runtime.effect.style.lightning.sparks
    if envelope <= 0 or count <= 0 or not tips:
        return
    room = max(0, 80 - len(runtime.particles))
    for i, tip in enumerate(tips[: min(count, room)]):
        life = float(runtime.rng.uniform(4.0, 9.0))
        runtime.particles.append(
            Particle(
                x=float(tip[0]),
                y=float(tip[1]),
                vx=float(runtime.rng.normal(0.0, 2.4)),
                vy=float(runtime.rng.normal(-1.2, 2.0)),
                life=life,
                max_life=life,
                size=float(width * runtime.rng.uniform(0.18, 0.45)),
                heat=float(runtime.rng.uniform(0.7, 1.0)),
            )
        )


def draw_lightning(
    runtime,
    track,
    points: dict[str, np.ndarray],
    frame_index: int,
    height: int,
    envelope: float,
    layer: np.ndarray,
) -> None:
    effect = runtime.effect
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if origin is None or envelope <= 0:
        step_particles(runtime.particles)
        draw_particles(layer, runtime.particles, effect, max(envelope, 0.15), runtime.kernels)
        return
    tip = _tip(origin, effect, points, track, height)
    every = max(effect.style.lightning.reseed_every, 1)
    slot = frame_index // every
    if slot != runtime.bolt_slot:
        runtime.bolt_prev = runtime.bolt_curr
        runtime.bolt_curr = build_bolt(origin, tip, runtime.noise, slot, effect)
        runtime.bolt_slot = slot
    phase = (frame_index % every) / every
    width = max(1.6, effect.style.thickness * torso_pixels(points, height))
    if runtime.bolt_prev is not None:
        _draw_tree(layer, runtime.bolt_prev, effect, envelope * (1.0 - phase), width)
    if runtime.bolt_curr is not None:
        _draw_tree(layer, runtime.bolt_curr, effect, envelope * (0.35 + 0.65 * phase), width)
        _spawn_sparks(runtime, runtime.bolt_curr.tips, envelope, width)
    step_particles(runtime.particles)
    draw_particles(layer, runtime.particles, effect, envelope, runtime.kernels)
