"""Efectos que llenan el espacio alrededor del rostro (adornos `type: adornment`, acción `ambient`).

Casi todo lo del catálogo cara va sobre la piel y deja vacíos la ropa y el fondo (facial_2 y facial_3:
~1,5% de la pantalla encendida). Estos van afuera y por eso pueden coincidir con un efecto de cara.
Usan las etiquetas de analysis/regions.py (`runtime.regions`).

- head_portal: un anillo de energía detrás de la cabeza (`render.occlude`: el pelo lo tapa). Se abre,
  gira en perspectiva con la cabeza y al final se contrae en un punto brillante.
- head_halo: un aro que baja sobre la cabeza, se inclina con ella y se suelta en polvo.
- garment_wave: una onda de luz recorre la prenda sin taparla (`render.blend: tint` conserva el
  tejido) y enciende solo el borde entre prenda y fondo; un borde interno puede ser un error del
  modelo, que parte la prenda en dos (facial_3, 11,5 s). Sin prenda a la vista (primer plano), un aro.
- black_holes: dos o tres agujeros negros pequeños, cada uno de un color, en el fondo libre. Tienen
  centro negro de verdad (`render.blend: over`: la luz sola no oscurece), se tragan polvo de luz que
  sale de detrás de la persona y al final implosionan. Sobre la cara no van: un punto oscuro en la piel
  parece un lunar o una herida.
- hair_energy: mechones de luz que salen del borde real del pelo y se atrasan cuando la cabeza se
  mueve, con pulsos que recorren el contorno (`render.occlude`: nunca caen sobre la cara). Sin pelo a
  la vista, un aro.
- behind_ghost: un fantasma asoma detrás del hombro (`render.occlude`). Si la persona gira la cabeza
  hacia él, se deshace y reaparece del otro lado. En un primer plano no hay hombro a la vista: asoma
  por la esquina de arriba, donde queda fondo libre.
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.analysis.regions import BACKGROUND, GARMENT, HAIR
from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import disintegrate, fine, melt
from vfxglow.engine.face_glow import WHITE, Face, _seed
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
AMBIENT = ("head_portal", "head_halo", "garment_wave", "black_holes", "hair_energy", "behind_ghost")
GOLD = np.array([1.0, 0.82, 0.35], np.float32)
# Portal: radio en unidades de cara, tope respecto al ancho del cuadro, brazos de la espiral y polvo.
PORTAL_RADIUS = 2.4
PORTAL_MAX = 0.62
PORTAL_ARMS = 5
PORTAL_MOTES = 26
# Aro: alto sobre las cejas, ancho y aplastado por la perspectiva (unidades de cara).
HALO_LIFT = 2.15
HALO_WIDTH = 0.95
HALO_FLAT = 0.24
# Onda: ancho respecto al alto de la prenda, luz máxima y tramos de borde que no valen la pena.
WAVE_WIDTH = 0.2
WAVE_LIGHT = 0.42
WAVE_SOFT = 7.0
WAVE_FOLLOW = 0.35
EDGE_MIN = 14
EDGE_SMOOTH = 15
WAVE_WAYS = ("down", "up", "out")
# Agujeros: tamaño (unidades de cara y fracción del ancho), distancia mínima a la cabeza, fondo libre
# exigido alrededor y polvo que se tragan.
HAIR_STRANDS = 36
HAIR_LENGTH = (0.3, 0.8)
HAIR_LAG = 3.5
HAIR_PULSES = 3
# Fantasma: escala del dibujo en unidades de cara, dónde queda respecto a la cabeza, cuánto debe girar
# la cabeza (grados, respecto a su postura habitual) y los tiempos del cambio de lado (s).
GHOST_SIZE = 0.75
GHOST_MAX = 0.17
GHOST_BESIDE = 2.35
GHOST_BELOW = 0.65
GHOST_TURN = 12.0
GHOST_OUT = 0.3
GHOST_AWAY = 0.25
GHOST_IN = 0.35
GHOST_TINT = np.array([0.72, 0.92, 1.0], np.float32)
HOLE_RADIUS = 0.34
HOLE_MIN, HOLE_MAX = 0.03, 0.065
HOLE_CLEAR = 1.6
HOLE_FREE = 0.92
HOLE_GRID = (8, 13)
HOLE_MOTES = 16
HOLE_ARMS = 5
HOLE_TINTS = (
    np.array([0.55, 0.2, 1.0], np.float32),
    np.array([0.1, 0.85, 1.0], np.float32),
    np.array([1.0, 0.15, 0.6], np.float32),
    np.array([1.0, 0.5, 0.05], np.float32),
    np.array([0.2, 1.0, 0.4], np.float32),
    np.array([0.2, 0.35, 1.0], np.float32),
)


def _head(face: Face) -> np.ndarray:
    return face.place([(0.0, 0.1)])[0]


def _yaw_squash(runtime) -> float:
    """Cuánto se aplasta de lado lo que está detrás de la cabeza cuando esta gira."""
    yaw = (getattr(runtime, "head_pose", None) or (0.0,))[0]
    return float(np.clip(np.cos(np.radians(yaw) * 1.2), 0.55, 1.0))


def _ellipse(center: np.ndarray, rx: float, ry: float, tilt: float, start: float = 0.0, sweep: float = TAU, count: int = 72) -> np.ndarray:
    t = np.linspace(start, start + sweep, count)
    x, y = np.cos(t) * rx, np.sin(t) * ry
    c, s = np.cos(tilt), np.sin(tilt)
    return center + np.stack([x * c - y * s, x * s + y * c], axis=1)


def _portal(face: Face, u: float, frame_index: int, runtime, layer, color, alpha: float, seed: int) -> list:
    height, width = layer.shape[:2]
    center = _head(face)
    tint = np.asarray(color, np.float32)
    opened = _ease(_seg(u, 0.0, 0.16))
    shut = _seg(u, 0.86, 1.0)
    radius = min(PORTAL_RADIUS * face.unit, PORTAL_MAX * width) * opened * (1.0 - shut) ** 2
    if radius < 1.0:
        if shut > 0.0:  # el punto brillante en que termina
            splat(layer, float(center[0]), float(center[1]), 0.5 * face.unit, tint, alpha, runtime.kernels)
        return []
    squash = _yaw_squash(runtime)
    tilt = float(np.arctan2(face.ux[1], face.ux[0]))
    spin = frame_index * 0.07
    ring = _ellipse(center, radius * squash, radius, tilt)
    fill_polygon(layer, ring, tint, alpha * 0.05, 1.0, feather=4.0)
    out: list = [(ring, tint)]
    for k in range(PORTAL_ARMS):  # la espiral que da profundidad
        q = np.linspace(0.0, 1.0, 40)
        a = spin + TAU * k / PORTAL_ARMS + q * 2.4
        r = radius * (1.0 - 0.72 * q)
        arm = center + np.stack([np.cos(a) * r * squash, np.sin(a) * r], axis=1)
        fine([arm], tint, alpha * 0.55, layer, width=1.4)
    for sign, size, length in ((1.0, 0.9, 2.0), (-1.0, 0.8, 1.3)):
        out.append((_ellipse(center, radius * size * squash, radius * size, tilt, spin * sign * 1.8, length), tint * 0.8 + WHITE * 0.2))
    rng = np.random.default_rng(seed)
    angles, offsets = rng.uniform(0, TAU, PORTAL_MOTES), rng.uniform(0, 1, PORTAL_MOTES)
    for a, offset in zip(angles, offsets, strict=True):  # el polvo que el portal se traga
        age = (frame_index * 0.02 + offset) % 1.0
        r = radius * (1.3 - 0.8 * age)
        turn = float(a) + age * 1.6
        at = center + np.array([np.cos(turn) * r * squash, np.sin(turn) * r])
        splat(layer, float(at[0]), float(at[1]), 0.035 * face.unit + 1.0, tint, alpha * 0.7 * float(np.sin(age * np.pi)), runtime.kernels)
    return out


def _halo(face: Face, u: float, frame_index: int, runtime, layer, color, alpha: float, seed: int) -> list:
    height = layer.shape[0]
    tint = np.asarray(color, np.float32) * 0.45 + GOLD * 0.55
    arrive = _ease(_seg(u, 0.0, 0.2))
    up = face.uy / face.unit
    above = _head(face) - up * (HALO_LIFT + 1.2 * (1.0 - arrive)) * face.unit
    # En un primer plano la cabeza llega al borde: el aro baja sobre el pelo pero no sale del cuadro.
    above = np.array([above[0], max(float(above[1]), 0.06 * height)])
    rx, ry = HALO_WIDTH * face.unit, HALO_FLAT * face.unit
    tilt = float(np.arctan2(face.ux[1], face.ux[0]))
    out: list = [(_ellipse(above, rx, ry, tilt), tint)]
    for k in range(5):  # brillos que recorren el aro
        a = frame_index * 0.09 + TAU * k / 5
        at = _ellipse(above, rx, ry, tilt, a, 0.0, 1)[0]
        splat(layer, float(at[0]), float(at[1]), 0.05 * face.unit + 1.0, WHITE, alpha * 0.8, runtime.kernels)
    return melt(out, u, face, layer, tint, alpha, runtime.kernels, seed, start=0.72)


def _edges(labels: np.ndarray, region: int = GARMENT) -> list[np.ndarray]:
    """Los tramos del borde de una región (la prenda, el pelo) que dan al fondo."""
    area = (labels == region).astype(np.uint8)
    contours, _ = cv2.findContours(area, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return []
    height, width = labels.shape[:2]
    outline = max(contours, key=len).reshape(-1, 2)
    open_air = cv2.dilate((labels == BACKGROUND).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    xs, ys = outline[:, 0], outline[:, 1]
    keep = open_air[ys, xs] & (xs > 1) & (xs < width - 2) & (ys > 1) & (ys < height - 2)
    runs, start = [], None
    for k, on in enumerate([*keep, False]):
        if on and start is None:
            start = k
        elif not on and start is not None:
            if k - start >= EDGE_MIN:
                runs.append(outline[start:k].astype(np.float64))
            start = None
    kernel = np.ones(EDGE_SMOOTH) / EDGE_SMOOTH
    pad = EDGE_SMOOTH // 2
    out = []
    for run in runs:  # el modelo trabaja a 256 px: sin suavizar, el borde sale escalonado
        padded = np.pad(run, ((pad, pad), (0, 0)), mode="edge")
        out.append(np.stack([np.convolve(padded[:, 0], kernel, "valid"), np.convolve(padded[:, 1], kernel, "valid")], axis=1))
    return out


def _wave(u: float, labels: np.ndarray, runtime, layer, color, alpha: float, seed: int, st: dict) -> list:
    height, width = layer.shape[:2]
    rows = np.flatnonzero((labels == GARMENT).any(axis=1))
    if rows.size == 0:
        return []
    top, bottom = float(rows[0]), float(rows[-1])
    # El marco de la prenda con inercia: el del modelo salta unos píxeles entre cuadros.
    box = st.get("box")
    st["box"] = (top, bottom) if box is None else (box[0] * 0.8 + top * 0.2, box[1] * 0.8 + bottom * 0.2)
    top, bottom = st["box"]
    tall = max(bottom - top, 1.0)
    way = st.setdefault("way", WAVE_WAYS[seed % len(WAVE_WAYS)])
    travel = -WAVE_WIDTH + (1.0 + 2.0 * WAVE_WIDTH) * _ease(u)
    if way == "out":  # desde el centro hacia los lados
        cols = np.flatnonzero((labels == GARMENT).any(axis=0))
        mid = (float(cols[0]) + float(cols[-1])) / 2.0
        half = max(float(cols[-1]) - mid, 1.0)
        place = np.abs(np.arange(width, dtype=np.float32) - mid) / half
        band = np.exp(-(((place - travel) / WAVE_WIDTH) ** 2))[None, :]
        at = lambda point: float(np.exp(-(((abs(point[0] - mid) / half - travel) / WAVE_WIDTH) ** 2)))  # noqa: E731
    else:
        reach = travel if way == "down" else 1.0 - travel
        place = (np.arange(height, dtype=np.float32) - top) / tall
        band = np.exp(-(((place - reach) / WAVE_WIDTH) ** 2))[:, None]
        at = lambda point: float(np.exp(-((((point[1] - top) / tall - reach) / WAVE_WIDTH) ** 2)))  # noqa: E731
    # Suave en el espacio y en el tiempo: una mano rápida abre huecos de un cuadro en la máscara y la
    # luz los dibujaba como manchas con escalones (facial_3, 8 s).
    soft = cv2.GaussianBlur((labels == GARMENT).astype(np.float32), (0, 0), WAVE_SOFT)
    old = st.get("soft")
    st["soft"] = soft if old is None else old + (soft - old) * WAVE_FOLLOW
    light = band * st["soft"] * np.float32(WAVE_LIGHT * alpha)
    tint = np.asarray(color, np.float32)
    layer[..., :3] += light[..., None] * tint
    layer[..., 3] = np.clip(layer[..., 3] + light, 0.0, 1.0)
    out: list = []
    for edge in _edges(labels):
        lit = np.array([at(p) > 0.3 for p in edge[::4]])
        idx = np.flatnonzero(lit) * 4
        if idx.size >= 3:
            out.append((edge[idx[0] : idx[-1] + 1], tint))
    return out


def _free(labels: np.ndarray | None, at: np.ndarray, radius: float) -> float:
    """Fracción de fondo alrededor de un punto."""
    if labels is None:
        return 1.0
    x, y, r = int(at[0]), int(at[1]), max(int(radius * 1.8), 2)
    patch = labels[max(y - r, 0) : y + r, max(x - r, 0) : x + r]
    return float((patch == BACKGROUND).mean()) if patch.size else 0.0


def _place_holes(face: Face, labels: np.ndarray | None, head: np.ndarray, shape: tuple[int, ...], seed: int) -> list[dict]:
    """Dónde van: en el fondo libre, lo más cerca de la cabeza que se pueda y separados entre sí."""
    height, width = shape[:2]
    rng = np.random.default_rng(seed)
    count = int(rng.integers(2, 4))
    tints = rng.permutation(len(HOLE_TINTS))
    rows, cols = HOLE_GRID[1], HOLE_GRID[0]
    grid = [np.array([width * (0.5 + c) / cols, height * (0.5 + r) / rows]) for r in range(rows) for c in range(cols)]
    size = float(np.clip(HOLE_RADIUS * face.unit, HOLE_MIN * width, HOLE_MAX * width))
    free = [p for p in grid if np.linalg.norm(p - head) >= HOLE_CLEAR * face.unit and _free(labels, p, size) >= HOLE_FREE]
    free.sort(key=lambda p: float(np.linalg.norm(p - head)) + rng.uniform(0.0, face.unit))
    picked: list[np.ndarray] = []
    for p in free:
        if all(np.linalg.norm(p - q) >= 4.5 * size for q in picked):
            picked.append(p)
        if len(picked) == count:
            break
    return [
        {
            "offset": p - head,
            "radius": size * float(rng.uniform(0.75, 1.25)),
            "tint": HOLE_TINTS[tints[k]],
            "tilt": float(rng.uniform(-0.6, 0.6)),
            "born": 0.08 * k,
            "turn": float(rng.choice([-1.0, 1.0])),
        }
        for k, p in enumerate(picked)
    ]


def _black_hole(layer, center: np.ndarray, r: float, tint: np.ndarray, spin: float, alpha: float) -> None:
    """El centro negro y, alrededor, un anillo de luz suave, más fuerte de un lado que del otro (la
    materia que gira hacia la cámara brilla más). Con una elipse fina parecía Saturno."""
    height, width = layer.shape[:2]
    reach = int(r * 1.9) + 2
    x0, y0 = max(int(center[0]) - reach, 0), max(int(center[1]) - reach, 0)
    x1, y1 = min(int(center[0]) + reach, width), min(int(center[1]) + reach, height)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dist = np.hypot(xx - float(center[0]), yy - float(center[1]))
    dark = np.clip((r - dist) / max(0.12 * r, 1.0), 0.0, 1.0)
    dark *= np.float32(alpha)
    angle = np.arctan2(yy - float(center[1]), xx - float(center[0]))
    glow = np.exp(-(((dist - r * 1.22) / (0.34 * r)) ** 2)) * (0.75 + 0.55 * np.cos(angle - spin)) * np.float32(alpha)
    patch = layer[y0:y1, x0:x1]
    patch[..., :3] *= (1.0 - dark)[..., None]
    patch[..., 3] = np.maximum(patch[..., 3], dark)
    patch[..., :3] += (glow * (1.0 - dark))[..., None] * tint
    patch[..., 3] = np.clip(patch[..., 3] + glow * 0.8, 0.0, 1.0)


def _holes(face: Face, u: float, frame_index: int, runtime, layer, alpha: float, seed: int, event) -> None:
    st = runtime.swoosh.setdefault(f"_holes:{event.start_frame if event else 0}", {})
    head = _head(face)
    if "list" not in st:
        st["list"] = _place_holes(face, getattr(runtime, "regions", None), head, layer.shape, seed)
        st["head"] = head.copy()
    st["head"] = st["head"] + (head - st["head"]) * 0.12  # flotan: siguen a la cabeza con retraso
    for k, hole in enumerate(st["list"]):
        opened = _ease(_seg(u, hole["born"], hole["born"] + 0.14))
        shut = _seg(u, 0.84 + 0.04 * k, 0.95 + 0.04 * k)
        center = st["head"] + hole["offset"]
        tint = hole["tint"]
        r = hole["radius"] * opened * (1.0 - shut) ** 2
        if shut > 0.0:  # la implosión deja un anillo que se abre
            ring = _ellipse(center, hole["radius"] * (1.0 + 3.0 * shut), hole["radius"] * (1.0 + 3.0 * shut), 0.0, count=40)
            fine([ring], tint, alpha * (1.0 - shut), layer, width=1.4)
        if r < 1.0:
            continue
        spin = frame_index * 0.16 * hole["turn"]
        _black_hole(layer, center, r, tint, spin, alpha)
        fine([_ellipse(center, r * 1.06, r * 1.06, 0.0, count=40)], WHITE * 0.6 + tint * 0.4, alpha, layer, width=1.3)
        for j in range(HOLE_ARMS):  # la materia que cae girando en espiral
            q = np.linspace(0.0, 1.0, 26)
            a = spin + TAU * j / HOLE_ARMS + (1.0 - q) ** 2 * 2.6 * hole["turn"]
            radius = r * (1.08 + 1.5 * (1.0 - q))
            arm = center + np.stack([np.cos(a) * radius, np.sin(a) * radius * 0.82], axis=1)
            fine([arm], tint, alpha * 0.7, layer, width=1.2)
        toward = center - head
        length = max(float(np.linalg.norm(toward)), 1.0)
        side = np.array([-toward[1], toward[0]]) / length
        for m in range(HOLE_MOTES):  # el polvo de luz que se traga: se curva y se acelera al caer
            age = (frame_index * 0.022 + m * 0.618 + k * 0.3) % 1.0
            fall = age**2
            bend = float(np.sin(age * np.pi)) * (0.25 * length) * hole["turn"] * (0.6 + 0.4 * float(np.sin(m * 2.4)))
            at = head + toward * fall + side * bend
            splat(layer, float(at[0]), float(at[1]), 0.02 * face.unit + 1.0, tint, alpha * 0.8 * float(np.sin(age * np.pi)) * opened, runtime.kernels)


def _hair(face: Face, u: float, frame_index: int, runtime, layer, color, alpha: float, seed: int, st: dict, labels: np.ndarray) -> list:
    runs = _edges(labels, HAIR)
    if not runs:
        return []
    head = _head(face)
    moved = head - st.get("head", head)
    st["head"] = head.copy()
    st["vel"] = st.get("vel", np.zeros(2)) * 0.75 + moved * 0.25
    trail = -st["vel"] * HAIR_LAG  # los mechones se quedan atrás cuando la cabeza se mueve
    grow = _ease(_seg(u, 0.0, 0.15)) * (1.0 - _ease(_seg(u, 0.84, 1.0)))
    path = np.vstack(runs)
    tint = np.asarray(color, np.float32)
    rng = np.random.default_rng(seed)
    places, sizes = rng.uniform(0, 1, HAIR_STRANDS), rng.uniform(*HAIR_LENGTH, HAIR_STRANDS)
    roots = st.setdefault("roots", {})
    q = np.linspace(0.0, 1.0, 12)
    for k in range(HAIR_STRANDS):
        wanted = path[int(places[k] * (len(path) - 1))]
        old = roots.get(k)
        near = old is not None and float(np.linalg.norm(wanted - old)) < 0.4 * face.unit
        roots[k] = old + (wanted - old) * 0.35 if near else wanted  # el borde del modelo tiembla
        root = roots[k]
        away = (root - head) / max(float(np.linalg.norm(root - head)), 1.0)
        side = np.array([-away[1], away[0]])
        length = sizes[k] * face.unit * grow
        wave = np.sin(q * 6.0 - frame_index * 0.28 + k * 1.7) * 0.14 * length * q
        strand = root + np.outer(q * length, away) + np.outer(wave, side) + np.outer(q**2, trail)
        fine([strand], tint * 0.6 + WHITE * 0.4, alpha * 0.8 * grow, layer, width=1.1)
        splat(layer, float(strand[-1, 0]), float(strand[-1, 1]), 0.02 * face.unit + 0.8, tint, alpha * grow, runtime.kernels)
    out: list = []
    for run in runs:  # pulsos que recorren el contorno del pelo
        size = max(len(run) // 6, 8)
        for j in range(HAIR_PULSES):
            at = int(((frame_index * 0.014 + j / HAIR_PULSES) % 1.0) * max(len(run) - size, 1))
            if size >= 3 and grow > 0.2:
                out.append((run[at : at + size], tint))
    return out


def _ghost_lines(center: np.ndarray, size: float, frame_index: int) -> list[np.ndarray]:
    """Un fantasma de sábana: cúpula, cuerpo que se angosta y borde que ondula, con dos ojos y la boca
    abierta. `size` es el medio ancho."""
    a = np.linspace(np.pi, 2.0 * np.pi, 22)
    dome = np.stack([np.cos(a), np.sin(a) * 1.05 - 0.15], axis=1)
    q = np.linspace(0.0, 1.0, 12)
    right = np.stack([1.0 + 0.1 * q, -0.15 + 1.75 * q], axis=1)
    h = np.linspace(1.1, -1.1, 34)
    hem = np.stack([h, 1.6 + 0.16 * np.sin(h * 7.0 + frame_index * 0.25)], axis=1)
    left = np.stack([-1.1 + 0.1 * q, 1.6 - 1.75 * q], axis=1)
    body = center + np.vstack([dome, right, hem, left]) * size
    t = np.linspace(0.0, TAU, 18)
    circle = np.stack([np.cos(t), np.sin(t)], axis=1)
    eyes = [center + (circle * [0.17, 0.25] + [x, -0.2]) * size for x in (-0.38, 0.38)]
    mouth = center + (circle * [0.2, 0.3] + [0.0, 0.42]) * size
    return [body, *eyes, mouth]


def _ghost(face: Face, u: float, frame_index: int, runtime, layer, alpha: float, seed: int, st: dict) -> None:
    height, width = layer.shape[:2]
    fps = getattr(runtime, "fps", 30.0) or 30.0
    head = _head(face)
    st.setdefault("side", 1.0 if float(head[0]) < width / 2.0 else -1.0)
    yaw = (getattr(runtime, "head_pose", None) or (0.0,))[0]
    st["usual"] = st.get("usual", yaw) + (yaw - st.get("usual", yaw)) * 0.02
    turned = yaw - st["usual"]
    frames = runtime.active_frames
    if st.get("swap") is None and frames > 0.6 * fps and abs(turned) >= GHOST_TURN and np.sign(turned) == st["side"]:
        st["swap"] = frames  # la persona mira hacia él
    size = min(GHOST_SIZE * face.unit, GHOST_MAX * width)
    wanted = head + np.array([st["side"] * GHOST_BESIDE * face.unit, GHOST_BELOW * face.unit])
    wanted = np.clip(wanted, [size * 1.2, size * 1.4], [width - size * 1.2, height - size * 1.4])
    labels = getattr(runtime, "regions", None)
    if labels is not None and _free(labels, wanted, size) < 0.35:  # tapado por la persona: la esquina de arriba
        wanted = np.array([wanted[0], size * 1.4])
    st["at"] = wanted if "at" not in st or st.get("jump") else st["at"] + (wanted - st["at"]) * 0.1
    st["jump"] = False
    rise = _ease(_seg(u, 0.0, 0.14))
    at = st["at"] + np.array([np.sin(frame_index * 0.05) * 0.1 * face.unit, np.sin(frame_index * 0.08) * 0.08 * face.unit + (1.0 - rise) * 1.2 * face.unit])
    gain = alpha * rise
    lines = _ghost_lines(at, size, frame_index)
    if st.get("swap") is not None:
        age = (frames - st["swap"]) / fps
        if age < GHOST_OUT:
            left = disintegrate([(curve, GHOST_TINT) for curve in lines], age / GHOST_OUT, face.unit, layer, gain, runtime.kernels, seed)
            fine([item[0] for item in left], GHOST_TINT, gain, layer, width=1.3)
            return
        if age < GHOST_OUT + GHOST_AWAY:
            if not st.get("flipped"):
                st["side"], st["flipped"], st["jump"] = -st["side"], True, True
            return
        back = _seg(age, GHOST_OUT + GHOST_AWAY, GHOST_OUT + GHOST_AWAY + GHOST_IN)
        gain *= back
        if back >= 1.0:
            st["swap"], st["flipped"], st["usual"] = None, False, yaw
    fill_polygon(layer, lines[0], GHOST_TINT, gain * 0.1, 1.0, feather=3.0)
    left = melt([(curve, GHOST_TINT) for curve in lines], u, face, layer, GHOST_TINT, gain, runtime.kernels, seed)
    fine([item[0] if isinstance(item, tuple) else item for item in left], GHOST_TINT, gain, layer, width=max(1.2, 0.012 * face.unit))
    rng = np.random.default_rng(seed)
    for k in range(14):  # el vapor que lo rodea
        age = (frame_index * 0.015 + k * 0.618) % 1.0
        x, y = rng.uniform(-1.0, 1.0), rng.uniform(-0.5, 1.2)
        p = at + np.array([x, y - age * 0.9]) * face.unit
        splat(layer, float(p[0]), float(p[1]), 0.1 * face.unit + 1.0, GHOST_TINT, gain * 0.12 * float(np.sin(age * np.pi)), runtime.kernels)


def ambient_fx(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    seed = _seed(shape, body, event)
    if shape == "head_portal":
        return _portal(face, u, frame_index, runtime, layer, color, alpha, seed)
    if shape == "head_halo":
        return _halo(face, u, frame_index, runtime, layer, color, alpha, seed)
    if shape == "black_holes":
        _holes(face, u, frame_index, runtime, layer, alpha, seed, event)
        return []
    st = runtime.swoosh.setdefault(f"_{shape}:{event.start_frame if event else 0}", {})
    if shape == "behind_ghost":
        _ghost(face, u, frame_index, runtime, layer, alpha, seed, st)
        return []
    labels = getattr(runtime, "regions", None)
    region = HAIR if shape == "hair_energy" else GARMENT
    if "there" not in st:
        st["there"] = labels is not None and bool((labels == region).any())
    if not st["there"]:
        return _halo(face, u, frame_index, runtime, layer, color, alpha, seed)
    if labels is None:
        return []
    if shape == "hair_energy":
        return _hair(face, u, frame_index, runtime, layer, color, alpha, seed, st, labels)
    return _wave(u, labels, runtime, layer, color, alpha, seed, st)
