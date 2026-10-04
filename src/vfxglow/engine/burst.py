"""Impactos en line-art de neón: llamarada, chispas en guiones y gotas.

Todo se dibuja como contorno o trazo fino (no manchas difusas), igual que el swoosh:

- flame_burst: en cada contacto, lenguas de fuego contorneadas que nacen del punto del
  golpe, crecen deprisa, se enroscan y se apagan. Color del atacante, con alguna lengua del
  color del rival para que las dos energías se mezclen.
- spark_dashes: guiones cortos que salen disparados del contacto y caen con gravedad.
- droplets: en algunos puñetazos rápidos el puño suelta partículas contorneadas. Cada golpe
  elige una forma de `style.shapes`: gota (cae como lluvia), anillo y hoja de fuego (suben
  como brasas), rizo (deriva girando) o guion (sale disparado).

Las tres usan el torso como unidad de tamaño, así que no dependen de la resolución.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.anchors import joint_speed, resolve_anchor, torso_pixels
from vfxglow.engine.raster import stroke_batch
from vfxglow.engine.swoosh import neon_layers, swoosh_keys

TAU = 2.0 * np.pi
# Fracción de la vida de la llamarada en la que alcanza su tamaño completo.
GROW = 0.3
# Gotas en pantalla a la vez y nuevas por fotograma: pocas y pequeñas para no saturar el plano.
DROPLET_LIMIT = 40
DROPLETS_PER_FRAME = 2
# Topes de tamaño como fracción de la altura del cuadro (llamarada y partícula).
MAX_BURST = 0.12
MAX_BIT = 0.012
SPARK_LIMIT = 80


@dataclass
class Bit:
    """Partícula de line-art: gota, anillo, hoja, rizo o guion."""

    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    color: int
    shape: str = "dash"
    gravity: float = 1.0
    spin: float = 1.0


# Forma -> (gravedad relativa: negativa sube, fracción de la velocidad de la mano que hereda).
SHAPES: dict[str, tuple[float, float]] = {
    "drop": (1.0, 0.55),
    "ring": (-0.12, 0.3),
    "leaf": (-0.25, 0.3),
    "curl": (-0.1, 0.35),
    "dash": (0.5, 0.9),
}


def person_index(person_id: str | None) -> int:
    if not person_id:
        return 0
    tail = person_id.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _palette(style, index: int) -> np.ndarray:
    return np.asarray(style.colors[index % len(style.colors)], dtype=np.float32)


def _neon(curve: np.ndarray, color: np.ndarray, width: float, alpha: float) -> list:
    return neon_layers(curve, color, width, alpha)


# ----- llamarada -----


def draw_flame_burst(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if origin is None or envelope <= 0 or event is None:
        return
    key = (event.start_frame, event.target)
    if runtime.burst_key != key:
        # Nueva activación: otra forma de llamarada, fija para toda su vida.
        runtime.burst_key = key
        runtime.burst_seed = zlib.crc32(f"{style.seed_offset}:{event.start_frame}:{event.target}".encode()) & 0xFFFFFFFF
    torso = torso_pixels(points, height)
    # En primeros planos el torso es enorme; el tope evita que la llamarada tape el cuadro.
    radius = min(style.size * torso, MAX_BURST * height)
    grow = float(np.clip(runtime.active_frames / max(effect.triggers[0].hold * GROW, 1.0), 0.0, 1.0)) if effect.triggers else 1.0
    grow = 1.0 - (1.0 - grow) ** 2
    # Line boil: la forma tiembla cada `boil_frames` sin cambiar de identidad.
    boil = frame_index // max(style.boil_frames, 1)
    rng = np.random.default_rng(runtime.burst_seed)
    jitter = np.random.default_rng(runtime.burst_seed + boil * 7919)
    own = person_index(event.attacker)
    rival = person_index(event.receiver) if event.receiver else own + 1
    width = max(1.2, style.thickness * torso)
    hold = effect.triggers[0].hold if effect.triggers else 14
    age = float(np.clip(runtime.active_frames / max(hold, 1), 0.0, 1.0))
    # Las piezas se separan del golpe y suben mientras viven, como brasas que se dispersan.
    drift = radius * 0.5 * age
    rise = np.array([0.0, -radius * 0.45 * age])
    count = 4 + int(rng.integers(0, 3))
    base = float(rng.uniform(0, TAU))
    strokes = []
    for index in range(count):
        angle = base + index * TAU / count + float(rng.normal(0, 0.3))
        direction = np.array([np.cos(angle), np.sin(angle)])
        # Cada lengua nace lejos del centro: pétalos separados, no una maraña sobre el golpe.
        start = origin + direction * (radius * float(rng.uniform(0.22, 0.42)) + drift) + rise
        length = radius * float(rng.uniform(0.35, 0.65)) * grow
        curl = float(rng.choice([-1.0, 1.0]) * rng.uniform(0.4, 1.1))
        tongue = flame_tongue(start, angle, length, length * 0.17, curl, jitter)
        color = _palette(style, rival if index % 3 == 2 else own)
        strokes += _neon(tongue, color, width, envelope)
    # Óvalos sueltos alrededor del golpe.
    theta = np.linspace(0, TAU, 22)
    for _ in range(2):
        angle = float(rng.uniform(0, TAU))
        center = origin + np.array([np.cos(angle), np.sin(angle)]) * radius * float(rng.uniform(0.5, 0.9)) * (0.7 + 0.3 * grow) + rise
        size = radius * float(rng.uniform(0.1, 0.18)) * grow
        tilt = float(rng.uniform(0, np.pi))
        ellipse = np.stack([np.cos(theta) * size, np.sin(theta) * size * 0.65], axis=1)
        rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
        strokes += _neon(center + (ellipse * (1 + jitter.normal(0, 0.05, (22, 1)))) @ rot.T, _palette(style, own), width * 0.8, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


def flame_tongue(origin: np.ndarray, angle: float, length: float, width: float, curl: float, rng: np.random.Generator) -> np.ndarray:
    """Contorno cerrado de una lengua de fuego: base ancha junto al golpe, punta que se enrosca."""
    s = np.linspace(0.0, 1.0, 18)
    bend = angle + curl * s**2
    radial = 0.12 * length + 0.88 * length * s
    spine = origin + np.stack([np.cos(bend), np.sin(bend)], axis=1) * radial[:, None]
    tangent = np.gradient(spine, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-6)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    half = width * np.sin(np.pi * np.clip(s * 0.9 + 0.1, 0, 1)) ** 0.7 * (1 - s) ** 0.35
    half = half * (1 + rng.normal(0, 0.08, len(s)))
    left = spine + normal * half[:, None]
    right = spine - normal * half[:, None]
    return np.vstack([left, right[::-1], left[:1]])


# ----- chispas -----


def draw_spark_dashes(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    torso = torso_pixels(points, height)
    bits: list[Bit] = runtime.bits
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if event is not None and origin is not None and envelope > 0 and runtime.burst_key != (event.start_frame, event.target):
        runtime.burst_key = (event.start_frame, event.target)
        rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:{event.start_frame}".encode()) & 0xFFFFFFFF)
        color = person_index(event.attacker)
        for _ in range(min(14, SPARK_LIMIT - len(bits))):
            angle = float(rng.uniform(0, TAU))
            speed = torso * float(rng.uniform(0.05, 0.12)) * style.size * 2
            life = float(rng.uniform(8, 16))
            bits.append(Bit(float(origin[0]), float(origin[1]), np.cos(angle) * speed, np.sin(angle) * speed - torso * 0.02, life, life, torso * 0.04, color))
    _step(bits, gravity=torso * 0.006, drag=0.06)
    width = max(1.0, style.thickness * torso * 0.7)
    strokes = []
    for bit in bits:
        tail = np.array([bit.x - bit.vx * 1.6, bit.y - bit.vy * 1.6])
        strokes += _neon(np.array([tail, [bit.x, bit.y]]), _palette(style, bit.color), width, bit.life / bit.max_life)
    stroke_batch(layer, strokes, style.hdr_gain)


# ----- gotas -----


def draw_droplets(runtime, track: FrameRecord | None, points, frame_index: int, height: int, envelope: float, layer: np.ndarray) -> None:
    effect = runtime.effect
    style = effect.style
    torso = torso_pixels(points, height)
    bits: list[Bit] = runtime.bits
    joints = [token.strip() for token in effect.target.id.split(",") if token.strip()]
    for key, person in swoosh_keys(track, joints):
        point = points.get(key)
        velocity = points.get(f"vel:{key}")
        fast = point is not None and velocity is not None and joint_speed(track, key) >= style.min_speed
        if not fast:
            runtime.swoosh_stroke.pop(key, None)
            continue
        # Un golpe empieza cuando la mano supera el umbral; ahí se decide si suelta partículas
        # y de qué forma, una sola para todo el golpe.
        start = runtime.swoosh_stroke.setdefault(key, frame_index)
        seed = zlib.crc32(f"{style.seed_offset}:{key}:{start}".encode()) & 0xFFFFFFFF
        chooser = np.random.default_rng(seed)
        if float(chooser.random()) >= style.chance or envelope <= 0:
            continue
        shapes = [name for name in style.shapes if name in SHAPES] or ["drop"]
        shape = shapes[int(chooser.integers(0, len(shapes)))]
        gravity, inherit = SHAPES[shape]
        rng = np.random.default_rng(seed + frame_index)
        for _ in range(min(DROPLETS_PER_FRAME, DROPLET_LIMIT - len(bits))):
            spread = rng.normal(0, torso * 0.025, 2)
            life = float(rng.uniform(14, 26))
            size = min(torso * style.size * float(rng.uniform(0.05, 0.1)), MAX_BIT * height)
            spin = float(rng.choice([-1.0, 1.0]))
            bits.append(
                Bit(
                    float(point[0]),
                    float(point[1]),
                    float(velocity[0] * inherit + spread[0]),
                    float(velocity[1] * inherit + spread[1]),
                    life,
                    life,
                    size,
                    person,
                    shape,
                    gravity,
                    spin,
                )
            )
    _step(bits, gravity=torso * 0.012, drag=0.03)
    width = max(1.0, style.thickness * torso * 0.7)
    strokes = []
    for bit in bits:
        fade = min(1.0, 2.5 * bit.life / bit.max_life)
        for line in bit_outline(bit):
            strokes += _neon(line, _palette(style, bit.color), width, fade)
    stroke_batch(layer, strokes, style.hdr_gain * max(envelope, 0.0))


def bit_outline(bit: Bit) -> list[np.ndarray]:
    """Polilíneas de una partícula según su forma."""
    center = np.array([bit.x, bit.y])
    velocity = np.array([bit.vx, bit.vy])
    age = 1.0 - bit.life / max(bit.max_life, 1e-6)
    if bit.shape == "drop":
        return [teardrop(center, velocity, bit.size)]
    if bit.shape == "ring":
        theta = np.linspace(0, TAU, 16)
        tilt = bit.spin * (0.6 + age * 1.5)
        ellipse = np.stack([np.cos(theta), np.sin(theta) * 0.65], axis=1) * bit.size * 1.3
        rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
        return [center + ellipse @ rot.T]
    if bit.shape == "leaf":
        # Hoja de fuego pequeña, apuntando hacia arriba; rng fijo para que no parpadee.
        return [flame_tongue(center, -np.pi / 2 + bit.spin * 0.3, bit.size * 3.5, bit.size, bit.spin * 0.9, np.random.default_rng(0))]
    if bit.shape == "curl":
        theta = np.linspace(0, 2.5 * np.pi, 24)
        radius = bit.size * 1.6 * (1 - theta / (2.8 * np.pi))
        turn = bit.spin * (theta + age * 3.0)
        return [center + np.stack([np.cos(turn), np.sin(turn)], axis=1) * radius[:, None]]
    return [np.array([center - velocity * 1.6, center])]


def teardrop(center: np.ndarray, velocity: np.ndarray, radius: float) -> np.ndarray:
    """Contorno de gota: cabeza redonda hacia donde viaja y cola en punta detrás."""
    speed = float(np.linalg.norm(velocity))
    forward = velocity / speed if speed > 1e-6 else np.array([0.0, 1.0])
    side = np.array([-forward[1], forward[0]])
    angles = np.linspace(-0.62 * np.pi, 0.62 * np.pi, 14)
    head = center + (np.cos(angles)[:, None] * forward + np.sin(angles)[:, None] * side) * radius
    tail = center - forward * radius * (2.2 + min(speed / max(radius, 1e-6), 3.0) * 0.4)
    return np.vstack([tail, head, tail])


def _step(bits: list[Bit], gravity: float, drag: float) -> None:
    alive = []
    for bit in bits:
        bit.vx *= 1.0 - drag
        bit.vy = bit.vy * (1.0 - drag) + gravity * bit.gravity
        bit.x += bit.vx
        bit.y += bit.vy
        bit.life -= 1.0
        if bit.life > 0:
            alive.append(bit)
    bits[:] = alive
