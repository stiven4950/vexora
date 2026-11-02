"""Maquillaje de luz sobre el rostro, sacado de referencias de maquillaje real (sesión del 2026-11-02):
línea fina y nítida, rellenos tenues y puntos, anclados a los ojos de la malla. Usa la base de la
familia de ojos (engine/eye_family.py): fases, perillas y señales de la cara.

- butterfly_wings: alas de mariposa pintadas alrededor de cada ojo (maquillaje UV): el ala de arriba
  sube del párpado a la sien y la de abajo baja a la mejilla; celdas de color amarillo y cian separadas
  por venas, contorno azul y puntos blancos por el borde. Aletean al parpadear, se abren con los ojos
  muy abiertos y los puntos brillan con la sonrisa.
- pharaoh_mark: el emblema egipcio de la frente: alas de plumas en tres hileras, el escarabajo
  turquesa con el ankh, el disco solar rojo entre cuernos y una fila de puntos oro y turquesa; bajo
  cada ojo, el ojo de Horus (el trazo que sigue el párpado, la gota y la espiral).
- neon_veins: líneas neón finísimas que siguen la anatomía: una línea de puntos por el centro de la
  frente y la nariz, curvas por las sienes hasta la mandíbula, ganchos sobre las cejas, lágrimas bajo
  los ojos que terminan en gota, el contorno de los labios y la barbilla, y pecas de luz. Un pulso de
  energía recorre las líneas, más rápido al sonreír o al hablar.
- face_dissolve: el rostro se deshace en luz: el contorno de la cara se vuelve polvo azul finísimo que
  el viento arrastra hacia atrás (más lejos en el lado que da al viento), de la sien y el ojo salen
  hebras de humo rosa y naranja, y por delante flotan chispas. Al girar la cabeza o moverse, el viento
  sopla más fuerte; al irse, todo se lo lleva el viento.

Coordenadas de cara (engine/face_glow.py): los ojos en x = ±0,5, y hacia el mentón; junto a cada ojo,
x crece hacia afuera de la cara.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import fine, melt
from vfxglow.engine.eye_family import ENTRY_END, EXIT_AT, phase, pick_knobs
from vfxglow.engine.face_glow import Face, _seed, _trim
from vfxglow.engine.face_signals import signals
from vfxglow.engine.raster import fill_polygon, splat
from vfxglow.geom import catmull_rom

TAU = 2.0 * np.pi
MAKEUP = ("butterfly_wings", "pharaoh_mark", "neon_veins", "face_dissolve")
GOLD = np.array([1.0, 0.76, 0.22], np.float32)
TURQUOISE = np.array([0.15, 0.85, 0.85], np.float32)
RUBY = np.array([1.0, 0.12, 0.08], np.float32)
UV_YELLOW = np.array([1.0, 0.95, 0.2], np.float32)
UV_CYAN = np.array([0.2, 0.85, 1.0], np.float32)
UV_BLUE = np.array([0.25, 0.35, 1.0], np.float32)
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
VEIN_CYAN = np.array([0.3, 1.0, 0.9], np.float32)
VEIN_PINK = np.array([1.0, 0.55, 0.95], np.float32)

# Alas de mariposa, junto a cada ojo (x hacia afuera, y hacia abajo, unidades de cara). La raíz de las
# venas va en el rabillo; cada vena llega a un punto del borde (índices del contorno).
# El de arriba barre del lagrimal por encima de la ceja hasta la sien; el de abajo baja del rabillo por
# la mejilla (como el maquillaje UV de la referencia).
UPPER_WING = ((-0.14, -0.12), (0.02, -0.4), (0.32, -0.62), (0.66, -0.8), (0.9, -0.72), (0.98, -0.46), (0.82, -0.18), (0.5, -0.05))
LOWER_WING = ((0.44, 0.02), (0.72, 0.1), (0.86, 0.36), (0.72, 0.62), (0.46, 0.62), (0.3, 0.36), (0.26, 0.12))
WING_ROOT = (0.44, -0.04)
UPPER_VEINS = (0, 2, 3, 4, 6)
LOWER_VEINS = (1, 2, 3, 5)
WING_DOTS = 22

# Emblema de la frente: centro, alas (medio ancho), hileras de plumas y la fila de puntos.
EMBLEM_Y = -0.78
EMBLEM_WING = 0.9
FEATHER_ROWS = 3
FEATHERS = 7
EMBLEM_DOTS = 7

# Líneas neón: cuántas lágrimas por ojo, pecas y el pulso (cuadros de 30 fps por vuelta).
TEARS = 4
FRECKLES = 26
PULSE_FRAMES = 70


def _side(face: Face, side: str, local) -> np.ndarray:
    """Puntos junto al ojo `side` (x hacia afuera de la cara), en píxeles."""
    out = -1.0 if side == "right" else 1.0
    pts = np.asarray(local, dtype=np.float64).reshape(-1, 2)
    return face.place(np.stack([0.5 * out + pts[:, 0] * out, pts[:, 1]], axis=1))


def _smooth_closed(points: np.ndarray, samples: int = 6) -> np.ndarray:
    return catmull_rom(np.vstack([points, points[:1]]), samples)


def _dots_along(curve: np.ndarray, count: int) -> np.ndarray:
    seg = np.linalg.norm(np.diff(curve, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    q = np.linspace(0.0, acc[-1], count, endpoint=False)
    return np.stack([np.interp(q, acc, curve[:, 0]), np.interp(q, acc, curve[:, 1])], axis=1)


# ----- alas de mariposa -----


def _butterfly_wings(face: Face, ctx: dict) -> list:
    sig, layer, alpha, kernels = ctx["sig"], ctx["layer"], ctx["alpha"], ctx["runtime"].kernels
    grow = _ease(_seg(ctx["u"], 0.0, ENTRY_END * 2.0))
    # Aleteo: al parpadear el ala se cierra hacia el ojo; con los ojos muy abiertos se abre.
    open_ = grow * (1.0 - 0.35 * min(sig.blink * 1.3, 1.0)) * (1.0 + 0.12 * float(np.clip(sig.wide / 0.25, 0.0, 1.0)))
    sparkle = 0.6 + 0.4 * float(np.clip(sig.smile / 0.5, 0.0, 1.0))
    lines: list = []
    for side in ("right", "left"):
        if not face.visible(side):
            continue
        root = np.asarray(WING_ROOT)
        for shape, veins, cells in ((UPPER_WING, UPPER_VEINS, (UV_YELLOW, UV_CYAN)), (LOWER_WING, LOWER_VEINS, (UV_CYAN, UV_YELLOW))):
            local = root + (np.asarray(shape) - root) * open_
            outline = _smooth_closed(_side(face, side, local))
            fill_polygon(layer, outline, UV_BLUE, alpha * 0.12, 1.0, feather=2.0)
            lines.append((outline, UV_BLUE * 1.2))
            hub = _side(face, side, root)[0]
            ends = [_side(face, side, local[k])[0] for k in veins]
            for k, (a, b) in enumerate(zip(ends[:-1], ends[1:])):  # celdas entre venas, como pétalos
                mid = (a + b) / 2
                cell = catmull_rom(np.array([hub + (a - hub) * 0.4, hub + (a - hub) * 0.86, mid + (mid - hub) * 0.04, hub + (b - hub) * 0.86, hub + (b - hub) * 0.4, (hub + (a - hub) * 0.4 + hub + (b - hub) * 0.4) / 2 - (mid - hub) * 0.04]), 5)
                cell = hub + (cell - hub) * 0.92
                tint = cells[k % 2]
                fill_polygon(layer, cell, tint, alpha * 0.45, 1.0, feather=1.5)
                lines.append((cell, tint * 0.8))
            border = hub + (outline - hub) * 0.93
            for k, dot in enumerate(_dots_along(border, WING_DOTS)):  # los puntos blancos del borde
                twinkle = sparkle * (0.7 + 0.3 * np.sin(ctx["frame_index"] * 0.25 + k * 1.7))
                splat(layer, float(dot[0]), float(dot[1]), 0.012 * face.unit + 0.5, WHITE, alpha * twinkle * grow, kernels)
        rng = np.random.default_rng(ctx["seed"] + (0 if side == "right" else 3))
        for k in range(14):  # polvo de luz cerca de la punta
            x, y = rng.uniform(0.45, 0.9), rng.uniform(-1.1, -0.55)
            dot = _side(face, side, (x, y))[0]
            splat(layer, float(dot[0]), float(dot[1]), 0.008 * face.unit + 0.4, UV_CYAN if k % 2 else WHITE, alpha * 0.6 * grow * sparkle, kernels)
    return lines


# ----- emblema egipcio -----


def _ankh(face: Face, center: tuple[float, float], size: float) -> list[np.ndarray]:
    cx, cy = center
    t = np.linspace(0.0, TAU, 24)
    loop = face.place(np.stack([cx + 0.3 * size * np.sin(t), cy - 0.58 * size - 0.3 * size * np.cos(t)], axis=1))
    stem = face.place([(cx, cy - 0.28 * size), (cx, cy + 0.85 * size)])
    bar = face.place([(cx - 0.45 * size, cy - 0.2 * size), (cx + 0.45 * size, cy - 0.2 * size)])
    return [loop, stem, bar]


def _wing_emblem(face: Face, sign: float, grow: float, layer, alpha: float) -> list[np.ndarray]:
    """Un ala de plumas: silueta limpia (el borde de arriba cae hacia la punta, el de abajo festoneado),
    dos líneas que la parten en tres hileras y plumas inclinadas en cada hilera."""
    reach = EMBLEM_WING * grow
    s = np.linspace(0.0, 1.0, 40)
    x = sign * (0.13 + reach * s)
    top = EMBLEM_Y - 0.1 - 0.05 * np.sin(np.pi * s * 0.8) + 0.13 * s**3
    depth = 0.25 * (1.0 - s) ** 0.8 + 0.025
    bottom = top + depth + 0.018 * np.abs(np.sin(s * np.pi * 10.0)) * (1.0 - s)  # el festón de las plumas
    upper, lower = face.place(np.stack([x, top], axis=1)), face.place(np.stack([x, bottom], axis=1))
    silhouette = np.vstack([upper, lower[::-1], upper[:1]])
    fill_polygon(layer, silhouette, GOLD, alpha * 0.18 * grow, 1.0, feather=1.2)
    lines = [silhouette]
    for tier in (1.0 / 3.0, 2.0 / 3.0):
        lines.append(face.place(np.stack([x, top + depth * tier], axis=1))[:-3])
    for row in range(FEATHER_ROWS):
        a, b = row / FEATHER_ROWS, (row + 1) / FEATHER_ROWS
        count = FEATHERS + 2 * row
        for k in range(1, count):
            i = int(k / count * (len(s) - 4))
            lean = sign * 0.035 * (0.5 + row * 0.25)
            lines.append(face.place([(x[i], top[i] + depth[i] * a + 0.01), (x[i] + lean, top[i] + depth[i] * b - 0.005)]))
    return lines


def _pharaoh_mark(face: Face, ctx: dict) -> list:
    layer, alpha, kernels = ctx["layer"], ctx["alpha"], ctx["runtime"].kernels
    grow = _ease(_seg(ctx["u"], 0.0, ENTRY_END * 2.0))
    trace = _seg(ctx["u"], 0.0, ENTRY_END * 2.5)
    lines: list = []
    t = np.linspace(0.0, TAU, 32)
    body = face.place(np.stack([0.13 * np.sin(t), EMBLEM_Y + 0.02 + 0.16 * np.cos(t)], axis=1))
    fill_polygon(layer, body, TURQUOISE, alpha * 0.4 * grow, 1.0, feather=1.2)
    lines.append((body, GOLD))
    lines += [(curve, GOLD) for curve in _ankh(face, (0.0, EMBLEM_Y + 0.03), 0.17)]
    disc = face.place(np.stack([0.06 * np.sin(t), EMBLEM_Y - 0.33 + 0.06 * np.cos(t)], axis=1))
    fill_polygon(layer, disc, RUBY, alpha * 0.6 * grow, 1.0, feather=1.2)
    lines.append((disc, RUBY))
    for sign in (-1.0, 1.0):
        # las patas del escarabajo que sostienen el disco y los cuernos que lo abrazan
        lines.append((catmull_rom(face.place([(sign * 0.07, EMBLEM_Y - 0.12), (sign * 0.12, EMBLEM_Y - 0.22), (sign * 0.07, EMBLEM_Y - 0.3)]), 5), GOLD))
        lines.append((catmull_rom(face.place([(sign * 0.05, EMBLEM_Y - 0.28), (sign * 0.1, EMBLEM_Y - 0.36), (sign * 0.08, EMBLEM_Y - 0.44)]), 5), GOLD))
        lines += [(_trim(curve, trace), GOLD) for curve in _wing_emblem(face, sign, grow, layer, alpha)]
        for k in range(EMBLEM_DOTS):  # la fila de puntos
            x = sign * (0.2 + 0.11 * k) * (0.3 + 0.7 * grow)
            dot = face.place([(x, EMBLEM_Y - 0.2)])[0]
            splat(layer, float(dot[0]), float(dot[1]), 0.018 * face.unit + 0.5, TURQUOISE if k % 2 == 0 else GOLD, alpha * grow, kernels)
    for side in ("right", "left"):  # el ojo de Horus bajo cada ojo
        if not face.visible(side):
            continue
        # El trazo bajo el párpado que se levanta pasado el rabillo, la gota y la espiral.
        sweep = catmull_rom(_side(face, side, [(-0.14, 0.13), (0.02, 0.19), (0.22, 0.17), (0.4, 0.09), (0.56, -0.02), (0.62, -0.06)]), 6)
        drop = catmull_rom(_side(face, side, [(0.0, 0.19), (0.0, 0.34), (-0.03, 0.48), (0.0, 0.58), (0.04, 0.6)]), 5)
        tail = catmull_rom(_side(face, side, [(0.1, 0.19), (0.22, 0.3), (0.36, 0.42), (0.5, 0.44), (0.56, 0.36), (0.5, 0.29), (0.43, 0.32), (0.45, 0.37)]), 6)
        lines += [(_trim(curve, trace), GOLD) for curve in (sweep, drop, tail)]
    return lines


# ----- líneas neón -----


def _veins(face: Face) -> list[tuple[np.ndarray, np.ndarray]]:
    """Las líneas, en el orden en que se trazan."""
    out = []
    for sign in (-1.0, 1.0):
        temple = catmull_rom(face.place([(sign * 0.6, -0.95), (sign * 0.88, -0.55), (sign * 0.98, -0.1), (sign * 0.96, 0.45), (sign * 0.78, 0.95), (sign * 0.5, 1.25)]), 8)
        hook = catmull_rom(face.place([(sign * 0.22, -0.32), (sign * 0.3, -0.62), (sign * 0.45, -0.9), (sign * 0.42, -1.05), (sign * 0.36, -1.0)]), 6)
        out += [(temple, VEIN_PINK), (hook, VEIN_CYAN)]
        for k in range(TEARS):
            x = 0.32 + 0.1 * k
            length = 0.3 + 0.12 * ((k * 7) % 3)
            tear = catmull_rom(face.place([(sign * x, 0.12), (sign * (x + 0.02), 0.12 + length * 0.4), (sign * (x - 0.01), 0.12 + length * 0.75), (sign * x, 0.12 + length)]), 5)
            out.append((tear, VEIN_CYAN))
    lips = face.feature("lips_outer")
    if lips is not None:
        out.append((np.vstack([lips, lips[:1]]), VEIN_CYAN))
    out.append((face.place([(0.0, 1.32), (0.0, 1.62)]), VEIN_CYAN))
    for sign in (-1.0, 1.0):
        out.append((catmull_rom(face.place([(sign * 0.18, 1.3), (sign * 0.08, 1.45), (0.0, 1.6)]), 5), VEIN_PINK))
    return out


def _neon_veins(face: Face, ctx: dict) -> list:
    sig, layer, alpha, kernels, frame_index = ctx["sig"], ctx["layer"], ctx["alpha"], ctx["runtime"].kernels, ctx["frame_index"]
    trace = _seg(ctx["u"], 0.0, ENTRY_END * 3.0)
    fade = 1.0 - 0.5 * sig.relaxed
    lines = [(_trim(curve, trace), tint * fade) for curve, tint in _veins(face)]
    dotted = face.place(np.stack([np.zeros(10), np.linspace(-1.05, -0.3, 10)], axis=1))  # la línea de puntos del centro
    nose = face.place(np.stack([np.zeros(6), np.linspace(0.02, 0.4, 6)], axis=1))
    for k, dot in enumerate(np.vstack([dotted, nose])):
        if k / 16 <= trace:
            splat(layer, float(dot[0]), float(dot[1]), 0.01 * face.unit + 0.4, VEIN_CYAN, alpha * fade, kernels)
    t = np.linspace(0.0, TAU, 16)
    ring = face.place([(0.0, -0.18)])[0]  # el círculo entre las cejas
    lines.append((ring + np.stack([np.cos(t), np.sin(t)], axis=1) * 0.035 * face.unit, VEIN_CYAN * fade))
    rng = np.random.default_rng(ctx["seed"])
    for k in range(FRECKLES):  # pecas de luz en las mejillas
        sign = -1.0 if k % 2 else 1.0
        dot = face.place([(sign * rng.uniform(0.25, 0.75), rng.uniform(0.2, 0.65))])[0]
        twinkle = 0.5 + 0.5 * np.sin(frame_index * 0.2 + k * 2.3)
        splat(layer, float(dot[0]), float(dot[1]), 0.007 * face.unit + 0.4, VEIN_CYAN, alpha * 0.7 * twinkle * trace, kernels)
    # El pulso: un punto brillante recorre cada línea; va más rápido al sonreír o al hablar.
    st = ctx["st"]
    speed = (1.0 + 1.2 * float(np.clip(sig.smile / 0.5, 0.0, 1.0)) + 1.2 * sig.voice) * float(ctx["knobs"]["speed"])
    st["pulse"] = st.get("pulse", 0.0) + speed / PULSE_FRAMES
    for k, (curve, tint) in enumerate(lines):
        if len(curve) < 2 or trace < 1.0:
            continue
        at = curve[int(((st["pulse"] + k * 0.37) % 1.0) * (len(curve) - 1))]
        splat(layer, float(at[0]), float(at[1]), 0.022 * face.unit + 0.5, WHITE, alpha * fade, kernels)
    return lines


# Desintegración: granos del contorno, su vida (cuadros de 30 fps), hasta dónde los lleva el viento
# (unidades de cara), hebras de humo y chispas del frente.
DUST = 320
DUST_LIFE = 46
DUST_REACH = 1.6
WISPS = 6
WISP_LENGTH = 2.2
SPARKS = 34
DUST_BLUE = np.array([0.4, 0.6, 1.0], np.float32)
WISP_PINK = np.array([1.0, 0.3, 0.65], np.float32)
WISP_ORANGE = np.array([1.0, 0.6, 0.3], np.float32)


def _face_dissolve(face: Face, ctx: dict) -> list:
    sig, layer, kernels, frame_index, st = ctx["sig"], ctx["layer"], ctx["runtime"].kernels, ctx["frame_index"], ctx["st"]
    oval = face.feature("face_oval")
    if oval is None or len(oval) < 8:
        return []
    alpha = ctx["power"]
    stage_t = ctx["stage_t"]
    leaving = stage_t if ctx["stage"] == "exit" else 0.0
    grow = _ease(_seg(ctx["u"], 0.0, ENTRY_END * 2.0))
    fade = 1.0 - _ease(leaving)
    across, down = face.ux / face.unit, face.uy / face.unit
    # El viento sopla hacia atrás de la cabeza: hacia un lado (con semilla) y un poco hacia arriba.
    side = 1.0 if ctx["seed"] % 2 else -1.0
    wind = across * side - down * 0.25
    wind = wind / np.linalg.norm(wind)
    gust = 1.0 + 1.5 * min(abs(sig.yaw_rate) / 90.0, 1.0) + sig.energy
    st["time"] = st.get("time", 0.0) + gust * float(ctx["knobs"]["speed"])
    closed = np.vstack([oval, oval[:1]])
    center = oval.mean(axis=0)
    rng = np.random.default_rng(ctx["seed"])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    for k, s_ in enumerate(rng.uniform(0.0, acc[-1], DUST)):  # el contorno que se vuelve polvo
        base = np.array([np.interp(s_, acc, closed[:, 0]), np.interp(s_, acc, closed[:, 1])])
        normal = (base - center) / max(float(np.linalg.norm(base - center)), 1e-6)
        downwind = max(float(normal @ wind), 0.0)
        age = ((st["time"] / DUST_LIFE) + k * 0.6180339) % 1.0
        reach = DUST_REACH * face.unit * (0.08 + 0.92 * downwind) * (1.0 + 2.5 * leaving) * grow
        swirl = np.array([-wind[1], wind[0]]) * np.sin(age * 6.0 + k) * 0.08 * face.unit * age
        at = base + wind * reach * age**1.4 + swirl
        size = (0.006 + 0.006 * (k % 3 == 0)) * face.unit + 0.4
        splat(layer, float(at[0]), float(at[1]), size, DUST_BLUE if k % 5 else WHITE, alpha * fade * (1.0 - age) * (0.35 + 0.9 * downwind), kernels)
    for p in closed[::2]:  # el borde mismo, punteado y tenue
        splat(layer, float(p[0]), float(p[1]), 0.006 * face.unit + 0.4, DUST_BLUE, alpha * 0.5 * grow * fade, kernels)
    perp = np.array([-wind[1], wind[0]])
    # Las hebras salen de todo el costado de la cabeza que da al viento (del pelo a la mandíbula), no de
    # un punto: si no, convergen como bigotes.
    facing = (closed[:-1] - center) @ wind / np.maximum(np.linalg.norm(closed[:-1] - center, axis=1), 1e-6)
    lee = closed[:-1][facing > 0.35]
    if len(lee) < WISPS:
        return []
    order = np.argsort(lee @ down)
    starts = lee[order][np.linspace(0, len(lee) - 1, WISPS).astype(int)]
    for k, start in enumerate(starts):  # hebras de humo rosa a naranja
        q = np.linspace(0.0, 1.0, 40)[:, None]
        normal = (start - center) / max(float(np.linalg.norm(start - center)), 1e-6)
        aim = wind * 0.75 + normal * 0.25
        aim = aim / np.linalg.norm(aim)
        side_ = np.array([-aim[1], aim[0]])
        length = WISP_LENGTH * face.unit * grow * (0.65 + 0.35 * ((k * 3) % 4) / 3) * (1.0 + leaving)
        wave = (np.sin(q * 4.0 - st["time"] * 0.1 + k * 1.9) + 0.5 * np.sin(q * 9.0 - st["time"] * 0.17 + k)) * 0.3 * face.unit * q**1.2
        spine = start + aim * q * length + side_ * wave
        for strand in range(5):  # el humo: varias hebras que se separan al alejarse
            offset = side_ * (strand - 2) * 0.035 * face.unit * (0.2 + 1.6 * q) + side_ * np.sin(q * 7.0 + strand * 1.3 - st["time"] * 0.13) * 0.05 * face.unit * q
            curve = spine + offset
            fine([curve[:21]], WISP_PINK, alpha * 0.22 * fade, layer, width=1.0)
            fine([curve[20:]], WISP_ORANGE, alpha * 0.16 * fade, layer, width=1.0)
        for m in range(26):  # una nube de partículas a lo largo de la hebra, más abierta al final
            t = (st["time"] * 0.015 + m / 26 + k * 0.13) % 1.0
            at = spine[int(t * (len(spine) - 1))] + side_ * np.sin(m * 2.1 + k) * 0.2 * face.unit * t
            tint = WISP_PINK + (WISP_ORANGE - WISP_PINK) * t
            splat(layer, float(at[0]), float(at[1]), (0.008 + 0.006 * (m % 3 == 0)) * face.unit + 0.4, tint, alpha * fade * (1.0 - t) ** 0.7, kernels)
    for k in range(SPARKS):  # chispas que flotan por delante
        age = ((st["time"] / 120.0) + k * 0.381966) % 1.0
        x, y = rng.uniform(0.6, 1.7), rng.uniform(-1.0, 1.2)
        at = face.place([(-side * (x + 0.4 * age), y - 0.2 * age)])[0]
        splat(layer, float(at[0]), float(at[1]), 0.008 * face.unit + 0.4, WHITE, alpha * 0.7 * fade * grow * np.sin(np.pi * age), kernels)
    return []


DRAW = {"butterfly_wings": _butterfly_wings, "pharaoh_mark": _pharaoh_mark, "neon_veins": _neon_veins, "face_dissolve": _face_dissolve}


def face_makeup(shape: str, body, frame, scale, frame_index: int, runtime, layer, color, alpha: float, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    stage, t = phase(u)
    start = event.start_frame if event is not None else 0
    knobs = pick_knobs(shape, body.prefix, start, runtime.effect.style.variants)
    power = alpha * float(knobs["intensity"])
    ctx = {
        "sig": signals(runtime, frame_index, body.prefix), "st": runtime.swoosh.setdefault(f"_makeup:{shape}:{start}:{body.prefix}", {}),
        "u": u, "frame_index": frame_index, "runtime": runtime, "layer": layer, "knobs": knobs, "seed": _seed(shape, body, event),
        "alpha": power * (1.0 - _ease(t) if stage == "exit" else 1.0), "power": power, "stage": stage, "stage_t": t,
    }
    lines = DRAW[shape](face, ctx)
    width = max(1.0, 0.005 * face.unit) * float(knobs["stroke"])
    for curve, tint in melt(lines, u, face, layer, WHITE, power, runtime.kernels, ctx["seed"], start=EXIT_AT):
        fine([curve], tint, ctx["alpha"] if stage != "exit" else power, layer, width=width)
    return []
