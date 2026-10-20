"""Rayo fractal con continuidad temporal.

El eje va de la articulación al objetivo o, si no hay objetivo, a lo largo de la
velocidad de la mano. El quiebre sale de ruido 3D evaluado en (arco, rama, slot),
así el rayo cambia poco entre fotogramas y se re-siembra cada `reseed_every` con
fundido cruzado. Las ramas nacen en los puntos de subdivisión con grosor decreciente.

Opciones del estilo de glowing/video_51 en `style.lightning`: la cinta quebrada y plana
(`ribbon`), el rayo hasta el borde del cuadro (`to_edge`), el lazo que sigue a la mano (`trail`)
y los chispazos sobre el cuerpo (`crackle`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vfxglow.director.schema import Effect
from vfxglow.engine.anchors import joint_speed, joint_velocity, resolve_anchor, torso_pixels
from vfxglow.engine.noise import ValueNoise
from vfxglow.engine.particles import Particle, draw_particles, step_particles
from vfxglow.engine.raster import fill_polygon, sample_gradient, stroke_gradient, stroke_polyline


@dataclass
class BoltTree:
    segments: list[np.ndarray]
    widths: list[float]
    tips: list[np.ndarray]


def _edge_tip(origin: np.ndarray, effect: Effect, points: dict[str, np.ndarray], track, size: tuple[int, int]) -> np.ndarray | None:
    """Hasta el borde del cuadro en la dirección del antebrazo (codo → muñeca) o, sin codo, del
    movimiento de la mano (video_51, seg. 6,3)."""
    height, width = size
    joint = effect.target.id
    elbow = points.get(joint.replace("wrist", "elbow")) if joint.endswith("wrist") else None
    origin = np.asarray(origin, np.float64)
    if elbow is not None and float(np.linalg.norm(origin - elbow)) > 4:
        direction = origin - elbow
    else:
        direction = np.array(joint_velocity(track, joint), dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm < 1e-4:
        return None
    direction /= norm
    steps = [((width if direction[0] > 0 else 0) - origin[0]) / direction[0] if abs(direction[0]) > 1e-4 else np.inf,
             ((height if direction[1] > 0 else 0) - origin[1]) / direction[1] if abs(direction[1]) > 1e-4 else np.inf]
    return origin + direction * max(min(steps), 0.15 * height)


def _hand(points: dict[str, np.ndarray], event) -> np.ndarray | None:
    """La mano que lanza el rayo: la del gesto si el gesto es de una mano; si no (un pie, el
    cuerpo), la que más se mueve. El rayo nunca sale de un pie ni del cuerpo."""
    if event is not None:
        name = event.target.split(":")[-1]
        if name.endswith("_wrist"):
            for key in (event.target, name):
                if key in points:
                    return points[key]
    prefix = event.target.split(":")[0] + ":" if event is not None and ":" in event.target else ""
    best, speed = None, -1.0
    for side in ("left", "right"):
        key = f"{prefix}{side}_wrist"
        hand = points.get(key, points.get(f"{side}_wrist"))
        vel = points.get(f"vel:{key}", points.get(f"vel:{side}_wrist"))
        moving = float(np.linalg.norm(vel)) if vel is not None else 0.0
        if hand is not None and moving > speed:
            best, speed = hand, moving
    return best


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


def _shard(layer: np.ndarray, segment: np.ndarray, width: float, effect: Effect, envelope: float, seed: float) -> None:
    """La cinta quebrada y plana de video_51: ancha en los quiebres, fina entre ellos, con bordes
    disparejos (un lado más que el otro) y un núcleo claro adentro."""
    if len(segment) < 3 or width < 1.0 or envelope <= 0:
        return
    d = np.diff(segment, axis=0)
    heading = np.arctan2(d[:, 1], d[:, 0])
    bend = np.abs(np.angle(np.exp(1j * np.diff(heading))))
    bend = np.concatenate([[0.0], bend, [0.0]])
    t = np.linspace(0, 1, len(segment))
    wobble = 0.5 + 0.5 * np.sin(t * 23.0 + seed * 7.1) * np.sin(t * 9.0 + seed * 3.3)
    w = width * (0.15 + 0.85 * np.clip(bend / 0.9, 0.0, 1.0) * (0.5 + 0.5 * wobble)) * np.sin(np.pi * np.clip(t, 0.02, 0.98)) ** 0.35
    tangent = np.gradient(segment, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
    lean = 0.25 + 0.5 * (0.5 + 0.5 * np.sin(t * 17.0 + seed * 5.0))  # cuánto va a cada lado
    body = np.vstack([segment + normal * (w * lean)[:, None], (segment - normal * (w * (1.0 - lean))[:, None])[::-1]])
    # Sin ganancia HDR: el color plano de la referencia (con ganancia, al componer se iba al blanco).
    fill_polygon(layer, body, sample_gradient(effect.style.colors, 0.5), envelope, 1.0, feather=1.2)
    core = np.vstack([segment + normal * (w * lean * 0.3)[:, None], (segment - normal * (w * (1.0 - lean) * 0.3)[:, None])[::-1]])
    fill_polygon(layer, core, sample_gradient(effect.style.colors, 0.0), envelope, 1.0, feather=1.0)


def _draw_tree(layer: np.ndarray, tree: BoltTree, effect: Effect, envelope: float, width: float, ribbon: float = 0.0) -> None:
    hot = sample_gradient(effect.style.colors, 0.0)
    for k, (segment, scale) in enumerate(zip(tree.segments, tree.widths)):
        if ribbon > 0 and scale > 0.3:  # el tronco y las ramas grandes: cinta plana con un hilo claro
            _shard(layer, segment, ribbon * scale, effect, envelope, k * 1.7)
            stroke_polyline(layer, segment, hot, max(1.0, width * scale * 0.4), 1.0, envelope)
            continue
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
    event=None,
) -> None:
    effect = runtime.effect
    origin = _hand(points, event) if effect.style.lightning.hands_only else None
    if origin is None:
        origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if origin is None or envelope <= 0:
        step_particles(runtime.particles)
        draw_particles(layer, runtime.particles, effect, max(envelope, 0.15), runtime.kernels)
        return
    from vfxglow.engine.firebend import note_bolt

    note_bolt(frame_index)
    params = effect.style.lightning
    tip = _edge_tip(origin, effect, points, track, layer.shape[:2]) if params.to_edge else None
    if tip is None:
        tip = _tip(origin, effect, points, track, height)
    every = max(params.reseed_every, 1)
    slot = frame_index // every
    if slot != runtime.bolt_slot:
        runtime.bolt_prev = runtime.bolt_curr
        runtime.bolt_curr = build_bolt(origin, tip, runtime.noise, slot, effect)
        runtime.bolt_slot = slot
    phase = (frame_index % every) / every
    torso = torso_pixels(points, height)
    width = max(1.6, effect.style.thickness * torso)
    ribbon = params.ribbon * torso
    if runtime.bolt_prev is not None:
        _draw_tree(layer, runtime.bolt_prev, effect, envelope * (1.0 - phase), width, ribbon)
    if runtime.bolt_curr is not None:
        _draw_tree(layer, runtime.bolt_curr, effect, envelope * (0.35 + 0.65 * phase), width, ribbon)
        _spawn_sparks(runtime, runtime.bolt_curr.tips, envelope, width)
    if params.trail > 0:
        _lasso(runtime, layer, origin, slot, effect, envelope, width, ribbon, torso)
    if params.crackle > 0:
        _crackle(runtime, layer, points, slot, effect, envelope, width, torso)
    step_particles(runtime.particles)
    draw_particles(layer, runtime.particles, effect, envelope, runtime.kernels)


def _lasso(runtime, layer: np.ndarray, origin: np.ndarray, slot: int, effect: Effect, envelope: float, width: float, ribbon: float, torso: float) -> None:
    """Lazo de rayo sobre el recorrido reciente de la mano (video_51, seg. 5,1): al barrer el
    brazo, el rayo queda dibujado por donde pasó, quebrado como el resto."""
    path = runtime.swoosh.setdefault("_bolt_trail", [])
    if path and float(np.linalg.norm(origin - path[-1])) > 1.5 * torso:  # salto del detector
        path.clear()
    path.append(np.asarray(origin, np.float64).copy())
    del path[: -effect.style.lightning.trail]
    if len(path) < 4:
        return
    pts = np.array(path)
    if float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1))) < 0.8 * torso:  # casi quieta
        return
    # Exagerado alrededor de la mano (como el látigo de fuego): el lazo dobla el recorrido.
    pts = pts[-1] + (pts - pts[-1]) * 1.8
    pieces = [_displace(a, b, runtime.noise, slot, 40 + i, 2, effect.style.lightning.jitter, effect.style.noise.octaves) for i, (a, b) in enumerate(zip(pts, pts[1:]))]
    line = np.vstack([pieces[0]] + [piece[1:] for piece in pieces[1:]])
    hot = sample_gradient(effect.style.colors, 0.0)
    if ribbon > 0:
        _shard(layer, line, ribbon * 0.9, effect, envelope, 3.3)
        stroke_polyline(layer, line, hot, max(1.0, width * 0.4), 1.0, envelope)
        return
    stroke_gradient(layer, line, effect.style, max(1.0, width), envelope * 0.8)
    stroke_polyline(layer, line, hot, max(1.0, width * 0.3), effect.style.hdr_gain * envelope, envelope)


# Solo los brazos: el rayo sale de las manos y corre por los brazos (en piernas y cabeza no).
_LIMBS = (("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"), ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"))


def _crackle(runtime, layer: np.ndarray, points: dict[str, np.ndarray], slot: int, effect: Effect, envelope: float, width: float, torso: float) -> None:
    """Chispazos cortos que saltan sobre los brazos (video_51, seg. 5,4 y 6,6): un arco quebrado
    de un punto del brazo a otro, separado un poco del cuerpo."""
    bones = [(points[a], points[b]) for a, b in _LIMBS if a in points and b in points]
    if not bones:
        return
    rng = np.random.default_rng(slot * 7919 + 17)
    hot = sample_gradient(effect.style.colors, 0.0)
    for k in range(effect.style.lightning.crackle):
        a, b = bones[int(rng.integers(len(bones)))]
        along = b - a
        normal = np.array([-along[1], along[0]]) / max(float(np.linalg.norm(along)), 1e-6)
        side = rng.choice([-1.0, 1.0])
        start = a + along * rng.uniform(0.0, 0.5) + normal * side * rng.uniform(0.05, 0.2) * torso
        end = a + along * rng.uniform(0.6, 1.1) + normal * side * rng.uniform(0.1, 0.35) * torso
        arc = _displace(start, end, runtime.noise, slot, 80 + k, 3, 0.45, effect.style.noise.octaves)
        stroke_gradient(layer, arc, effect.style, max(1.0, width * 0.8), envelope * 0.9)
        stroke_polyline(layer, arc, hot, max(1.0, width * 0.25), effect.style.hdr_gain * envelope, envelope)
