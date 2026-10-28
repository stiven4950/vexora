"""Pase de energía (adornos `type: adornment`, `style.shapes`): la energía nunca salta, viaja.

Leído en video_41 (seg. 6,0-7,1 y 13,0-13,9) y unpair_dance (seg. 11,3-11,9 y 25,8-27,4;
docs/referencias/):

- `arm_relay`: un pulso brillante con su estela sale de una mano, sube por el brazo, cruza el
  pecho por debajo del cuello y baja por el otro brazo hasta la otra mano, que se enciende al
  recibirlo. Empieza en la mano del gesto (o en la que estaba quieta, que es la que "manda").
- `hand_volley`: con las manos juntas jugando, la energía va y vuelve entre ellas en un arco; la
  mano que la tiene se contornea con sus dedos y destella al recibirla.
- `person_relay`: la energía recorre a una persona (sube al puño, baja por el torso y la pierna),
  sale por el pie en una onda por el piso, entra por el pie de la otra persona y sube hasta su
  mano. Sola, la onda se abre en el piso alrededor del pie.

Las estelas se rellenan de blanco y el color va en el halo (P11), como en engine/duo_fx.py.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.duo_fx import branched, fill_band
from vfxglow.engine.raster import splat

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
ENERGY_PASS = ("arm_relay", "hand_volley", "person_relay")
# Largo de la estela en fracción del recorrido, y ancho del pulso en anchos de hombros.
TRAIL = 0.22
PULSE_WIDTH = 0.07
# Un viaje de una mano a la otra en hand_volley, en fotogramas.
VOLLEY_FRAMES = 8
FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def _resample(points: list[np.ndarray], n: int = 80) -> np.ndarray:
    path = np.array(points, dtype=np.float64)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    if acc[-1] < 1e-6:
        return np.repeat(path[:1], n, axis=0)
    u = np.linspace(0.0, acc[-1], n)
    return np.stack([np.interp(u, acc, path[:, 0]), np.interp(u, acc, path[:, 1])], axis=1)


def _arm(body, side: str) -> list[np.ndarray] | None:
    """Mano, codo y hombro de un lado (la mano es el nudillo del medio si se ve)."""
    joints = [body.get(f"{side}_middle_mcp"), body.get(f"{side}_wrist"), body.get(f"{side}_elbow"), body.get(f"{side}_shoulder")]
    if joints[1] is None or joints[2] is None or joints[3] is None:
        return None
    return [j for j in joints if j is not None]


def _start_side(body, event, seed: int) -> str:
    for side in ("left", "right"):
        if event is not None and (event.kind == side or event.target.endswith(f":{side}")):
            return side
    speeds = {}
    for side in ("left", "right"):
        vel = body.points.get(f"vel:{body.prefix}{side}_wrist")
        speeds[side] = float(np.linalg.norm(vel)) if vel is not None else None
    if all(v is not None for v in speeds.values()) and abs(speeds["left"] - speeds["right"]) > 1e-3:
        return min(speeds, key=speeds.get)  # la mano quieta manda la energía a la que se mueve
    return ("left", "right")[seed % 2]


def _travel(path: np.ndarray, p: float, scale: float, layer, color, alpha, kernels) -> list[np.ndarray]:
    """El pulso en la fracción `p` del camino con su estela detrás: (líneas del tramo encendido)."""
    n = len(path)
    head = int(np.clip(p, 0.0, 1.0) * (n - 1))
    tail = max(int((p - TRAIL) * (n - 1)), 0)
    if head - tail < 2:  # todavía no sale: la energía se junta en el punto de partida
        at = path[head]
        splat(layer, float(at[0]), float(at[1]), 0.09 * scale, WHITE * 0.8 + np.asarray(color, np.float32) * 0.6, alpha, kernels)
        return []
    curve = path[tail:head + 1]
    widths = PULSE_WIDTH * scale * np.linspace(0.1, 1.0, len(curve)) ** 1.5  # fina atrás, gruesa en el pulso
    fill_band(layer, curve, widths, alpha)
    at = path[head]
    splat(layer, float(at[0]), float(at[1]), 0.09 * scale, WHITE * 0.8 + np.asarray(color, np.float32) * 0.6, alpha, kernels)
    return [curve]


def _arrival(at: np.ndarray, amount: float, scale: float, rng, layer, color, alpha, kernels) -> list[np.ndarray]:
    """La mano (o el pie) que recibe: se enciende y suelta rayitos."""
    if amount <= 0:
        return []
    splat(layer, float(at[0]), float(at[1]), (0.08 + 0.1 * amount) * scale, WHITE * 0.7 + np.asarray(color, np.float32) * 0.7, alpha * (1.0 - 0.6 * amount), kernels)
    lines: list[np.ndarray] = []
    for k in range(5):
        angle = TAU * k / 5 + rng.uniform(-0.3, 0.3)
        lines += branched(at, np.array([np.cos(angle), np.sin(angle)]), scale * (0.12 + 0.12 * amount), rng, 1)
    return lines


def _arm_relay(body, frame, scale, frame_index, runtime, layer, color, alpha, event, seed) -> list[np.ndarray]:
    start = _start_side(body, event, seed)
    other = "right" if start == "left" else "left"
    a, b = _arm(body, start), _arm(body, other)
    if a is None or b is None:
        return []
    center, _across, down = frame
    neck = center - down * 0.08 * scale  # cruza por debajo del cuello
    path = _resample([*a, neck, *b[::-1]])
    u = _phase(runtime, event)
    p = _ease(_seg(u, 0.05, 0.7))
    rng = np.random.default_rng((seed + frame_index // 2) & 0xFFFFFFFF)
    lines = _travel(path, p, scale, layer, color, alpha, runtime.kernels) if u < 0.8 else []  # llegó: la estela se apaga
    lines += _arrival(path[-1], _seg(u, 0.7, 1.0), scale, rng, layer, color, alpha, runtime.kernels)
    return lines


def _glove(body, side: str, scale: float) -> list[np.ndarray]:
    """Contorno de la mano con sus dedos (si se ven los puntos de la mano)."""
    from vfxglow.engine.face_toon import _finger_outline

    lines = []
    for finger in FINGERS:
        joints = ("cmc", "mcp", "ip", "tip") if finger == "thumb" else ("mcp", "pip", "dip", "tip")
        chain = [body.get(f"{side}_{finger}_{j}") for j in joints]
        chain = [c for c in chain if c is not None]
        if len(chain) >= 2:
            lines.append(_finger_outline(chain, 0.035 * scale))
    return lines


def _hand(body, side: str) -> np.ndarray | None:
    knuckle = body.get(f"{side}_middle_mcp")
    return knuckle if knuckle is not None else body.get(f"{side}_wrist")


def _hand_volley(body, frame, scale, frame_index, runtime, layer, color, alpha, event, seed) -> list[np.ndarray]:
    first = _start_side(body, event, seed)
    second = "right" if first == "left" else "left"
    a, b = _hand(body, first), _hand(body, second)
    if a is None or b is None:
        return []
    age = runtime.active_frames
    trip, t = divmod(age, VOLLEY_FRAMES)
    src, dst, holder = (a, b, second) if trip % 2 == 0 else (b, a, first)
    if t < VOLLEY_FRAMES * 0.3:  # recién llegó: la tiene la mano de origen
        holder = first if holder == second else second
    span = dst - src
    bulge = np.array([-span[1], span[0]]) * 0.25
    if bulge[1] > 0:
        bulge = -bulge  # el arco va por arriba
    q = np.linspace(0, 1, 40)[:, None]
    arc = (1 - q) ** 2 * src + 2 * (1 - q) * q * ((src + dst) / 2 + bulge) + q ** 2 * dst
    p = t / VOLLEY_FRAMES
    lines = _travel(arc, p, scale, layer, color, alpha, runtime.kernels)
    lines += _glove(body, holder, scale)
    if t == VOLLEY_FRAMES - 1:  # destello al recibir
        splat(layer, float(dst[0]), float(dst[1]), 0.16 * scale, WHITE * 0.9, alpha, runtime.kernels)
    return lines


def _partner(body) -> str | None:
    """El prefijo de la otra persona más cercana ("person_1:"), o None si está sola."""
    hips = body.mid("left_hip", "right_hip")
    if hips is None:
        return None
    best, best_d = None, None
    for key, value in body.points.items():
        if ":" not in key or key.startswith(("vel:", body.prefix)) or not key.endswith("left_hip"):
            continue
        prefix = key[: -len("left_hip")]
        d = float(np.linalg.norm(value - hips))
        if best_d is None or d < best_d:
            best, best_d = prefix, d
    return best


def _leg(body, side: str, prefix: str | None = None) -> list[np.ndarray] | None:
    get = (lambda name: body.points.get(f"{prefix}{name}")) if prefix else body.get
    joints = [get(f"{side}_wrist"), get(f"{side}_elbow"), get(f"{side}_shoulder"), get(f"{side}_hip"), get(f"{side}_knee"), get(f"{side}_ankle")]
    return joints if all(j is not None for j in joints) else None


def _person_relay(body, frame, scale, frame_index, runtime, layer, color, alpha, event, seed) -> list[np.ndarray]:
    side = _start_side(body, event, seed)
    mine = _leg(body, side)
    if mine is None:
        return []
    partner = _partner(body)
    other = None
    if partner is not None:
        foot = mine[-1]
        options = [s for s in ("left", "right") if _leg(body, s, partner) is not None]
        if options:
            near = min(options, key=lambda s: float(np.linalg.norm(body.points[f"{partner}{s}_ankle"] - foot)))
            other = _leg(body, near, partner)
    u = _phase(runtime, event)
    rng = np.random.default_rng((seed + frame_index // 2) & 0xFFFFFFFF)
    floor_y = max(p[1] for p in ([mine[-1]] + ([other[-1]] if other else [])))
    if other is None:  # sola: baja hasta el pie y la onda se abre en el piso
        path = _resample(mine)
        p = _ease(_seg(u, 0.05, 0.6))
        lines = _travel(path, p, scale, layer, color, alpha, runtime.kernels) if u < 0.7 else []
        ring = _seg(u, 0.6, 1.0)
        if ring > 0:
            t = np.linspace(0, TAU, 48)
            lines.append(np.stack([mine[-1][0] + np.cos(t) * scale * (0.2 + 1.2 * ring), floor_y + np.sin(t) * scale * (0.05 + 0.25 * ring)], axis=1))
        return lines
    a_foot, b_foot = mine[-1], other[-1]
    x = np.linspace(0, 1, 24)
    wave = np.stack([a_foot[0] + (b_foot[0] - a_foot[0]) * x, floor_y + np.sin(x * TAU * 2) * 0.06 * scale * np.sin(x * np.pi)], axis=1)
    raw = [*mine, *wave, *other[::-1]]
    path = _resample(raw, 160)
    p = _ease(_seg(u, 0.05, 0.8))
    lines = _travel(path, p, scale, layer, color, alpha, runtime.kernels) if u < 0.9 else []
    acc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(np.array(raw), axis=0), axis=1))])
    for index, at in ((len(mine) - 1, a_foot), (len(mine) + len(wave), b_foot)):  # el pie que la suelta y el que la recibe
        flare = float(np.clip(1.0 - abs(p - acc[index] / max(acc[-1], 1e-6)) / 0.06, 0.0, 1.0))
        if flare > 0:
            splat(layer, float(at[0]), float(at[1]), 0.18 * scale * flare, WHITE * 0.9, alpha * flare, runtime.kernels)
    lines += _arrival(path[-1], _seg(u, 0.8, 1.0), scale, rng, layer, color, alpha, runtime.kernels)
    return lines


def energy_pass(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    seed = zlib.crc32(f"{shape}:{body.prefix}:{event.start_frame if event else 0}".encode())
    if shape == "arm_relay":
        return _arm_relay(body, frame, scale, frame_index, runtime, layer, color, alpha, event, seed)
    if shape == "hand_volley":
        return _hand_volley(body, frame, scale, frame_index, runtime, layer, color, alpha, event, seed)
    if shape == "person_relay":
        return _person_relay(body, frame, scale, frame_index, runtime, layer, color, alpha, event, seed)
    return []
