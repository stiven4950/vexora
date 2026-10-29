"""Objetos entre la boca y las manos (adornos `type: adornment`, `style.shapes`).

Idea del usuario en dance_two_mens (seg. 11,8-12,7): agachado, una mano plana bajo el mentón y la
otra arriba, abierta. El análisis lo marca como `hand_chin` (el lado es la mano del mentón).

- `shofar`: un cuerno de guerra que sale de la boca y se curva hasta la otra mano (angosto en la
  boquilla, ancho en la campana, con anillos); de la campana salen las ondas del llamado.
- `snack`: un pedazo de pastel (o una pieza de carne) en la mano del mentón y una cuchara (o un
  tenedor, o un cuchillo) en la otra. Cuando las manos bajan de golpe hacia el piso, se le caen:
  giran, rebotan y el pastel deja migajas, antes de que él llegue al suelo.

Con una mano en la boca (`hand_mouth`; unpair_dance seg. 13,4-14,4 y video_41 seg. 0-1,7):

- `water_bottle`, `beer`, `can`: el envase con el pico en la boca y el cuerpo hacia la mano. El
  líquido es un relleno con la superficie siempre horizontal que baja mientras bebe, con burbujas
  que suben; vacío, el envase se arruga (la lata se aplasta) y al final se desdibuja: los trazos se
  rompen en guiones cada vez más cortos hasta desaparecer.
- `cigarette`, `vape`: el cigarro sale de la boca entre los dedos, con la brasa encendida; el
  vapeador es una cajita con su luz. El humo es una cantidad numerosa de partículas muy finas que
  suben en diagonal, se encogen y desaparecen; al final sale una bocanada de la boca hacia adelante
  (más grande con el vapeador).
"""

from __future__ import annotations

import zlib

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

DRINKS = ("water_bottle", "beer", "can")
SMOKES = ("cigarette", "vape")
HAND_PROPS = ("shofar", "snack") + DRINKS + SMOKES
# Rapidez hacia abajo de las manos (anchos de hombros por segundo) que suelta lo que sostienen.
DROP_SPEED = 3.0
# Envases: (largo, ancho del cuerpo, ancho del pico, largo del pico) en anchos de hombros.
_VESSELS = {"water_bottle": (0.95, 0.3, 0.12, 0.22), "beer": (1.0, 0.26, 0.09, 0.36), "can": (0.6, 0.3, 0.27, 0.04)}
# Humo: vida de una partícula (fotogramas), partículas por fotograma y radio inicial (hombros).
SMOKE_LIFE = 34
SMOKE_RATE = 3
SMOKE_RADIUS = 0.016


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


# ----- lo que se lleva a la boca -----


def _mouth_hand(body, event, frame, scale):
    """(boca, mano, dirección de la mano hacia los dedos) en píxeles, o None."""
    _center, _across, down = frame
    nose = body.get("nose")
    corners = body.get("mouth_left"), body.get("mouth_right")
    if corners[0] is not None and corners[1] is not None:
        mouth = (corners[0] + corners[1]) / 2
    elif nose is not None:
        mouth = nose + down * 0.12 * scale
    else:
        return None
    wrists = {s: body.get(f"{s}_wrist") for s in ("left", "right") if body.get(f"{s}_wrist") is not None}
    if not wrists:
        return None
    side = event.kind if event is not None and event.kind in wrists else min(wrists, key=lambda s: float(np.linalg.norm(wrists[s] - mouth)))
    wrist = wrists[side]
    knuckle = body.get(f"{side}_middle_mcp")
    tip = body.get(f"{side}_index_tip")
    hand = knuckle if knuckle is not None else wrist
    reach = (tip if tip is not None else hand) - wrist
    if float(np.linalg.norm(reach)) < 1e-3:
        reach = mouth - wrist
    return mouth, hand, reach / max(float(np.linalg.norm(reach)), 1e-6)


def _area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))


def _below(poly: np.ndarray, level: float) -> np.ndarray:
    """La parte del polígono por debajo de la recta y = level (en la imagen, y crece hacia abajo)."""
    out = []
    for a, b in zip(poly, np.roll(poly, -1, axis=0)):
        a_in, b_in = a[1] >= level, b[1] >= level
        if a_in:
            out.append(a)
        if a_in != b_in:
            t = (level - a[1]) / (b[1] - a[1])
            out.append(a + (b - a) * t)
    return np.array(out) if len(out) >= 3 else np.zeros((0, 2))


def _liquid(poly: np.ndarray, fraction: float) -> np.ndarray:
    """El líquido que llena `fraction` del envase, con la superficie horizontal."""
    if fraction <= 0.01:
        return np.zeros((0, 2))
    total = _area(poly)
    lo, hi = float(poly[:, 1].min()), float(poly[:, 1].max())
    for _ in range(14):  # la altura de la superficie que deja ese volumen debajo
        mid = (lo + hi) / 2
        part = _below(poly, mid)
        if (_area(part) if len(part) else 0.0) > fraction * total:
            lo = mid
        else:
            hi = mid
    return _below(poly, (lo + hi) / 2)


def _dashed(line: np.ndarray, keep: float, period: float) -> list[np.ndarray]:
    """La línea rota en guiones de `keep` de cada `period` px: así se desdibuja."""
    if keep >= 0.999:
        return [line]
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    out = []
    for start in np.arange(0.0, acc[-1], max(period, 2.0)):
        end = start + period * keep
        if end - start < 0.5:
            continue
        u = np.linspace(start, min(end, acc[-1]), 5)
        out.append(np.stack([np.interp(u, acc, line[:, 0]), np.interp(u, acc, line[:, 1])], axis=1))
    return out


def _vessel(shape: str, mouth, axis, scale: float, crumple: float, rng: np.random.Generator) -> tuple[np.ndarray, list[np.ndarray]]:
    """(contorno, detalles) del envase con el pico en la boca y el cuerpo a lo largo de `axis`."""
    length, width, neck, neck_len = _VESSELS[shape]
    length *= 1.0 - (0.45 if shape == "can" else 0.2) * crumple  # aplastado se acorta
    side = np.array([-axis[1], axis[0]])
    # Perfil: distancia desde el pico y medio ancho, del pico a la base.
    if shape == "can":
        profile = [(0.0, neck / 2), (0.04, width / 2), (length - 0.04, width / 2), (length, neck / 2)]
    else:
        shoulder = neck_len + 0.12 * length
        profile = [(0.0, neck / 2), (neck_len, neck / 2), (shoulder, width / 2), (length - 0.03, width / 2), (length, width / 2 - 0.03)]
    rows = [(d * scale, half * scale) for d, half in profile]
    right = [mouth + axis * d + side * h for d, h in rows]
    left = [mouth + axis * d - side * h for d, h in rows][::-1]
    outline = np.array(right + left)
    if crumple > 0:  # arrugado: el contorno se abolla de lado
        dense = np.concatenate([np.linspace(outline[k], outline[(k + 1) % len(outline)], 6, endpoint=False) for k in range(len(outline))])
        center = mouth + axis * length * scale * 0.5
        q = np.linspace(0, TAU, len(dense), endpoint=False)
        lobes = rng.uniform(0, TAU, 3)  # pocas abolladuras grandes, no un serrucho
        bumps = (np.sin(q * 3 + lobes[0]) + 0.6 * np.sin(q * 5 + lobes[1]) + 0.4 * np.sin(q * 8 + lobes[2])) * crumple * 0.03 * scale
        radial = dense - center
        radial /= np.maximum(np.linalg.norm(radial, axis=1, keepdims=True), 1e-6)
        outline = dense + radial * bumps[:, None]
    details = []
    if shape == "beer":  # la etiqueta
        a, b = 0.5 * length * scale, 0.78 * length * scale
        h = width / 2 * scale * 0.92
        details.append(np.array([mouth + axis * a + side * h, mouth + axis * a - side * h]))
        details.append(np.array([mouth + axis * b + side * h, mouth + axis * b - side * h]))
    elif shape == "water_bottle":  # la tapa y dos franjas
        h = neck / 2 * scale * 1.3
        details.append(np.array([mouth + axis * 0.05 * scale + side * h, mouth + axis * 0.05 * scale - side * h]))
        for f in (0.6, 0.66):
            h = width / 2 * scale * 0.95
            details.append(np.array([mouth + axis * f * length * scale + side * h, mouth + axis * f * length * scale - side * h]))
    else:  # la lata: el aro de arriba y la anilla
        t = np.linspace(0, TAU, 20)
        ring = mouth + axis * 0.04 * scale + np.outer(np.cos(t) * width / 2 * scale, side) + np.outer(np.sin(t) * 0.03 * scale, axis)
        details.append(ring)
    return outline, details


def _drink(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    found = _mouth_hand(body, event, frame, scale)
    if found is None:
        return []
    mouth, hand, _reach = found
    span = hand - mouth
    if float(np.linalg.norm(span)) < 0.3 * scale:
        # La mano en la boca: el envase se inclina hacia arriba y hacia el lado del codo, como al
        # beber (colgando hacia abajo se leía como un bloque sobre el pecho, video_41 seg. 17,2).
        _center, across, down = frame
        side = event.kind if event is not None and event.kind in ("left", "right") else "right"
        elbow = body.get(f"{side}_elbow")
        out = across if elbow is None or (elbow - mouth) @ across >= 0 else -across
        span = (out * 0.85 - down * 0.5) * scale
    axis = span / max(float(np.linalg.norm(span)), 1e-6)
    u = _phase(runtime, event)
    st = _activation(runtime, event, shape, body)
    seed = st.setdefault("seed", zlib.crc32(f"{shape}:{body.prefix}:{event.start_frame if event else 0}".encode()))
    crumple = _ease(_seg(u, 0.66, 0.8))
    outline, details = _vessel(shape, mouth, axis, scale, crumple, np.random.default_rng(seed))
    level = 0.85 - 0.75 * _ease(_seg(u, 0.12, 0.62))  # bebe: el nivel baja
    tint = np.asarray(color, np.float32)
    keep = 1.0 - _ease(_seg(u, 0.82, 1.0))  # al final se desdibuja
    if crumple < 0.5 and keep > 0.5:
        liquid = _liquid(outline, level)
        if len(liquid):
            fill_polygon(layer, liquid, WHITE * 0.4 + tint * 0.5, alpha * 0.45, 1.0, feather=1.0)  # tenue: no un bloque de luz
            rng = np.random.default_rng(seed)
            lo, hi = float(liquid[:, 1].min()), float(liquid[:, 1].max())
            contour = liquid.astype(np.float32).reshape(-1, 1, 2)
            for _ in range(7):  # burbujas que suben y se reinician abajo
                rise = (frame_index * 0.05 + rng.uniform()) % 1.0
                at = np.array([rng.uniform(liquid[:, 0].min(), liquid[:, 0].max()), hi - (hi - lo) * rise])
                if cv2.pointPolygonTest(contour, (float(at[0]), float(at[1])), False) >= 0:
                    splat(layer, float(at[0]), float(at[1]), 0.018 * scale + 1, tint * 0.4, alpha * 0.5, runtime.kernels)
    fill_polygon(layer, outline, tint, alpha * 0.18 * keep, 0.9, feather=1.5)
    grow = _ease(_seg(u, 0.0, 0.1))  # aparece trazándose
    closed = np.vstack([outline, outline[:1]])
    closed = closed[: max(int(len(closed) * grow), 2)]
    period = 0.12 * scale
    lines = _dashed(closed, keep, period)
    for detail in details:
        lines += _dashed(detail, keep, period)
    return lines


def _ember(mouth, reach, scale) -> tuple[np.ndarray, np.ndarray]:
    """(boquilla, punta) del cigarro: sale de la boca hacia donde apuntan los dedos."""
    return mouth, mouth + reach * 0.42 * scale


def _smoke(st: dict, source: np.ndarray, frame_index: int, scale: float, up: np.ndarray, drift: np.ndarray, rate: int, size: float, rng_seed: int, push: float = 1.0) -> list[tuple[np.ndarray, float, float]]:
    """Partículas de humo: (lugar, radio, vida restante 0-1). Cada una recuerda dónde nació."""
    born = st.setdefault("born", {})
    if frame_index not in born:
        born[frame_index] = source.copy()
    for old in [f for f in born if f < frame_index - SMOKE_LIFE or f > frame_index]:
        del born[old]
    out = []
    for birth, origin in born.items():
        age = frame_index - birth
        rng = np.random.default_rng((rng_seed + birth * 7919) & 0xFFFFFFFF)
        for _ in range(rate):
            speed = rng.uniform(0.008, 0.016) * scale * push
            spread = rng.uniform(-0.5, 0.5)
            wobble = np.sin(age * 0.25 + rng.uniform(0, TAU)) * 0.02 * scale
            side = np.array([-up[1], up[0]])
            at = origin + (up + drift * 0.6 + side * spread * 0.3) * speed * age + side * wobble
            life = 1.0 - age / SMOKE_LIFE
            out.append((at, size * scale * (0.4 + 0.6 * life) * rng.uniform(0.6, 1.2), life))
    return out


def _smoking(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    found = _mouth_hand(body, event, frame, scale)
    if found is None:
        return []
    mouth, hand, _reach = found
    _center, across, down = frame
    span = hand - mouth
    if float(np.linalg.norm(span)) < 0.1 * scale:
        span = across * (1.0 if hand[0] >= mouth[0] else -1.0)
    reach = span / max(float(np.linalg.norm(span)), 1e-6)
    up = -down
    u = _phase(runtime, event)
    st = _activation(runtime, event, shape, body)
    seed = zlib.crc32(f"{shape}:{body.prefix}:{event.start_frame if event else 0}".encode())
    keep = 1.0 - _ease(_seg(u, 0.85, 1.0))
    tint = np.asarray(color, np.float32)
    side = np.array([-reach[1], reach[0]])
    lines: list[np.ndarray] = []
    if shape == "cigarette":
        base, tip = _ember(mouth, reach, scale)
        w = 0.025 * scale
        stick = np.array([base + side * w, tip + side * w, tip - side * w, base - side * w, base + side * w])
        band = base + reach * 0.13 * scale
        lines += _dashed(stick, keep, 0.1 * scale) + _dashed(np.array([band + side * w, band - side * w]), keep, 0.1 * scale)
        glow = 0.6 + 0.4 * np.sin(frame_index * 0.3) ** 2  # la brasa respira
        if keep > 0.2:
            splat(layer, float(tip[0]), float(tip[1]), 0.05 * scale, (WHITE * 0.8 + tint * 0.6) * glow, alpha * keep, runtime.kernels)
        source, rate, size = tip, SMOKE_RATE, SMOKE_RADIUS
    else:
        length, w = 0.34 * scale, 0.06 * scale
        a, b = mouth, mouth + reach * length
        t = np.linspace(-np.pi / 2, np.pi / 2, 8)
        cap = [b + np.outer(np.cos(t) * w, reach)[k] + side * np.sin(t[k]) * w for k in range(len(t))]
        box = np.array([a + side * w * 0.6, b + side * w, *cap[::-1], b - side * w, a - side * w * 0.6, a + side * w * 0.6])
        lines += _dashed(box, keep, 0.1 * scale)
        led = a + reach * length * 0.7
        if frame_index % 10 < 7 and keep > 0.2:
            splat(layer, float(led[0]), float(led[1]), 0.025 * scale, WHITE * 1.2, alpha * keep, runtime.kernels)
        source, rate, size = mouth, 0, 0.0
    drift = across if float(np.dot(reach, across)) >= 0 else -across
    particles = _smoke(st, source, frame_index, scale, up, drift, rate, size, seed) if rate else []
    if u > 0.55:  # la bocanada: sale de la boca hacia adelante
        puff = st.setdefault("puff", {"born": {}})
        ahead = reach if shape == "cigarette" else drift
        vape = shape == "vape"
        particles += _smoke(puff, mouth, frame_index, scale, ahead * 0.7 + up * 0.5, drift, 10 if vape else 4, 0.035 if vape else 0.02, seed + 1, 2.2 if vape else 1.4)
    for at, radius, life in particles:
        splat(layer, float(at[0]), float(at[1]), radius + 0.6, WHITE * 0.35 + tint * 0.35, alpha * life * 0.45, runtime.kernels)  # partículas finas: poca luz
    return lines


def hand_prop(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    if shape == "shofar":
        return _shofar(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "snack":
        return _snack(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in DRINKS:
        return _drink(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in SMOKES:
        return _smoking(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
