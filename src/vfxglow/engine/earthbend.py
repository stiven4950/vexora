"""Tierra control (estilo Avatar): roca elemental con energía mineral.

Peso, fuerza, resistencia. La roca se lee como roca real, no como triángulos planos ni auras doradas:
- Cada roca es un polígono irregular (6-9 vértices con el radio variado) partido en 3-4 facetas
  desde un punto interno. Cada faceta se sombrea con el producto de su dirección y la luz (arriba a
  la izquierda, la misma que el agua): claras las que miran a la luz, café oscuro las de sombra.
  Un borde fino brillante solo donde mira a la luz y un contorno oscuro fino.
- Paleta: café roca (base), gris mineral (facetas con luz) y ámbar SOLO dentro de las grietas y en
  chispas diminutas en los puntos de contacto.
- Las grietas nacen del punto de contacto estimado (el pie que pisó, el puño), nunca al azar: ramas
  que se abren por el piso con perspectiva (aplastadas en vertical) y se revelan con `grow`.
- Los impactos pesan: unos cuadros de pausa (solo grietas) antes de que salgan los escombros.

Física: los escombros caen con gravedad y arrastre, rebotan poco (restitución 0,3, fricción 0,7 en x),
se asientan al quedar lentos y se achican y desvanecen al rato. El polvo son nubes grises suaves
que se abren, suben un poco y se desvanecen (poco alfa, sin brillo).

Figuras:
- `earth_slam`: pisotón o caída: grietas desde el pie, chispas, escombros y un anillo de polvo.
- `earth_shield`: placas de roca que suben bajo las manos y arman un escudo frente al torso.
- `earth_fist`: guantelete de roca alrededor del puño, que suelta escombros y al final se rompe.
- `earth_orbit`: rocas que giran alrededor de la cadera y al final salen disparadas.
- `earth_boulder`: una roca sale del piso, flota a la altura de la mano, se lanza y se hace trizas.
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, _activation, _ease, _phase, _seg
from vfxglow.engine.waterbend import GRAVITY, LIGHT, _floor, _limb, _unit

EARTHBEND = ("earth_slam", "earth_shield", "earth_fist", "earth_orbit", "earth_boulder", "earth_crystals")

AMBER = np.array([1.0, 0.62, 0.15], np.float32)
DUST = np.array([0.62, 0.56, 0.47], np.float32)  # gris beige
PALETTE = {
    "dark": np.array([0.15, 0.09, 0.06], np.float32),  # café de la sombra
    "base": np.array([0.40, 0.28, 0.19], np.float32),  # café roca
    "light": np.array([0.70, 0.65, 0.58], np.float32),  # gris mineral con luz
    "rim": np.array([0.88, 0.85, 0.78], np.float32),
    "outline": np.array([0.06, 0.04, 0.03], np.float32),
}
# Cristal de jade (la variante cristalina de la tierra): verde profundo en la sombra, menta en la luz.
CRYSTAL = {
    "dark": np.array([0.02, 0.2, 0.12], np.float32),
    "base": np.array([0.08, 0.55, 0.34], np.float32),
    "light": np.array([0.55, 0.96, 0.72], np.float32),
    "rim": np.array([0.85, 1.0, 0.92], np.float32),
    "outline": np.array([0.01, 0.1, 0.06], np.float32),
}
JADE = np.array([0.3, 1.0, 0.6], np.float32)  # la energía del cristal (grietas, destellos)
COVER = 0.95  # la roca es opaca
FLAT = 0.35  # las grietas del piso se aplastan en vertical (perspectiva)
REST = 0.3  # restitución del rebote
FRICTION = 0.7  # lo que conserva de la velocidad en x al rebotar
FADE_FROM, FADE_TO = 40, 70  # edad (cuadros) en que el escombro se achica y se va
DUST_LIFE = 26
GROUND_FRAMES = 3  # cuadros seguidos parado antes de partir el piso
SPARK_LIFE = 7


# ----- la roca -----


def _shade_color(shade: float, palette: dict) -> np.ndarray:
    if shade < 0.5:
        return palette["dark"] + (palette["base"] - palette["dark"]) * (shade * 2.0)
    return palette["base"] + (palette["light"] - palette["base"]) * ((shade - 0.5) * 2.0)


def rock_polygon(center, radius: float, seed: int, rotation: float = 0.0) -> tuple[list, np.ndarray]:
    """Una roca: (facetas, contorno). Cada faceta es (polígono, sombra 0..1) y su primer punto es el
    punto interno desde el que se parte la roca; el resto del polígono es su borde exterior."""
    rng = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    center = np.asarray(center, np.float64)
    n = int(rng.integers(6, 10))
    ang = (np.arange(n) + rng.uniform(-0.3, 0.3, n)) * TAU / n
    ring = center + np.stack([np.cos(ang), np.sin(ang)], axis=1) * (radius * rng.uniform(0.72, 1.0, n))[:, None]
    inner = center + rng.uniform(-0.25, 0.25, 2) * radius
    parts = int(rng.integers(3, 5))
    bounds = np.round(np.linspace(0, n, parts + 1)).astype(int)
    rot = np.array([[np.cos(rotation), -np.sin(rotation)], [np.sin(rotation), np.cos(rotation)]])

    def turn(p):  # gira alrededor del centro
        return (p - center) @ rot.T + center

    facets = []
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        outer = ring[[i % n for i in range(b0, b1 + 1)]]
        facing = outer.mean(axis=0) - inner
        facing = facing / max(float(np.linalg.norm(facing)), 1e-9)
        shade = float(np.clip(0.5 + 0.5 * float(facing @ LIGHT) + rng.uniform(-0.05, 0.05), 0.0, 1.0))
        facets.append((turn(np.vstack([inner, outer])), shade))
    return facets, turn(ring)


def _stretch(facets: list, center, sx: float, sy: float) -> list:
    c = np.asarray(center, np.float64)
    return [(c + (poly - c) * np.array([sx, sy]), shade) for poly, shade in facets]


def _window(layer, points: np.ndarray, pad: int):
    """Recuadro de la capa que cubre los puntos, o None si queda fuera."""
    h, w = layer.shape[:2]
    x0, y0 = max(int(np.floor(points[:, 0].min())) - pad, 0), max(int(np.floor(points[:, 1].min())) - pad, 0)
    x1, y1 = min(int(np.ceil(points[:, 0].max())) + pad + 1, w), min(int(np.ceil(points[:, 1].max())) + pad + 1, h)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _over(layer, win, rgb: np.ndarray, a: np.ndarray) -> None:
    """Pone `rgb` encima con cobertura `a` (capa premultiplicada)."""
    x0, y0, x1, y1 = win
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] = dst[..., :3] * (1.0 - a[..., None]) + rgb * a[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - a)


def draw_rock(layer, facets: list, alpha: float, palette: dict | None = None, dim: float = 1.0) -> None:
    """Pinta la roca opaca: facetas sombreadas, costuras, borde brillante hacia la luz y contorno."""
    if not facets or alpha <= 0:
        return
    pal = palette or PALETTE
    pts = np.vstack([poly for poly, _ in facets])
    win = _window(layer, pts, 3)
    if win is None:
        return
    x0, y0, x1, y1 = win
    rgb = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    size = float(np.ptp(pts, axis=0).max())
    line = 1 if size < 40 else 2

    def px(poly):
        return np.round((poly - [x0, y0]) * 16).astype(np.int32)  # subpíxel para el antialias

    def col(c):
        return tuple(int(v) for v in np.clip(c * 255.0, 0, 255))

    for poly, shade in facets:
        c = col(_shade_color(shade, pal) * dim)
        cv2.fillPoly(rgb, [px(poly)], c, lineType=cv2.LINE_AA, shift=4)
        cv2.fillPoly(mask, [px(poly)], 255, lineType=cv2.LINE_AA, shift=4)
    for poly, shade in facets:
        inner = poly[0]
        cv2.line(rgb, tuple(int(v) for v in px(inner[None])[0]), tuple(int(v) for v in px(poly[1:2])[0]), col(_shade_color(shade, pal) * dim * 0.6), 1, cv2.LINE_AA, 4)
        cv2.polylines(rgb, [px(poly[1:])], False, col(pal["outline"] * dim), line, cv2.LINE_AA, 4)
        cv2.polylines(mask, [px(poly[1:])], False, 255, line, cv2.LINE_AA, 4)
    for poly, _ in facets:
        for j in range(1, len(poly) - 1):
            out = (poly[j] + poly[j + 1]) / 2 - poly[0]
            lit = float(out @ LIGHT) / max(float(np.linalg.norm(out)), 1e-9)
            if lit > 0.35:  # el borde que mira a la luz brilla
                p, q = (poly[j] - [x0, y0]) * 0.97 + (poly[0] - [x0, y0]) * 0.03, (poly[j + 1] - [x0, y0]) * 0.97 + (poly[0] - [x0, y0]) * 0.03
                cv2.line(rgb, tuple(np.round(p * 16).astype(int)), tuple(np.round(q * 16).astype(int)), col(pal["rim"] * dim * min(lit * 1.3, 1.0)), 1, cv2.LINE_AA, 4)
    _over(layer, win, rgb.astype(np.float32) / 255.0, mask.astype(np.float32) / 255.0 * COVER * min(alpha, 1.0))


# ----- grietas -----


def _walk(start: np.ndarray, angle: float, length: float, unit: float, rng) -> np.ndarray:
    """Camino al azar (grieta zigzagueante) aplastado en vertical por la perspectiva."""
    step = max(unit * 0.1, 1.0)
    pts = [np.asarray(start, np.float64)]
    for _ in range(max(int(np.ceil(length / step)), 2)):
        angle += rng.normal(0.0, 0.3)
        pts.append(pts[-1] + np.array([np.cos(angle), np.sin(angle) * FLAT]) * step)
    return np.array(pts)


def _prefix(pts: np.ndarray, grow: float) -> np.ndarray:
    """El tramo inicial de la polilínea: la fracción `grow` de su largo."""
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    target = float(np.clip(grow, 0.0, 1.0)) * cum[-1]
    k = int(np.searchsorted(cum, target, side="right")) - 1
    k = min(max(k, 0), len(pts) - 2)
    local = (target - cum[k]) / max(cum[k + 1] - cum[k], 1e-9)
    return np.vstack([pts[: k + 1], pts[k] + (pts[k + 1] - pts[k]) * np.clip(local, 0.0, 1.0)])


def ground_cracks(origin, unit: float, seed: int, grow: float, subs: bool = True) -> list:
    """Grietas del piso desde `origin`: 5-8 ramas principales radiales (todas parten del origen) y 1-2
    subramas cada una, reveladas según `grow` (0..1). Con `subs=False` devuelve solo las principales."""
    if grow <= 0:
        return []
    rng = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    origin = np.asarray(origin, np.float64)
    n = int(rng.integers(7, 11))
    base = rng.uniform(0.0, TAU)
    mains, branches = [], []
    for i in range(n):
        length = 3.4 * unit * rng.uniform(0.5, 1.0)
        main = _walk(origin, base + (i + rng.uniform(-0.3, 0.3)) * TAU / n, length, unit, rng)
        mains.append(main)
        for _ in range(int(rng.integers(1, 3))):
            f = rng.uniform(0.3, 0.7)
            k = min(int(f * (len(main) - 1)), len(main) - 2)
            d = main[k + 1] - main[k]
            heading = np.arctan2(d[1] / FLAT, d[0]) + rng.choice([-1.0, 1.0]) * rng.uniform(0.5, 0.9)
            branches.append((f, _walk(main[k], heading, 0.4 * length, unit, rng)))
    out = [_prefix(m, grow) for m in mains]
    if subs:
        out += [_prefix(b, _seg(grow, f, 1.0)) for f, b in branches if grow > f]
    return out


def _stroke(layer, lines: list, fades: list, dark_w: int, core_w: int, alpha: float, dark: bool = True, color=AMBER) -> None:
    """Trazos con una línea oscura y un núcleo ámbar fino, más brillante según `fades` (por punto)."""
    lines = [l for l in lines if len(l) >= 2]
    if not lines or alpha <= 0:
        return
    win = _window(layer, np.vstack(lines), dark_w * 2 + core_w * 4 + 2)
    if win is None:
        return
    x0, y0, x1, y1 = win
    shape = (y1 - y0, x1 - x0)
    dark_m, core = np.zeros(shape, np.uint8), np.zeros(shape, np.uint8)
    for pl, fd in zip(lines, fades):
        q = np.round(pl - [x0, y0]).astype(np.int32)
        if dark:
            cv2.polylines(dark_m, [q], False, 255, dark_w, cv2.LINE_AA)
        for j in range(len(q) - 1):
            level = int(255 * float(np.clip(fd[j], 0.0, 1.0)))
            if level > 3:
                cv2.line(core, tuple(int(v) for v in q[j]), tuple(int(v) for v in q[j + 1]), level, core_w, cv2.LINE_AA)
    a = min(alpha, 1.0)
    if dark:
        _over(layer, win, np.broadcast_to(PALETTE["outline"], shape + (3,)), dark_m.astype(np.float32) / 255.0 * 0.85 * a)
    core_f = core.astype(np.float32) / 255.0
    glow = cv2.GaussianBlur(core_f, (0, 0), max(core_w * 1.2, 1.0))
    energy = np.clip(core_f + glow * 0.5, 0.0, 1.0) * a
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += np.asarray(color, np.float32) * energy[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - np.minimum(energy, 1.0))


def draw_cracks(layer, cracks: list, origin, unit: float, alpha: float, amber: float = 1.0, color=AMBER) -> None:
    """Pinta las grietas: línea oscura con el núcleo ámbar, más vivo junto al origen y apagándose a lo largo."""
    origin = np.asarray(origin, np.float64)
    reach = 3.0 * unit
    fades = [np.clip(1.0 - np.linalg.norm(c - origin, axis=1) / reach, 0.0, 1.0) ** 1.2 * amber for c in cracks]
    dark_w = max(int(round(unit * 0.06)), 2)
    _stroke(layer, cracks, fades, dark_w, max(dark_w // 2, 1), alpha, color=color)


# ----- partículas -----


def _blob(layer, pos, sigma: float, color, a: float, add: bool) -> None:
    """Mancha gaussiana: suma luz (chispas) o se pone encima (polvo)."""
    sigma = max(float(sigma), 0.5)
    r = int(np.ceil(sigma * 3))
    win = _window(layer, np.array([pos, pos], np.float64), r)
    if win is None:
        return
    x0, y0, x1, y1 = win
    yy, xx = np.mgrid[y0:y1, x0:x1]
    g = (np.exp(-((xx - pos[0]) ** 2 + (yy - pos[1]) ** 2) / (2 * sigma * sigma)) * a).astype(np.float32)
    if add:
        dst = layer[y0:y1, x0:x1]
        dst[..., :3] += np.asarray(color, np.float32) * g[..., None]
        dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - np.minimum(g, 1.0))
    else:
        _over(layer, win, np.broadcast_to(np.asarray(color, np.float32), g.shape + (3,)), g)


def step_debris(st: dict, height: int, floor: float | None) -> list:
    """Los escombros [pos, vel, tamaño, ángulo, giro, edad]: caen, se frenan con el aire, rebotan poco,
    se asientan al quedar lentos y al rato se achican y se van."""
    gravity = GRAVITY * height
    keep = []
    for pos, vel, size, angle, spin, age in st.get("debris", []):
        at_rest = floor is not None and pos[1] >= floor - 0.5 and not np.any(vel)
        if not at_rest:
            vel = vel * 0.98 + np.array([0.0, gravity])
            pos = pos + vel
            angle += spin
            if floor is not None and pos[1] > floor and vel[1] > 0:
                pos[1] = floor
                vel = np.array([vel[0] * FRICTION, -vel[1] * REST])
                spin *= 0.5
                if abs(vel[1]) < gravity * 1.5:  # ya no rebota: queda quieto
                    vel, spin = np.zeros(2), 0.0
        age += 1
        if age < FADE_TO and pos[1] < height * 1.2:
            keep.append([pos, vel, size, angle, spin, age])
    st["debris"] = keep
    return keep


def _draw_debris(layer, debris: list, alpha: float) -> None:
    for pos, _vel, size, angle, _spin, age in debris:
        k = _seg(age, FADE_FROM, FADE_TO)
        r = size * (1.0 - 0.6 * k)
        if r < 1.0:
            continue
        facets, _ = rock_polygon(pos, r, int(size * 1000) % 9973, angle)
        draw_rock(layer, facets, alpha * (1.0 - k))


def _burst(st: dict, origin, count: int, unit: float, height: int, rng, cone: float = 1.0, reach=(0.5, 1.4), size=(0.1, 0.24), up: float = -np.pi / 2) -> None:
    """Escombros que salen hacia arriba y afuera desde `origin`."""
    gravity = GRAVITY * height
    for _ in range(count):
        ang = up + rng.uniform(-cone, cone)
        speed = np.sqrt(2.0 * gravity * unit * rng.uniform(*reach))
        st.setdefault("debris", []).append([np.array(origin, np.float64), np.array([np.cos(ang), np.sin(ang)]) * speed, unit * rng.uniform(*size), rng.uniform(0, TAU), rng.normal(0.0, 0.2), 0])


def _puffs(st: dict, origin, unit: float, rng, count: int, ring: bool = True) -> None:
    for k in range(count):
        side = (1.0 if k % 2 else -1.0) if ring else rng.uniform(-1, 1)
        vel = np.array([side * unit * rng.uniform(0.03, 0.07), -unit * rng.uniform(0.0, 0.01)])
        st.setdefault("dust", []).append([np.array(origin, np.float64) + [side * unit * rng.uniform(0.0, 0.5), 0.0], vel, unit * rng.uniform(0.28, 0.5), 0, DUST_LIFE])


def step_dust(st: dict) -> list:
    """Polvo [pos, vel, radio, edad, vida]: se abre, sube un poco y se desvanece."""
    keep = []
    for pos, vel, radius, age, life in st.get("dust", []):
        vel = vel * 0.95 + np.array([0.0, -radius * 0.004])
        age += 1
        if age < life:
            keep.append([pos + vel, vel, radius * 1.025, age, life])
    st["dust"] = keep
    return keep


def _draw_dust(layer, puffs: list, alpha: float) -> None:
    for pos, _vel, radius, age, life in puffs:
        _blob(layer, pos, radius * 0.55, DUST, min(0.3 * alpha, 0.35) * (1.0 - age / life), add=False)


def _sparks(st: dict, pos, unit: float, rng, count: int, color=AMBER) -> None:
    for _ in range(count):
        ang = rng.uniform(0, TAU)
        st.setdefault("sparks", []).append([np.array(pos, np.float64), np.array([np.cos(ang), np.sin(ang) - 0.8]) * unit * rng.uniform(0.02, 0.07), 0, color])


def _step_sparks(st: dict, height: int) -> list:
    keep = []
    for pos, vel, age, *color in st.get("sparks", []):
        vel = vel * 0.85 + np.array([0.0, GRAVITY * height * 0.4])
        if age + 1 < SPARK_LIFE:
            keep.append([pos + vel, vel, age + 1, *color])
    st["sparks"] = keep
    return keep


def _draw_sparks(layer, sparks: list, alpha: float) -> None:
    sigma = max(0.0025 * layer.shape[0], 1.0)
    for spark in sparks:
        pos, _vel, age = spark[:3]
        color = spark[3] if len(spark) > 3 else AMBER
        _blob(layer, pos, sigma, color, min(alpha, 1.0) * (1.0 - age / SPARK_LIFE) * 1.2, add=True)


def _before(st: dict, layer, alpha: float) -> None:
    """El polvo va detrás de todo."""
    _draw_dust(layer, step_dust(st), alpha)


def _after(st: dict, layer, alpha: float, floor: float | None) -> None:
    """Escombros y chispas van delante de todo."""
    _draw_debris(layer, step_debris(st, layer.shape[0], floor), alpha)
    _draw_sparks(layer, _step_sparks(st, layer.shape[0]), alpha)


def _seed(event, point, frame_index: int) -> int:
    start = event.start_frame if event is not None else frame_index
    return int(start) * 7919 + int(point[0])


def _tick(st: dict, event, point, frame_index: int):
    """Cuenta los cuadros de esta activación y da el azar determinista de ese cuadro."""
    st["age"] = st.get("age", -1) + 1
    st.setdefault("seed", _seed(event, point, frame_index))
    return np.random.default_rng(st["seed"] + st["age"] * 977)


# ----- las figuras -----


def _own_phase(runtime, event, wait: int) -> float:
    """La vida del efecto contada desde que la persona apoyó (lo que esperó en el aire no se le
    descuenta: si no, el piso se partía y se apagaba enseguida)."""
    triggers = runtime.effect.triggers
    hold = triggers[0].hold if triggers else 20
    span = (event.end_frame - event.start_frame + 1 + hold) if event is not None else 60
    return float(np.clip((runtime.active_frames - 1 - wait) / max(span - wait, 12), 0.0, 1.0))


def _grounded(body, scale: float, layer) -> bool:
    """Si la persona está parada: los pies bien por debajo de la cadera (en una voltereta el
    pisotón se detectaba con los pies arriba y las grietas salían en el cielo)."""
    hips = [p for p in (body.get("left_hip"), body.get("right_hip")) if p is not None]
    feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
    if not hips or not feet:
        return True
    unit = _unit(scale, layer)
    if max(f[1] for f in feet) <= np.mean([h[1] for h in hips]) + 0.5 * unit:
        return False
    shoulders = [p for p in (body.get("left_shoulder"), body.get("right_shoulder")) if p is not None]
    if shoulders and np.mean([p[1] for p in shoulders]) > np.mean([h[1] for h in hips]) - 0.3 * unit:
        return False  # el torso no está derecho (de costado o de cabeza)
    # Y el pie más bajo apoyado: casi quieto (en el aire, de costado, también queda bajo la cadera).
    low = max(("left_ankle", "right_ankle"), key=lambda n: body.get(n)[1] if body.get(n) is not None else -1e9)
    from vfxglow.engine.waterbend import velocity

    vel = velocity(body, low)
    return vel is None or float(np.linalg.norm(vel)) < 0.12 * unit


def _earth_slam(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    st = _activation(runtime, event, "earth:slam", body)
    if "origin" not in st:  # el punto de contacto se fija una sola vez: el pie más bajo, en el piso
        feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
        floor = _floor(body, scale)
        # Parado varios cuadros seguidos (en lo alto de un salto el pie queda quieto un instante).
        st["ground"] = st.get("ground", 0) + 1 if feet and floor is not None and _grounded(body, scale, layer) else 0
        if st["ground"] < GROUND_FRAMES:
            return  # en el aire (una voltereta): el piso se parte cuando apoye, no en el cielo
        foot = max(feet, key=lambda p: p[1])
        st["origin"] = np.array([float(foot[0]), float(floor)])
        st["wait"] = runtime.active_frames - 1
    origin, unit, height = st["origin"], _unit(scale, layer), layer.shape[0]
    rng = _tick(st, event, origin, frame_index)
    age, u = st["age"], _own_phase(runtime, event, st["wait"])
    _before(st, layer, alpha)
    if age == 0:
        _sparks(st, origin, unit, rng, 6)
    if age == 3:  # tras la pausa de las grietas salen los escombros y el polvo
        _burst(st, origin, int(rng.integers(18, 27)), unit, height, rng, cone=1.1, reach=(0.7, 2.0), size=(0.14, 0.34))
        _burst(st, origin, 4, unit, height, rng, cone=0.7, reach=(0.4, 1.0), size=(0.38, 0.55))  # unos trozos grandes
        _puffs(st, origin, unit, rng, 16)
    grow = min(max(0.1 + 0.07 * age, _ease(_seg(u, 0.0, 0.4))), 1.0)
    cracks = ground_cracks(origin, unit, st["seed"], grow)
    draw_cracks(layer, cracks, origin, unit, alpha * (1.0 - _seg(u, 0.9, 1.0)), amber=1.0 - _seg(u, 0.7, 1.0))
    if age < 3:
        _blob(layer, origin, 0.35 * unit, AMBER, alpha * 0.7 * (1.0 - age / 3.0), add=True)
    _spikes(st, layer, origin, unit, rng, age, u, alpha, cracks)
    _after(st, layer, alpha, origin[1])


def _spikes(st: dict, layer, origin, unit: float, rng, age: int, u: float, alpha: float, cracks: list) -> None:
    """Picos de roca que brotan del piso por las grietas, inclinados hacia afuera: le dan masa al
    pisotón. Salen tras la pausa, se sostienen y al final se desmoronan en escombros."""
    if "spikes" not in st:
        r = np.random.default_rng(st["seed"] + 5)
        spikes = []
        for k in range(int(r.integers(5, 8))):
            side = -1.0 if k % 2 else 1.0
            dist = unit * r.uniform(0.35, 1.5)
            base = np.asarray(origin, np.float64) + [side * dist, r.uniform(-0.12, 0.2) * unit]
            spikes.append((base, unit * r.uniform(0.7, 1.5) * (1.25 - 0.35 * dist / (1.5 * unit)), unit * r.uniform(0.28, 0.42), side * r.uniform(0.15, 0.45), int(r.integers(0, 10**6))))
        spikes.sort(key=lambda sp: sp[0][1])  # los de atrás (más arriba en el cuadro) primero
        st["spikes"] = spikes
    if u >= 0.78:
        if not st.get("crumbled"):
            st["crumbled"] = True
            for base, tall, wide, tilt, seed in st["spikes"]:
                for k in range(4):
                    at = base + np.array([np.sin(tilt), -np.cos(tilt)]) * tall * (0.2 + 0.2 * k)
                    st.setdefault("debris", []).append([at, rng.normal(0, 0.015 * unit, 2), wide * rng.uniform(0.4, 0.7), rng.uniform(0, TAU), rng.normal(0, 0.15), 0])
        return
    rise = _ease(_seg(age, 3, 7))
    if rise <= 0.02:
        return
    for base, tall, wide, tilt, seed in st["spikes"]:
        draw_rock(layer, spike_facets(base, tall * rise, wide, tilt, seed), alpha)


def spike_facets(base, tall: float, wide: float, tilt: float, seed: int) -> list:
    """Un pico de roca: una roca estirada y afilada hacia arriba, con la base en el piso."""
    facets, _ = rock_polygon(np.zeros(2), 1.0, seed)
    out = []
    rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
    for poly, shade in facets:
        y = poly[:, 1]
        taper = np.clip((y + 1.0) / 2.0, 0.15, 1.0)  # arriba (y=-1) fino, abajo ancho
        local = np.stack([poly[:, 0] * wide * 0.5 * taper, (y - 1.0) * tall * 0.5], axis=1)
        out.append((local @ rot.T + np.asarray(base, np.float64), shade))
    return out


def _earth_shield(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    torso = [p for p in (body.get(n) for n in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")) if p is not None]
    if not torso:
        return
    center = np.mean(torso, axis=0)
    st = _activation(runtime, event, "earth:shield", body)
    rng = _tick(st, event, center, frame_index)
    unit, height, u, age = _unit(scale, layer), layer.shape[0], _phase(runtime, event), st["age"]
    n = st.setdefault("n", 5 + st["seed"] % 3)
    hands = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
    start_y = min(max(max([h[1] for h in hands], default=center[1]), center[1]) + 0.8 * unit, 0.98 * layer.shape[0])
    radius, spacing, mid = 0.5 * unit, 0.72 * unit, (n - 1) / 2
    plates = []
    for i in range(n):
        x = center[0] + (i - mid) * spacing
        row = i % 2  # dos filas: las impares un poco más arriba y atrás (un muro, no una fila)
        final = np.array([x, center[1] + 0.15 * unit * ((i - mid) / max(mid, 1)) ** 2 - row * 0.55 * unit])
        t = _seg(u, 0.03 * i, 0.3 + 0.03 * i)
        rise = 1.0 - (1.0 - t) ** 3  # sale frenando (ease-out)
        pos = np.array([x, start_y]) + (final - np.array([x, start_y])) * rise
        pos[1] += np.sin(age * 0.2 + i * 1.3) * 0.025 * unit * _seg(u, 0.3, 0.4)  # flota apenas
        plates.append(pos)
    _before(st, layer, alpha)
    if u >= 0.8:
        if not st.get("crumbled"):  # se deshace: cada placa cae en pedazos
            st["crumbled"] = True
            for pos in plates:
                for _ in range(5):
                    st.setdefault("debris", []).append([pos + rng.normal(0, 0.2 * unit, 2), rng.normal(0, 0.012 * unit, 2) + [0.0, -0.02 * unit], unit * rng.uniform(0.05, 0.12), rng.uniform(0, TAU), rng.normal(0, 0.15), 0])
    else:
        seam_gain = 1.0 - _seg(u, 0.7, 0.8)
        seams, fades = [], []
        for i in range(n - 1):  # la veta ámbar entre placas
            mx, my = (plates[i][0] + plates[i + 1][0]) / 2, (plates[i][1] + plates[i + 1][1]) / 2
            ys = np.linspace(my - 0.55 * unit, my + 0.55 * unit, 6)
            seams.append(np.stack([mx + rng.normal(0, 0.015 * unit, 6), ys], axis=1))
            fades.append(np.full(6, 0.85 * seam_gain * (0.85 + 0.15 * np.sin(age * 0.3 + i))))
        _stroke(layer, seams, fades, 2, max(int(unit * 0.02), 1), alpha, dark=False)
        for i, pos in enumerate(plates):
            facets, _ = rock_polygon(pos, radius, st["seed"] + i * 31, 0.12 * np.sin(i * 2.1))
            draw_rock(layer, _stretch(facets, pos, 0.75, 1.35), alpha * _seg(u, 0.0, 0.08))
    _after(st, layer, alpha, _floor(body, scale))


def _earth_fist(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    found = _limb(body, event)
    if found is None:
        return
    name, wrist = found
    wrist = np.asarray(wrist, np.float64)
    st = _activation(runtime, event, f"earth:fist:{name}", body)
    rng = _tick(st, event, wrist, frame_index)
    unit, u = _unit(scale, layer), _phase(runtime, event)
    elbow = body.get(name.replace("wrist", "elbow").replace("ankle", "knee"))
    along = (wrist - elbow) if elbow is not None and float(np.linalg.norm(wrist - elbow)) > 1 else np.array([1.0, 0.0])
    along = along / max(float(np.linalg.norm(along)), 1e-9)
    perp = np.array([-along[1], along[0]])
    speed = float(np.linalg.norm(wrist - st.get("last", wrist))) / max(unit, 1.0)
    st["last"] = wrist.copy()
    n = st.setdefault("n", 7 + st["seed"] % 3)
    plates = []
    for i in range(n):
        off = (i / max(n - 1, 1) - 0.5) * 0.6 * unit - 0.05 * unit
        side = (1.0 if i % 2 else -1.0) * 0.15 * unit * (0.6 + 0.4 * ((i * 37) % 5) / 4)
        plates.append((wrist + along * off + perp * side, unit * (0.18 + 0.1 * ((i * 53) % 7) / 6)))
    _before(st, layer, alpha)
    if u >= 0.75:
        if not st.get("broke"):  # se desprende el guantelete
            st["broke"] = True
            for pos, r in plates:
                st.setdefault("debris", []).append([pos.copy(), perp * rng.choice([-1.0, 1.0]) * 0.02 * unit + along * 0.02 * unit + [0.0, -0.03 * unit], r * 0.9, rng.uniform(0, TAU), rng.normal(0, 0.2), 0])
    else:
        grow = _ease(_seg(u, 0.0, 0.12))
        if grow > 0.05:
            for i, (pos, r) in enumerate(plates):
                facets, _ = rock_polygon(pos, r * grow, st["seed"] + i * 17, float(np.arctan2(along[1], along[0])))
                draw_rock(layer, facets, alpha)
        if speed > 0.06 and st["age"] % 2 == 0:  # con el golpe suelta lascas y chispas
            _burst(st, wrist + rng.normal(0, 0.1 * unit, 2), 2, unit, layer.shape[0], rng, cone=1.2, reach=(0.05, 0.2), size=(0.05, 0.1), up=np.pi / 2)
            if speed > 0.1:
                _sparks(st, wrist, unit, rng, 2)
    _after(st, layer, alpha, _floor(body, scale))


def _earth_orbit(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    hips = [p for p in (body.get("left_hip"), body.get("right_hip")) if p is not None]
    if not hips:
        return
    center = np.mean(hips, axis=0)
    st = _activation(runtime, event, "earth:orbit", body)
    rng = _tick(st, event, center, frame_index)
    unit, u = _unit(scale, layer), _phase(runtime, event)
    n = st.setdefault("n", 10 + st["seed"] % 4)
    sizes = [unit * (0.18 + 0.24 * ((i * 41) % 7) / 6) for i in range(n)]
    rocks = []
    for i in range(n):
        a = i * TAU / n + u * TAU * 1.5
        ring = 1.0 + 0.25 * ((i * 29) % 3)  # tres anillos: no una sola fila de piedras
        rocks.append((a, center + np.array([np.cos(a) * 2.0 * unit * ring, np.sin(a) * 0.55 * unit * ring - (i % 3) * 0.35 * unit]), sizes[i], i))
    _before(st, layer, alpha)
    if u >= 0.8:
        if not st.get("flung"):  # salen disparadas por la tangente
            st["flung"] = True
            for a, pos, r, _ in rocks:
                vel = np.array([-np.sin(a) * 1.8, np.cos(a) * 0.5]) * 0.12 * unit + np.array([np.cos(a), np.sin(a) * 0.3]) * 0.05 * unit
                st.setdefault("debris", []).append([pos.copy(), vel, r, rng.uniform(0, TAU), rng.normal(0, 0.2), 0])
    else:
        grow = _ease(_seg(u, 0.0, 0.12))
        for back in (True, False):  # primero las de atrás (mitad de arriba de la elipse)
            for a, pos, r, i in rocks:
                if (np.sin(a) < 0) == back and grow > 0.05:
                    facets, _ = rock_polygon(pos, r * grow * (0.7 if back else 1.0), st["seed"] + i * 13, a * 0.5)
                    draw_rock(layer, facets, alpha, dim=0.6 if back else 1.0)
    _after(st, layer, alpha, _floor(body, scale))


def _earth_boulder(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    found = _limb(body, event)
    if found is None:
        return
    name, wrist = found
    wrist = np.asarray(wrist, np.float64)
    st = _activation(runtime, event, f"earth:boulder:{name}", body)
    rng = _tick(st, event, wrist, frame_index)
    unit, u, height = _unit(scale, layer), _phase(runtime, event), layer.shape[0]
    width = layer.shape[1]
    floor = _floor(body, scale)
    elbow = body.get(name.replace("wrist", "elbow").replace("ankle", "knee"))
    along = (wrist - elbow) if elbow is not None and float(np.linalg.norm(wrist - elbow)) > 1 else np.array([1.0, 0.0])
    along = along / max(float(np.linalg.norm(along)), 1e-9)
    radius = 1.3 * unit  # una roca de verdad (con 0,55 parecía un dado)
    _before(st, layer, alpha)
    if not st.get("shattered"):
        if u < 0.4:  # sube del piso y flota a la altura de la mano
            hold = wrist + along * 0.9 * unit + [0.0, -0.1 * unit]
            ground = np.array([hold[0], floor if floor is not None else wrist[1] + unit])
            rise = 1.0 - (1.0 - _seg(u, 0.0, 0.25)) ** 3
            pos = ground + (hold - ground) * rise + [0.0, np.sin(st["age"] * 0.25) * 0.02 * unit * _seg(u, 0.25, 0.4)]
            st["pos"] = pos
            if u < 0.25 and st["age"] % 3 == 0:
                _puffs(st, ground, unit * 0.5, rng, 1, ring=False)
            grow = 0.6 + 0.4 * rise
        else:
            if "vel" not in st:  # se lanza a lo largo del antebrazo
                st["vel"], st["angle"] = along * 0.22 * unit, 0.0
            st["pos"] = st["pos"] + st["vel"]
            st["angle"] += 0.18
            grow = 1.0
            if st["age"] % 2 == 0:
                _sparks(st, st["pos"] - st["vel"] * 0.5, unit * 0.5, rng, 1)
        pos = st["pos"]
        outside = not (0.03 * width < pos[0] < 0.97 * width and 0.03 * height < pos[1] < 0.97 * height)
        if "vel" in st and (u >= 0.7 or outside):  # revienta en trizas
            st["shattered"] = True
            _burst(st, pos, 26, unit, height, rng, cone=np.pi, reach=(0.3, 1.2), size=(0.1, 0.3))
            for sh in st["debris"][-26:]:
                sh[1] = sh[1] * 0.8 + st["vel"] * 0.3
            _puffs(st, pos, unit, rng, 10, ring=False)
            _sparks(st, pos, unit, rng, 5)
        else:
            facets, _ = rock_polygon(pos, radius * grow, st["seed"], st.get("angle", 0.0))
            draw_rock(layer, facets, alpha)
    _after(st, layer, alpha, floor)


# ----- cristales de jade -----


def crystal_facets(base, tall: float, wide: float, tilt: float) -> list:
    """Un prisma de cristal con la base en el piso: tres caras (sombra, centro y luz) y la punta
    tallada en tres triángulos. Devuelve (polígono, sombra) como las rocas, para draw_rock."""
    w, h = wide * 0.5, tall
    left, mid, right = -w, -0.12 * w, 0.42 * w
    shoulder = 0.78 * h
    faces = [
        (np.array([[left, 0], [left, -shoulder], [mid, -shoulder - 0.06 * h], [mid, 0]]), 0.18),  # cara de sombra
        (np.array([[mid, 0], [mid, -shoulder - 0.06 * h], [right, -shoulder - 0.03 * h], [right, 0]]), 0.55),
        (np.array([[right, 0], [right, -shoulder - 0.03 * h], [w, -shoulder], [w, 0]]), 0.9),  # cara de luz
        (np.array([[left, -shoulder], [0.0, -h], [mid, -shoulder - 0.06 * h]]), 0.3),  # la punta
        (np.array([[mid, -shoulder - 0.06 * h], [0.0, -h], [right, -shoulder - 0.03 * h]]), 0.7),
        (np.array([[right, -shoulder - 0.03 * h], [0.0, -h], [w, -shoulder]]), 1.0),
    ]
    rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
    base = np.asarray(base, np.float64)
    out = []
    for poly, shade in faces:
        local = poly.astype(np.float64)
        center = local.mean(axis=0)
        # draw_rock toma el primer punto como el centro de la faceta (de ahí parte las costuras).
        out.append((np.vstack([center, local]) @ rot.T + base, shade))
    return out


def _glint(layer, pos, size: float, a: float) -> None:
    """Un destello en estrella (cruz fina y brillante) sobre una cara del cristal."""
    for d in (np.array([1.0, 0.0]), np.array([0.0, 1.0])):
        for k in np.linspace(-1, 1, 7):
            _blob(layer, pos + d * k * size, max(size * 0.12, 0.6), np.array([0.9, 1.0, 0.95], np.float32), a * (1 - abs(k)) ** 2, add=True)


def _earth_crystals(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    """Cristales de jade que brotan del piso en racimo alrededor del pie (o delante de la persona),
    con grietas verdes en la base, destellos que recorren las caras y, al final, se quiebran en
    esquirlas verdes."""
    st = _activation(runtime, event, "earth:crystals", body)
    unit, height = _unit(scale, layer), layer.shape[0]
    if "origin" not in st:
        feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
        floor = _floor(body, scale)
        st["ground"] = st.get("ground", 0) + 1 if feet and floor is not None and _grounded(body, scale, layer) else 0
        if st["ground"] < GROUND_FRAMES:
            return  # brotan del piso: con la persona en el aire no hay piso donde
        foot = max(feet, key=lambda p: p[1])
        st["origin"] = np.array([float(foot[0]), float(floor)])
        st["wait"] = runtime.active_frames - 1
    origin = st["origin"]
    u = _own_phase(runtime, event, st["wait"])
    rng = _tick(st, event, origin, frame_index)
    age = st["age"]
    if "crystals" not in st:
        r = np.random.default_rng(st["seed"] + 11)
        crystals = []
        for k in range(int(r.integers(7, 11))):
            side = (k % 2) * 2 - 1.0 if k else 0.0
            dist = unit * (0.15 + 0.32 * k) * r.uniform(0.8, 1.15)
            base = origin + [side * dist, r.uniform(-0.1, 0.25) * unit]
            tall = unit * r.uniform(0.9, 2.1) * (1.3 - 0.45 * min(dist / (2.5 * unit), 1.0))  # los del centro, más altos
            crystals.append((base, tall, tall * r.uniform(0.3, 0.42), side * r.uniform(0.08, 0.5) + r.uniform(-0.1, 0.1), k * 0.37))
        crystals.sort(key=lambda c: c[0][1])  # de atrás hacia adelante
        st["crystals"] = crystals
    _before(st, layer, alpha)
    cracks = ground_cracks(origin, unit * 0.8, st["seed"], min(0.15 + 0.12 * age, 1.0))
    draw_cracks(layer, cracks, origin, unit, alpha * (1.0 - _seg(u, 0.85, 1.0)), amber=1.0 - _seg(u, 0.75, 1.0), color=JADE)
    if age < 4:
        _blob(layer, origin, 0.5 * unit, JADE, alpha * 0.6 * (1.0 - age / 4.0), add=True)
    if u >= 0.8:
        if not st.get("shattered"):  # se quiebran: esquirlas verdes y destellos
            st["shattered"] = True
            for base, tall, wide, tilt, _delay in st["crystals"]:
                for k in range(3):
                    at = base + np.array([np.sin(tilt), -np.cos(tilt)]) * tall * (0.25 + 0.3 * k)
                    ang = rng.uniform(-np.pi * 0.9, -np.pi * 0.1)
                    st.setdefault("shards", []).append([at, np.array([np.cos(ang), np.sin(ang)]) * unit * rng.uniform(0.05, 0.12), wide * rng.uniform(0.25, 0.45), rng.uniform(0, TAU), rng.normal(0, 0.25), 0])
                _sparks(st, base + [0.0, -tall * 0.5], unit, rng, 3, color=JADE)
    else:
        for base, tall, wide, tilt, delay in st["crystals"]:
            rise = _ease(_seg(age, 1 + delay * 2, 6 + delay * 2))  # brotan escalonados, del centro afuera
            if rise <= 0.02:
                continue
            draw_rock(layer, crystal_facets(base, tall * rise, wide, tilt), alpha * 0.92, palette=CRYSTAL)
            # El brillo interior: una veta de energía por el centro del prisma.
            axis = np.array([np.sin(tilt), -np.cos(tilt)])
            vein = np.array([base + axis * tall * rise * f for f in np.linspace(0.1, 0.8, 6)])
            _stroke(layer, [vein], [np.linspace(0.7, 0.2, 6)], 1, max(int(wide * 0.06), 1), alpha * 0.7, dark=False, color=JADE)
            # Destellos que suben por la cara de luz.
            t = (age * 0.07 + delay) % 1.0
            if rise > 0.9 and t < 0.5:
                at = base + axis * tall * (0.2 + 0.6 * t * 2) + np.array([np.cos(tilt), np.sin(tilt)]) * wide * 0.3
                _glint(layer, at, wide * 0.35, alpha * np.sin(np.pi * t * 2))
    shards = {"debris": st.get("shards", [])}
    step_debris(shards, height, origin[1])
    st["shards"] = shards["debris"]
    for pos, _vel, size, angle, _spin, a_age in st["shards"]:
        k = _seg(a_age, FADE_FROM, FADE_TO)
        if size * (1 - 0.6 * k) >= 1.0:
            facets, _ = rock_polygon(pos, size * (1 - 0.6 * k), int(size * 1000) % 9973, angle)
            draw_rock(layer, facets, alpha * (1 - k), palette=CRYSTAL)
    _after(st, layer, alpha, origin[1])


def earthbend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    figure = {
        "earth_slam": _earth_slam,
        "earth_shield": _earth_shield,
        "earth_fist": _earth_fist,
        "earth_orbit": _earth_orbit,
        "earth_boulder": _earth_boulder,
        "earth_crystals": _earth_crystals,
    }.get(shape)
    if figure is not None:
        figure(body, scale, frame_index, runtime, layer, alpha, event)
    return []
