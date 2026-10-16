"""Objetos entre la boca y las manos (adornos `type: adornment`, `style.shapes`).

Idea del usuario en dance_two_mens (seg. 11,8-12,7): agachado, una mano plana bajo el mentón y la
otra arriba, abierta. El análisis lo marca como `hand_chin` (el lado es la mano del mentón).

- `shofar`: un cuerno de guerra que sale de la boca y se curva hasta la otra mano (angosto en la
  boquilla, ancho en la campana, con anillos); de la campana salen las ondas del llamado.
- `snack`: un pedazo de pastel (o una pieza de carne) en la mano del mentón y una cuchara (o un
  tenedor, o un cuchillo) en la otra. Cuando las manos bajan de golpe hacia el piso, se le caen:
  giran, rebotan y el pastel deja migajas, antes de que él llegue al suelo.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

HAND_PROPS = ("shofar", "snack")
# Rapidez hacia abajo de las manos (anchos de hombros por segundo) que suelta lo que sostienen.
DROP_SPEED = 3.0


def _hands(body, event, frame, scale):
    """(boca, mano del mentón, mano extendida) en píxeles, o None."""
    center, across, down = frame
    nose = body.get("nose")
    mouth = body.get("mouth")
    if mouth is None:
        mouth = nose + down * 0.12 * scale if nose is not None else center - down * 0.45 * scale
    wrists = {s: body.get(f"{s}_wrist") for s in ("left", "right")}
    if any(w is None for w in wrists.values()):
        return None
    near = event.kind if event is not None and event.kind in wrists else min(wrists, key=lambda s: float(np.linalg.norm(wrists[s] - mouth)))
    far = "right" if near == "left" else "left"
    return mouth, wrists[near], wrists[far], near, far


def _bezier(a, c, b, n: int = 32) -> np.ndarray:
    q = np.linspace(0, 1, n)[:, None]
    return (1 - q) ** 2 * a + 2 * (1 - q) * q * c + q ** 2 * b


# ----- el cuerno de guerra -----


def _shofar(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    found = _hands(body, event, frame, scale)
    if found is None:
        return []
    mouth, _near, far_hand, _n, _f = found
    center, across, down = frame
    up = -down
    span = far_hand - mouth
    length = float(np.linalg.norm(span))
    if length < 0.3 * scale:
        return []
    side = np.array([-span[1], span[0]]) / length
    if float(np.dot(side, up)) < 0:
        side = -side  # se arquea hacia arriba, como un cuerno
    control = mouth + span * 0.5 + side * length * 0.38
    u = _phase(runtime, event)
    reach = _ease(_seg(u, 0.0, 0.18))  # el cuerno crece de la boca a la mano
    spine = _bezier(mouth, control, far_hand, 36)
    spine = spine[: max(int(len(spine) * reach), 3)]
    q = np.linspace(0, 1, 36)[: len(spine)] ** 2.0
    width = 0.022 * scale + 0.12 * scale * q
    tangent = np.gradient(spine, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
    upper, lower = spine + normal * width[:, None], spine - normal * width[:, None]
    body_poly = np.vstack([upper, lower[::-1]])
    fill_polygon(layer, body_poly, np.asarray(color, np.float32), alpha * 0.35, 0.9, feather=1.5)
    lines = [upper, lower]
    for k in range(2, len(spine) - 2, 5):  # anillos del cuerno
        lines.append(np.array([upper[k], lower[k]]))
    lines.append(np.array([upper[0], lower[0]]))  # la boquilla
    if reach > 0.95:
        tip, d = spine[-1], tangent[-1] / max(float(np.linalg.norm(tangent[-1])), 1e-6)
        n = np.array([-d[1], d[0]])
        t = np.linspace(0, TAU, 28)
        bell = tip + np.outer(np.cos(t) * width[-1] * 0.35, d) + np.outer(np.sin(t) * width[-1] * 1.5, n)
        fill_polygon(layer, bell, np.asarray(color, np.float32), alpha * 0.5, 0.9, feather=1.5)
        lines.append(bell)
        for k in range(3):  # el llamado: ondas que salen de la campana
            age = (frame_index * 0.08 + k / 3) % 1.0
            r = (0.15 + 0.9 * age) * scale
            arc = np.linspace(-0.6, 0.6, 16)
            wave = tip + np.outer(np.cos(arc) * r, d) + np.outer(np.sin(arc) * r * 1.2, n)
            if age < 0.9:
                lines.append(wave)
        splat(layer, float(tip[0]), float(tip[1]), width[-1] * 0.8, WHITE * 1.4, alpha, runtime.kernels)
    return lines


# ----- el bocado que se cae -----


def _cake(at, up, size) -> tuple[list[np.ndarray], np.ndarray]:
    """Una tajada de pastel (triángulo de lado) con capas, crema y una cereza."""
    side = np.array([-up[1], up[0]])
    tip, back_top, back_bottom = at - side * size, at + side * size * 0.8 + up * size * 0.7, at + side * size * 0.8
    tip_low = at - side * size - up * 0.0
    outline = np.array([tip_low, back_bottom, back_top, tip_low])
    layers = [np.array([tip_low + (back_top - tip_low) * f + up * 0.0, back_bottom + (back_top - back_bottom) * f]) for f in (0.35, 0.65)]
    q = np.linspace(0, 1, 12)
    frosting = np.array([tip_low + (back_top - tip_low) * v + up * np.sin(v * TAU * 2) * size * 0.06 for v in q])
    cherry_at = back_top - side * size * 0.25 + up * size * 0.2
    t = np.linspace(0, TAU, 14)
    cherry = cherry_at + np.stack([np.cos(t), np.sin(t)], axis=1) * size * 0.16
    stem = np.array([cherry_at + up * size * 0.15, cherry_at + up * size * 0.35 + side * size * 0.1])
    return [outline, *layers, frosting, cherry, stem], outline


def _meat(at, up, size) -> tuple[list[np.ndarray], np.ndarray]:
    """Una pieza de carne con su hueso (muslo de caricatura)."""
    side = np.array([-up[1], up[0]])
    t = np.linspace(0, TAU, 24)
    meat_c = at - side * size * 0.25
    meat = meat_c + np.outer(np.cos(t) * size * 0.75, side) + np.outer(np.sin(t) * size * 0.5, up)
    bone_a, bone_b = at + side * size * 0.4, at + side * size * 1.1
    knob = [bone_b + np.outer(np.cos(t[:13]) * size * 0.14, side) + np.outer(np.sin(t[:13]) * size * 0.14, up) + up * k * size * 0.14 for k in (-1, 1)]
    marks = [np.array([meat_c - side * size * 0.3 + up * k * size * 0.15, meat_c + up * k * size * 0.2]) for k in (-1, 1)]
    return [meat, np.array([bone_a, bone_b]), *knob, *marks], meat


def _utensil(kind: str, at, along, size) -> list[np.ndarray]:
    """Cuchara, tenedor o cuchillo con el mango en la mano y la punta hacia afuera."""
    n = np.array([-along[1], along[0]])
    handle = np.array([at - along * size * 0.3, at + along * size * 0.6])
    head = at + along * size * 0.95
    if kind == "spoon":
        t = np.linspace(0, TAU, 18)
        return [handle, head + np.outer(np.cos(t) * size * 0.32, along) + np.outer(np.sin(t) * size * 0.2, n)]
    if kind == "fork":
        lines = [handle, np.array([head - along * size * 0.3 - n * size * 0.18, head - along * size * 0.3 + n * size * 0.18])]
        lines += [np.array([head - along * size * 0.3 + n * size * k, head + along * size * 0.25 + n * size * k]) for k in (-0.18, -0.06, 0.06, 0.18)]
        return lines
    blade = np.array([at + along * size * 0.6 - n * size * 0.08, at + along * size * 1.5, at + along * size * 0.6 + n * size * 0.12])
    return [handle, blade]


def _snack(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    found = _hands(body, event, frame, scale)
    if found is None:
        return []
    mouth, near_hand, far_hand, near, far = found
    center, across, down = frame
    up = -down
    st = _activation(runtime, event, "snack", body)
    u = _phase(runtime, event)
    pick = zlib.crc32(f"{event.start_frame if event else 0}:{body.prefix}".encode()) % 3
    food, tool = (("cake", "spoon"), ("meat", "knife"), ("cake", "fork"))[pick]
    elbow = body.get(f"{far}_elbow")
    along = (far_hand - elbow) / max(float(np.linalg.norm(far_hand - elbow)), 1e-6) if elbow is not None else up
    size = 0.32 * scale
    food_at = near_hand + up * size * 0.45
    if "drop" not in st:  # se le caen cuando baja las manos de golpe hacia el piso (o al final)
        falling = []
        for s in (near, far):
            vel = body.points.get(f"vel:{body.prefix}{s}_wrist")
            falling.append(vel is not None and vel[1] / max(scale, 1e-6) > DROP_SPEED)
        if (u > 0.2 and any(falling)) or u > 0.85:
            st["drop"] = frame_index
            st["food0"], st["tool0"], st["along0"] = food_at.copy(), far_hand.copy(), along.copy()
    if "drop" not in st:
        drawing, outline = (_cake if food == "cake" else _meat)(food_at, up, size)
        fill_polygon(layer, outline, np.asarray(color, np.float32), alpha * 0.4, 0.9, feather=1.0)
        lines = drawing + _utensil(tool, far_hand, along, size)
        if food == "cake" and frame_index % 6 < 3:  # brillo de la crema
            splat(layer, float(food_at[0]), float(food_at[1] - size * 0.3), size * 0.12, WHITE * 1.3, alpha, runtime.kernels)
        return lines
    age = frame_index - st["drop"]
    feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
    floor = max(p[1] for p in feet) + 0.05 * scale if feet else st["food0"][1] + 2 * scale
    g = 0.02 * scale
    lines: list[np.ndarray] = []
    for k, (start, spin) in enumerate(((st["food0"], 0.25), (st["tool0"], -0.35))):
        y = start[1] + 0.5 * g * age * age
        bounce = 0.0
        if y > floor:  # rebota una vez, más bajito
            t_hit = np.sqrt(2 * (floor - start[1]) / g) if floor > start[1] else 0.0
            after = age - t_hit
            if after > 14:
                continue
            bounce = after
            y = floor - (0.25 * scale) * np.sin(min(after / 10.0, 1.0) * np.pi)
        x = start[0] + (k - 0.5) * 0.02 * scale * age
        at = np.array([x, y])
        turn = spin * (age if bounce == 0 else age * 0.3)
        tilted = np.array([up[0] * np.cos(turn) - up[1] * np.sin(turn), up[0] * np.sin(turn) + up[1] * np.cos(turn)])
        if k == 0:
            drawing, outline = (_cake if food == "cake" else _meat)(at, tilted, size)
            fill_polygon(layer, outline, np.asarray(color, np.float32), alpha * 0.4, 0.9, feather=1.0)
            lines += drawing
            if bounce and bounce < 4 and food == "cake":  # migajas al caer
                rng = np.random.default_rng(st["drop"])
                for _ in range(8):
                    a = rng.uniform(np.pi, TAU)
                    crumb = np.array([x, floor]) + np.array([np.cos(a), np.sin(a)]) * (0.1 + 0.08 * bounce) * scale
                    splat(layer, float(crumb[0]), float(crumb[1]), 0.012 * scale + 1, np.asarray(color, np.float32) * 1.4, alpha, runtime.kernels)
        else:
            d = st["along0"]
            d = np.array([d[0] * np.cos(turn) - d[1] * np.sin(turn), d[0] * np.sin(turn) + d[1] * np.cos(turn)])
            lines += _utensil(tool, at, d, size)
    return lines


def hand_prop(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    if shape == "shofar":
        return _shofar(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "snack":
        return _snack(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
