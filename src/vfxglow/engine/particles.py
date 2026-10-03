"""Partículas con Euler semi-implícito, estiradas a lo largo de su velocidad."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vfxglow.director.schema import Effect
from vfxglow.engine.raster import sample_gradient, splat


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    heat: float


def spawn_particles(
    particles: list[Particle],
    rng: np.random.Generator,
    origin: np.ndarray,
    effect: Effect,
    envelope: float,
    width: float,
    speed: float,
    limit: int,
) -> None:
    if envelope <= 0 or len(particles) >= limit:
        return
    count = int(1 + 5 * effect.style.intensity * envelope * (0.45 + min(speed, 2.0)))
    room = limit - len(particles)
    for _ in range(min(count, room)):
        life = float(rng.uniform(8.0, 18.0))
        burst = (6.0 + 14.0 * min(speed, 2.0)) * effect.style.intensity
        particles.append(
            Particle(
                x=float(origin[0] + rng.normal(0.0, width * 0.12)),
                y=float(origin[1] + rng.normal(0.0, width * 0.12)),
                vx=float(rng.normal(0.0, burst * 0.25)),
                vy=float(-abs(rng.normal(burst * 0.55, burst * 0.15))),
                life=life,
                max_life=life,
                size=float(width * rng.uniform(0.35, 1.0)),
                heat=float(rng.uniform(0.55, 1.0)),
            )
        )


def step_particles(particles: list[Particle]) -> None:
    alive: list[Particle] = []
    for p in particles:
        p.vx += -p.vx * 0.08
        p.vy += -p.vy * 0.04 - 0.18
        p.x += p.vx
        p.y += p.vy
        p.life -= 1.0
        if p.life > 0:
            alive.append(p)
    particles[:] = alive


def draw_particles(
    layer: np.ndarray,
    particles: list[Particle],
    effect: Effect,
    envelope: float,
    kernels: dict[int, np.ndarray],
) -> None:
    blur = effect.render.motion_blur
    for p in particles:
        age = 1.0 - p.life / max(p.max_life, 1e-3)
        fade = float(np.clip(p.life / max(p.max_life, 1e-3), 0.0, 1.0))
        color = sample_gradient(effect.style.colors, np.clip(p.heat * (1.0 - age), 0.0, 1.0))
        energy = color * np.float32(effect.style.hdr_gain * envelope)
        speed = float(np.hypot(p.vx, p.vy))
        steps = 1 + int(min(6, blur * speed / max(p.size, 1.0)))
        for s in range(steps):
            t = s / steps
            splat(
                layer,
                p.x - p.vx * t * 0.45,
                p.y - p.vy * t * 0.45,
                p.size * (1.0 - 0.35 * age),
                energy,
                fade / steps,
                kernels,
            )
