"""Lo que aparece en la cabeza y alrededor de la persona (adornos `type: adornment`).

- snake_band: una balaca de dos serpientes trenzadas que serpentean por la frente; sus cabezas se
  levantan al frente, se mecen y sacan la lengua.
- snake_crown: serpientes que nacen del nacimiento del pelo y se retuercen hacia afuera.
- red_horns: cachos rojos con anillos que crecen desde la frente y sueltan brasas por la punta.
- death_hook: el gancho de la muerte: una guadaña enorme entra por un lado, se detiene junto al
  cuello, un brillo recorre el filo y se retira.
- skeleton_dance: esqueletos pequeños que suben por los lados y bailan.
- fairies: hadas que vuelan alrededor de la persona con su estela de polvo, por delante y por detrás
  (Halloween: `ambient` de la temporada). Van y vienen en oleadas por su cuenta: no ocupan el lugar
  del efecto de turno.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import fine, melt
from vfxglow.engine.duo_fx import body_mask
from vfxglow.engine.face_glow import WHITE, Face, _seed, _trim
from vfxglow.engine.raster import fill_polygon, splat
from vfxglow.engine.season import _star
from vfxglow.engine.swoosh import normals

TAU = 2.0 * np.pi
BEASTS = ("snake_band", "snake_crown", "red_horns", "death_hook", "skeleton_dance", "fairies")
HEAD_BEASTS = ("snake_band", "snake_crown", "red_horns")
SNAKES = ("snake_band", "snake_crown")
SNAKE_GREEN = np.array([0.3, 1.0, 0.4], np.float32)
SNAKE_GOLD = np.array([1.0, 0.8, 0.2], np.float32)
TONGUE = np.array([1.0, 0.15, 0.3], np.float32)
HORN_RED = np.array([1.0, 0.07, 0.05], np.float32)
EMBER = np.array([1.0, 0.45, 0.1], np.float32)
BONE = np.array([0.8, 0.95, 1.0], np.float32)
BLADE = np.array([0.6, 0.9, 1.0], np.float32)
FAIRY_COLORS = tuple(np.array(c, np.float32) for c in ((1.0, 0.45, 0.85), (0.45, 1.0, 0.8), (1.0, 0.85, 0.3), (0.65, 0.5, 1.0)))
# Oleadas de hadas: cuadros del ciclo, cuántos vuelan y cuánto tardan en llegar e irse.
FAIRY_PERIOD = 420
FAIRY_ON = 210
FAIRY_FADE = 30
FAIRIES = 4
TRAIL = 12


def _snake(spine: np.ndarray, width: float, tint, frame_index: int, seed: int, layer, alpha: float, kernels) -> list:
    """Cuerpo con su contorno y su patrón de escamas; la cabeza y la lengua al final de `spine`."""
    if len(spine) < 3:
        return []
    n = normals(spine)
    q = np.linspace(0.0, 1.0, len(spine))
    half = width * (0.25 + 0.75 * np.sin(np.pi * np.clip(q * 0.92 + 0.04, 0, 1)) ** 0.6)
    left, right = spine + n * half[:, None], spine - n * half[:, None]
    body = np.vstack([left, right[::-1]])
    fill_polygon(layer, body, tint * 0.4, alpha * 0.45, 1.0, feather=1.0)
    out: list = [(left, tint), (right, tint)]
    zig = np.array([(left if k % 2 else right)[i] for k, i in enumerate(range(0, len(spine), 3))])
    if len(zig) >= 2:
        out.append((zig, tint * 0.7))
    tip, d = spine[-1], spine[-1] - spine[-3]
    d = d / max(float(np.linalg.norm(d)), 1e-6)
    s = np.array([-d[1], d[0]])
    w = width * 1.5
    head = np.array([tip - d * w * 0.3 + s * w * 0.55, tip + d * w * 0.5 + s * w * 0.95, tip + d * w * 1.5 + s * w * 0.45, tip + d * w * 1.95,
                     tip + d * w * 1.5 - s * w * 0.45, tip + d * w * 0.5 - s * w * 0.95, tip - d * w * 0.3 - s * w * 0.55])
    fill_polygon(layer, head, tint * 0.5, alpha * 0.6, 1.0, feather=1.0)
    out.append((np.vstack([head, head[:1]]), tint))
    for sign in (-1.0, 1.0):
        eye = tip + d * w * 0.8 + s * sign * w * 0.42
        splat(layer, float(eye[0]), float(eye[1]), max(w * 0.13, 0.7), SNAKE_GOLD, alpha, kernels)
    if (frame_index // 6 + seed) % 3 != 2:  # la lengua sale y entra
        mouth = tip + d * w * 1.95
        fork = mouth + d * w * 0.9
        out.append((np.stack([mouth, fork]), TONGUE))
        for sign in (-1.0, 1.0):
            out.append((np.stack([fork, fork + (d + s * sign * 0.6) * w * 0.45]), TONGUE))
    return out


def _band(face: Face, u: float, frame_index: int, layer, alpha: float, kernels, seed: int) -> list:
    """Dos serpientes que vienen de las sienes por la frente, trenzadas, y se levantan al frente."""
    height = face.local("forehead_top", (0.0, -1.05))[1] * 0.78
    grow = _ease(_seg(u, 0.0, 0.2))
    out: list = []
    for sign, tint in ((-1.0, SNAKE_GREEN), (1.0, SNAKE_GOLD)):
        q = np.linspace(0.0, 1.0, 46)
        # Por la frente, de una sien al centro, con una onda que corre hacia la cabeza.
        x = sign * 1.12 * (1.0 - q)
        y = height + 0.2 * (x / 1.12) ** 2 + 0.085 * sign * np.sin(q * 15.0 - frame_index * 0.28) * (0.35 + 0.65 * np.sin(np.pi * q))
        # La parte final se levanta y se mece; las dos cabezas se miran al frente.
        rise = np.clip((q - 0.72) / 0.28, 0.0, 1.0)
        x = x + sign * rise * 0.28 + np.sin(frame_index * 0.09 + sign) * 0.12 * rise**2
        y = y - rise * (0.62 + 0.06 * np.sin(frame_index * 0.13 + sign))
        spine = face.place(np.stack([x, y], axis=1))
        keep = max(int(len(spine) * grow), 4)
        out += _snake(spine[:keep], 0.05 * face.unit, tint, frame_index, seed + int(sign), layer, alpha, kernels)
    return out


def _crown(face: Face, u: float, frame_index: int, layer, alpha: float, kernels, seed: int) -> list:
    rng = np.random.default_rng(seed)
    top = face.local("forehead_top", (0.0, -1.05))[1]
    out: list = []
    count = 7
    for k in range(count):
        a = -np.pi * (0.1 + 0.8 * k / (count - 1))
        root = np.array([1.02 * np.cos(a), 0.05 + (0.05 - top) * np.sin(a)])
        out_dir = np.array([np.cos(a), np.sin(a)])
        side = np.array([-out_dir[1], out_dir[0]])
        length = rng.uniform(1.0, 1.55)
        speed, phase = rng.uniform(0.18, 0.3), rng.uniform(0, TAU)
        grow = _ease(_seg(u, k * 0.03, k * 0.03 + 0.2))
        if grow <= 0:
            continue
        q = np.linspace(0.0, 1.0, 34)[:, None]
        wave = np.sin(q * 9.0 - frame_index * speed + phase) * (0.05 + 0.2 * q)
        local = root + out_dir * q * length * grow + side * wave * grow
        tint = SNAKE_GREEN if k % 2 == 0 else SNAKE_GOLD
        out += _snake(face.place(local), 0.042 * face.unit, tint, frame_index, seed + k, layer, alpha, kernels)
    return out


def _bezier(a, b, c, n: int = 24) -> np.ndarray:
    q = np.linspace(0.0, 1.0, n)[:, None]
    return (1 - q) ** 2 * np.asarray(a) + 2 * (1 - q) * q * np.asarray(b) + q**2 * np.asarray(c)


def _horns(face: Face, u: float, frame_index: int, layer, alpha: float, kernels) -> list:
    top = face.local("forehead_top", (0.0, -1.05))[1]
    grow = _ease(_seg(u, 0.0, 0.16))
    out: list = []
    for sign in (-1.0, 1.0):
        base = np.array([0.42 * sign, top * 0.98])
        spine = _bezier(base, base + [sign * 0.85, -0.2], base + [sign * 0.62, -1.3], 30)
        spine = spine[: max(int(len(spine) * grow), 3)]
        n = normals(spine)
        half = 0.13 * (1.0 - np.linspace(0.0, 1.0, len(spine)) ** 1.4) + 0.006
        left, right = spine + n * half[:, None], spine - n * half[:, None]
        outline = face.place(np.vstack([left, right[::-1]]))  # abierto en la base: nace de la frente
        fill_polygon(layer, outline, HORN_RED * 0.6, alpha * 0.45, 1.0, feather=1.2)
        out.append((outline, HORN_RED))
        for k in range(5, len(spine) - 4, 4):  # los anillos del cacho, combados
            d = spine[k + 1] - spine[k - 1]
            d = d / max(float(np.linalg.norm(d)), 1e-6)
            out.append((face.place(_bezier(left[k], spine[k] - d * half[k] * 0.9, right[k], 7)), HORN_RED * 0.55))
        tip = face.place(spine[-1:])[0]
        for k in range(7):
            age = (frame_index * 0.05 + k / 7.0) % 1.0
            at = tip + (-face.uy / face.unit * age * 0.75 + face.ux / face.unit * np.sin(age * 9.0 + k) * 0.07) * face.unit
            splat(layer, float(at[0]), float(at[1]), 0.02 * face.unit + 0.5, EMBER * 1.3, alpha * (1 - age) * grow, kernels)
    return out


def _scythe(face: Face, u: float, frame_index: int, layer, color, alpha: float, kernels, rng) -> list:
    side = 1.0 if rng.uniform() < 0.5 else -1.0
    across, down = face.ux / face.unit, face.uy / face.unit
    unit = face.unit
    neck = face.at("chin", (0.0, 1.6)) + down * 0.35 * unit
    grip = neck + (across * side * 3.0 + down * 6.0) * unit  # el mango sale por abajo del cuadro
    top = neck + (across * side * 2.1 - down * 1.5) * unit
    tip = neck + across * side * 0.15 * unit  # la punta queda junto al cuello
    edge = _bezier(top, top + (tip - top) * 0.45 - down * 1.1 * unit - across * side * 0.3 * unit, tip)
    back = _bezier(tip, top + (tip - top) * 0.52 - down * 0.55 * unit + across * side * 0.05 * unit, top - across * side * 0.1 * unit)
    arrive = _ease(_seg(u, 0.0, 0.2))
    leave = _ease(_seg(u, 0.72, 0.95))
    angle = side * (1.0 - arrive + 1.2 * leave) * 0.9  # gira alrededor del mango: entra, y se la lleva
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])

    def turn(points: np.ndarray) -> np.ndarray:
        return grip + (np.asarray(points, dtype=np.float64).reshape(-1, 2) - grip) @ rot.T

    edge_px, back_px = turn(edge), turn(back)
    blade = np.vstack([edge_px, back_px])
    fill_polygon(layer, blade, BLADE * 0.5, alpha * 0.28, 1.0, feather=1.5)
    tint = np.asarray(color, np.float32)
    out: list = [(np.vstack([blade, blade[:1]]), BLADE), (turn(np.array([top, grip])), tint)]
    collar = top + (grip - top) * 0.05
    out.append((turn(np.array([collar + across * 0.2 * unit, collar - across * 0.2 * unit])), tint))
    shine = _seg(u, 0.26, 0.6)
    if 0.0 < shine < 1.0:  # el brillo corre por el filo
        at = edge_px[int(shine * (len(edge_px) - 1))]
        splat(layer, float(at[0]), float(at[1]), 0.16 * unit, WHITE, alpha, kernels)
        for line in ((at - across * 0.34 * unit, at + across * 0.34 * unit), (at - down * 0.34 * unit, at + down * 0.34 * unit)):
            out.append((np.array(line), WHITE * 0.9))
    for k in range(16):  # humo frío que cae del filo
        age = (frame_index * 0.03 + k / 16.0) % 1.0
        at = edge_px[k * len(edge_px) // 16] + (down * age * 1.2 + across * np.sin(age * 7.0 + k) * 0.08) * unit
        splat(layer, float(at[0]), float(at[1]), (0.025 + 0.05 * age) * unit + 0.5, BLADE * 0.7, alpha * 0.4 * (1 - age), kernels)
    return out


def _skeleton(hip: np.ndarray, size: float, beat: float, tint) -> list:
    """Un esqueleto de frente en pose de baile. `beat` avanza el baile."""
    sway = np.sin(beat) * 0.1
    neck = hip + np.array([sway, -0.92]) * size
    skull = neck + np.array([sway * 0.6, -0.26]) * size
    t = np.linspace(0, TAU, 16)
    out: list = [(skull + np.stack([np.cos(t) * 0.19, np.sin(t) * 0.22], axis=1) * size, tint)]
    for sign in (-1.0, 1.0):
        socket = skull + np.array([sign * 0.08, -0.02]) * size
        out.append((socket + np.stack([np.cos(t) * 0.05, np.sin(t) * 0.05], axis=1) * size, tint))
    teeth = skull + np.array([0.0, 0.17]) * size
    out.append((np.array([teeth + [-0.1 * size, 0.0], teeth + [0.1 * size, 0.0]]), tint))
    spine = np.linspace(neck, hip, 8)
    out.append((spine, tint))
    for k in range(1, 5):  # costillas
        y = spine[k]
        wide = (0.3 - 0.03 * k) * size
        for sign in (-1.0, 1.0):
            out.append((_bezier(y, y + [sign * wide, -0.02 * size], y + [sign * wide * 0.7, 0.1 * size], 7), tint))
    out.append((np.array([hip + [-0.2 * size, 0.04 * size], hip, hip + [0.2 * size, 0.04 * size]]), tint))
    for sign in (-1.0, 1.0):
        arm_beat = np.sin(beat + (sign > 0) * np.pi)
        shoulder = neck + np.array([sign * 0.32, 0.08]) * size
        elbow = shoulder + np.array([sign * 0.3, 0.08 - 0.32 * arm_beat]) * size
        hand = elbow + np.array([sign * 0.18, -0.34 - 0.2 * arm_beat]) * size
        out.append((np.array([neck, shoulder, elbow, hand]), tint))
        leg_beat = np.sin(beat * 2.0 + (sign > 0) * np.pi)
        pelvis = hip + np.array([sign * 0.17, 0.04]) * size
        knee = pelvis + np.array([sign * 0.1, 0.42 - 0.1 * max(leg_beat, 0.0)]) * size
        foot = knee + np.array([sign * 0.04, 0.46 - 0.2 * max(leg_beat, 0.0)]) * size
        out.append((np.array([pelvis, knee, foot, foot + [sign * 0.14 * size, 0.0]]), tint))
    return out


def _skeletons(face: Face, u: float, frame_index: int, layer, rng) -> list:
    height, width = layer.shape[:2]
    center = face.place([(0.0, 0.4)])[0]
    size = min(1.5 * face.unit, height * 0.16)
    rise = _ease(_seg(u, 0.0, 0.18)) * (1.0 - _ease(_seg(u, 0.9, 1.0)))
    out: list = []
    for k, (offset, delay) in enumerate(((-2.6, 0.0), (2.6, 0.06), (-4.1, 0.1), (4.1, 0.03))):
        x = center[0] + offset * face.unit
        if not size * 0.5 < x < width - size * 0.5:
            x = float(np.clip(x, size * 0.6, width - size * 0.6)) if k < 2 else -1.0
        if x < 0:
            continue
        lift = rise * _ease(_seg(u, delay, delay + 0.2))
        hip = np.array([x, height + size * 0.1 - lift * size * 1.15])
        tint = BONE if k % 2 == 0 else np.array([0.6, 1.0, 0.7], np.float32)
        out += _skeleton(hip, size, frame_index * 0.2 + k * 1.3, tint)
    return out


def _fairy_at(center: np.ndarray, unit: float, frame: float, k: int) -> tuple[np.ndarray, float]:
    """La posición del hada `k` en el cuadro `frame` y qué tan adelante va (-1 a 1)."""
    direction = 1.0 if k % 2 == 0 else -1.0
    a = frame * 0.042 * direction + TAU * k / FAIRIES + 0.6 * np.sin(frame * 0.017 + k)
    depth = float(np.sin(a))
    radius = (2.0 + 0.35 * np.sin(frame * 0.023 + 2.0 * k)) * unit
    y = 1.35 * depth + 0.25 * np.sin(a * 2.0 + k) + 0.3 * np.sin(frame * 0.012 + k * 1.7)  # por delante, a la altura del pecho
    return center + np.array([np.cos(a) * radius, y * unit]), depth


def _wing(root: np.ndarray, angle: float, length: float, wide: float) -> np.ndarray:
    """Un ala en forma de gota, de la espalda hacia afuera."""
    q = np.concatenate([np.linspace(0, 1, 9), np.linspace(1, 0, 9)[1:]])
    sign = np.concatenate([np.ones(9), -np.ones(8)])
    bulge = np.sin(np.pi * q**0.75) * wide * sign
    d = np.array([np.cos(angle), np.sin(angle)])
    return root + np.outer(q * length, d) + np.outer(bulge, [-d[1], d[0]])


def _fairy(at: np.ndarray, size: float, flap: float, heading: float, tint) -> list[np.ndarray]:
    """Un hada chiquita: cabeza, vestido, varita con estrella y cuatro alas que aletean."""
    back = at + np.array([0.0, -0.1]) * size
    spread = 0.25 + 0.55 * abs(flap)
    lines = []
    for sign in (-1.0, 1.0):
        up = -np.pi / 2 + sign * (0.55 + spread)
        down = np.pi / 2 - sign * (0.5 + spread * 0.7)
        lines.append(_wing(back, up, size * 1.15, size * 0.3))
        lines.append(_wing(back, down, size * 0.72, size * 0.2))
    t = np.linspace(0, TAU, 12)
    lines.append(at + np.array([0.0, -0.42]) * size + np.stack([np.cos(t), np.sin(t)], axis=1) * size * 0.15)
    lines.append(np.array([at + [0.0, -0.27 * size], at + [heading * 0.2 * size, 0.42 * size], at + [-heading * 0.2 * size, 0.42 * size], at + [0.0, -0.27 * size]]))
    hand = at + np.array([heading * 0.48, -0.2]) * size
    lines.append(np.array([at + [0.0, -0.15 * size], hand]))
    lines.append(_star(hand + np.array([heading * 0.08, -0.08]) * size, size * 0.14))
    return lines


def _fairies(face: Face, body, scale: float, frame_index: int, layer, alpha: float, kernels) -> list:
    wave = frame_index % FAIRY_PERIOD
    if wave >= FAIRY_ON:
        return []
    swell = min(wave / FAIRY_FADE, (FAIRY_ON - wave) / FAIRY_FADE, 1.0)
    center = face.place([(0.0, 0.5)])[0]
    mask = body_mask(body, layer.shape[:2], scale)
    h, w = layer.shape[:2]
    arrive = 1.0 + 2.2 * (1.0 - _ease(float(np.clip(swell, 0.0, 1.0))))  # llegan desde lejos y se van
    for k in range(FAIRIES):
        at, depth = _fairy_at(center, face.unit * arrive, float(frame_index), k)
        tint = FAIRY_COLORS[k % len(FAIRY_COLORS)]
        behind = depth < 0 and mask is not None and mask[int(np.clip(at[1], 0, h - 1)), int(np.clip(at[0], 0, w - 1))]
        for j in range(1, TRAIL + 1):  # polvo que queda atrás y cae
            past, past_depth = _fairy_at(center, face.unit * arrive, float(frame_index - j * 2), k)
            past = past + np.array([np.sin(j * 2.3 + k) * 0.05, j * 0.028]) * face.unit
            if past_depth < 0 and mask is not None and mask[int(np.clip(past[1], 0, h - 1)), int(np.clip(past[0], 0, w - 1))]:
                continue
            twinkle = 0.6 + 0.4 * np.sin(frame_index * 0.9 + j * 1.9)
            splat(layer, float(past[0]), float(past[1]), (0.018 * (1 - j / (TRAIL + 1)) + 0.01) * face.unit + 0.5, tint * 1.3, alpha * twinkle * (1 - j / (TRAIL + 1)), kernels)
        if behind:
            continue  # detrás de la persona
        size = face.unit * 0.42 * (0.78 + 0.28 * depth)
        splat(layer, float(at[0]), float(at[1]), size * 0.34, tint, alpha * 0.28, kernels)
        ahead, _ = _fairy_at(center, face.unit * arrive, float(frame_index + 2), k)
        heading = 1.0 if ahead[0] >= at[0] else -1.0
        fine(_fairy(at, size, float(np.sin(frame_index * 1.3 + k)), heading, tint), tint, alpha, layer)
    return []


def head_beast(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    if shape == "fairies":
        return _fairies(face, body, scale, frame_index, layer, alpha, runtime.kernels)
    u = _phase(runtime, event)
    seed = _seed(shape, body, event)
    rng = np.random.default_rng(seed)
    if shape == "snake_band":
        items = _band(face, u, frame_index, layer, alpha, runtime.kernels, seed)
    elif shape == "snake_crown":
        items = _crown(face, u, frame_index, layer, alpha, runtime.kernels, seed)
    elif shape == "red_horns":
        items = _horns(face, u, frame_index, layer, alpha, runtime.kernels)
    elif shape == "death_hook":
        return _scythe(face, u, frame_index, layer, color, alpha, runtime.kernels, rng)
    else:
        return _skeletons(face, u, frame_index, layer, rng)
    return melt(items, u, face, layer, color, alpha, runtime.kernels, seed)
