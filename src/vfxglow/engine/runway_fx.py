"""Piezas del desfile que no necesitan los trazos de la prenda (docs/referencias/video_46.md); van solo
con la pose y la cara, así que sirven también en baile.

- hair_lights: lucecitas sobre el pelo, como una guirnalda (outfit naranja de video_46): unos doce
  destellos pequeños en cruz repartidos por la coronilla y los mechones de los lados, pegados a la
  cabeza (giran y se inclinan con ella) y titilando cada uno a su ritmo. Pieza de cabeza de un outfit.
- joint_rings: las articulaciones del outfit cian de video_46: un anillo en perspectiva alrededor de
  cada codo y cada rodilla (la mitad de adelante brillante, la de atrás tenue, con un brillo que da la
  vuelta), una línea que baja por la pierna desde la rodilla y un arco como paréntesis por fuera de
  cada hombro. Entran completos y siguen el cuerpo.
- step_glint: al caminar, cuando un pie se apoya (evento `step`), la suela se enciende y un anillo
  plano se abre en el piso con unas chispas a los lados; dura un tercio de segundo.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.face_glow import Face
from vfxglow.engine.raster import splat

TAU = 2.0 * np.pi
RUNWAY_FX = ("hair_lights", "joint_rings", "step_glint")
# Las que miran qué es cada píxel (analysis/regions.py): el pelo, y si la articulación está sobre la persona.
NEEDS_REGIONS = ("hair_lights", "joint_rings", "step_glint")
WHITE = np.array([1.0, 1.0, 1.0], np.float32)

# Lucecitas: cuántas, hasta dónde se buscan en el pelo alrededor de la cabeza y cuánto bajan (unidades
# de cara), su tamaño y el titileo.
HAIR_SPOTS = 12
HAIR_REACH = 2.8
HAIR_LOW = 1.4
HAIR_SPARK = 0.1
HAIR_TWINKLE = 0.35


def _hair_template(seed: int) -> np.ndarray:
    """Sin máscara de pelo: un arco sobre la coronilla y unas pocas a los lados (coordenadas de cara)."""
    rng = np.random.default_rng(seed)
    crown = np.linspace(-1.9, 1.9, 8) + rng.uniform(-0.12, 0.12, 8)
    reach = rng.uniform(0.82, 1.0, 8)
    top = np.stack([np.sin(crown) * 1.3 * reach, -0.35 - np.cos(crown) * 1.45 * reach], axis=1)
    side = np.where(np.arange(4) % 2 == 0, 1.0, -1.0) * rng.uniform(1.2, 1.4, 4)
    return np.vstack([top, np.stack([side, rng.uniform(0.2, 1.3, 4)], axis=1)])


def _spread(points: np.ndarray, count: int, seed: int) -> np.ndarray:
    """`count` puntos bien repartidos (el más lejano de los ya elegidos, uno a uno)."""
    rng = np.random.default_rng(seed)
    if len(points) > 3000:
        points = points[rng.choice(len(points), 3000, replace=False)]
    chosen = [points[rng.integers(len(points))]]
    gap = np.linalg.norm(points - chosen[0], axis=1)
    for _ in range(min(count, len(points)) - 1):
        chosen.append(points[int(np.argmax(gap))])
        gap = np.minimum(gap, np.linalg.norm(points - chosen[-1], axis=1))
    return np.array(chosen)


def _hair_spots(face: Face, labels: np.ndarray | None, seed: int) -> np.ndarray:
    """Dónde va cada lucecita, en coordenadas de cara (así sigue a la cabeza): repartidas por el pelo de
    verdad alrededor de la cabeza, sin bajar más que el mentón; sin pelo a la vista, la plantilla."""
    if labels is not None:
        from vfxglow.analysis.regions import HAIR

        ys, xs = np.nonzero(labels == HAIR)
        if len(xs) >= HAIR_SPOTS * 20:
            pts = np.stack([xs, ys], axis=1).astype(np.float64)
            basis = np.stack([face.ux, face.uy], axis=1)
            local = np.linalg.solve(basis, (pts - face.origin).T).T
            near = (np.linalg.norm(local - [0.0, -0.2], axis=1) < HAIR_REACH) & (local[:, 1] < HAIR_LOW)
            if near.sum() >= HAIR_SPOTS * 10:
                return _spread(local[near], HAIR_SPOTS, seed)
    return _hair_template(seed)


def hair_lights(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    start = event.start_frame if event is not None else 0
    seed = zlib.crc32(f"hair_lights:{start}:{body.prefix}".encode())
    st = runtime.swoosh.setdefault(f"_hair_lights:{start}:{body.prefix}", {})
    if "spots" not in st:  # se eligen una vez y quedan pegadas a la cabeza
        st["spots"] = _hair_spots(face, getattr(runtime, "regions", None), seed)
    spots = face.place(st["spots"])
    rng = np.random.default_rng(seed + 1)
    phases, speeds = rng.uniform(0, TAU, len(spots)), rng.uniform(0.15, 0.3, len(spots))
    tint = np.asarray(color, np.float32)
    core = tint * 0.5 + WHITE * 0.5  # núcleo casi blanco, como un foquito
    h, v = face.ux / face.unit, face.uy / face.unit
    out = []
    for at, phase, speed in zip(spots, phases, speeds, strict=True):
        glow = 1.0 - HAIR_TWINKLE + HAIR_TWINKLE * float(np.sin(frame_index * speed + phase))
        arm = HAIR_SPARK * face.unit * (0.8 + 0.2 * glow)
        out += [(np.array([at - h * arm, at + h * arm]), core * glow), (np.array([at - v * arm, at + v * arm]), core * glow)]
        splat(layer, float(at[0]), float(at[1]), arm * 1.1 + 1.0, tint, alpha * glow, runtime.kernels)
    return out


# Anillos: radio en anchos de hombros (codo, rodilla, arco del hombro), cuánto se aplastan por la
# perspectiva, brillo de la mitad de atrás, largo de la línea de la pierna (fracción de la canilla) y
# cuadros que tardan en abrirse.
ELBOW_R = 0.2
KNEE_R = 0.22
SHOULDER_R = 0.26
RING_FLAT = 0.38
RING_BACK = 0.35
SHIN_LINE = 0.5
RING_GROW = 4
# Distancia entre las dos rodillas (o codos), en radios de anillo, por debajo de la cual se cruzan.
KNEES_APART = 3.0
LIMBS = (("shoulder", "elbow", "wrist", ELBOW_R), ("hip", "knee", "ankle", KNEE_R))


def _ring(center: np.ndarray, along: np.ndarray, radius: float, count: int = 40) -> tuple[np.ndarray, np.ndarray]:
    """Un anillo alrededor del hueso (dirección `along`), visto de costado: (mitad de adelante, de atrás)."""
    across = np.array([-along[1], along[0]])
    t = np.linspace(0.0, TAU, count)
    pts = center + np.outer(np.cos(t) * radius, across) + np.outer(np.sin(t) * radius * RING_FLAT, along)
    half = count // 2
    return pts[: half + 1], pts[half:]


def _on_person(labels: np.ndarray | None, at: np.ndarray) -> bool:
    """La articulación cae sobre la persona: la pose inventa el codo que queda detrás del cuerpo y su
    anillo flotaría en el aire."""
    if labels is None:
        return True
    h, w = labels.shape[:2]
    x, y = int(round(at[0])), int(round(at[1]))
    if not (0 <= x < w and 0 <= y < h):
        return False
    return bool((labels[max(y - 4, 0) : y + 5, max(x - 4, 0) : x + 5] > 0).any())


def _limb_ring(body, side: str, limb: tuple, scale: float, grow: float, frame_index: int, runtime, layer, tint, alpha: float) -> list:
    root, mid, tip, size = limb
    a, j, b = body.get(f"{side}_{root}"), body.get(f"{side}_{mid}"), body.get(f"{side}_{tip}")
    if a is None or j is None or b is None or not _on_person(getattr(runtime, "regions", None), j):
        return []
    length = float(np.linalg.norm(b - a))
    if length < 1.0:
        return []
    along = (b - a) / length
    across = np.array([-along[1], along[0]])
    radius = size * scale * grow
    front, back = _ring(j, along, radius)
    out = [(front, tint), (back, tint * RING_BACK)]
    spin = (frame_index * 0.22 + (0.0 if side == "left" else np.pi)) % TAU  # el brillo que da la vuelta
    at = j + across * np.cos(spin) * radius + along * np.sin(spin) * radius * RING_FLAT
    splat(layer, float(at[0]), float(at[1]), 0.03 * scale + 1.0, tint * 0.4 + WHITE * 0.6, alpha * (1.0 if np.sin(spin) >= 0 else RING_BACK), runtime.kernels)
    other_side = "right" if side == "left" else "left"
    other_tip = body.get(f"{other_side}_{tip}")
    if mid == "knee" and (other_tip is None or b[1] >= other_tip[1]):
        # La línea baja por el costado de afuera de la pierna de adelante (el pie más abajo en el cuadro).
        other = body.get(f"{other_side}_knee")
        if other is not None and float((j - other) @ across) < 0:
            across = -across
        edge = j + across * radius * 0.85
        out.append((np.array([edge, edge + (b - j) * SHIN_LINE * grow]), tint * 0.85))
    return out


def _behind(body, side: str, mid: str, tip: str, size: float, scale: float) -> bool:
    """Con las dos rodillas (o los dos codos) casi juntas, los anillos se cruzan: queda solo el de
    adelante, el del pie (o la mano) más abajo en el cuadro, que es el más cerca de la cámara."""
    other = "right" if side == "left" else "left"
    j, k = body.get(f"{side}_{mid}"), body.get(f"{other}_{mid}")
    a, b = body.get(f"{side}_{tip}"), body.get(f"{other}_{tip}")
    if j is None or k is None or a is None or b is None:
        return False
    return float(np.linalg.norm(j - k)) < KNEES_APART * size * scale and float(a[1]) < float(b[1])


def _shoulder_arc(body, side: str, scale: float, grow: float, tint) -> list:
    """Un paréntesis por fuera del hombro."""
    shoulder, other = body.get(f"{side}_shoulder"), body.get(f"{'right' if side == 'left' else 'left'}_shoulder")
    if shoulder is None or other is None:
        return []
    away = (shoulder - other) / max(float(np.linalg.norm(shoulder - other)), 1.0)
    t = np.linspace(-1.0, 1.0, 24) * grow
    r = SHOULDER_R * scale
    return [(shoulder + np.outer(np.cos(t) * r * 0.55, away) + np.outer(np.sin(t) * r, np.array([0.0, 1.0])), tint)]


def joint_rings(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    grow = min((getattr(runtime, "active_frames", RING_GROW) + 1) / RING_GROW, 1.0)
    tint = np.asarray(color, np.float32)
    out: list = []
    for side in ("left", "right"):
        for limb in LIMBS:
            if _behind(body, side, limb[1], limb[2], limb[3], scale):
                continue
            out += _limb_ring(body, side, limb, scale, grow, frame_index, runtime, layer, tint, alpha)
        out += _shoulder_arc(body, side, scale, grow, tint)
    return out


# Paso: cuántos cuadros (a 30 fps) dura el destello, cuánto se abre el anillo del piso (anchos de
# hombros) y cuántas chispas salen a los lados.
STEP_FRAMES = 10
STEP_RING = (0.12, 0.55)
STEP_FLAT = 0.22
STEP_SPARKS = 4
# Hasta dónde bajo el talón se busca la suela (anchos de hombros).
SOLE_REACH = 0.5


def _step_side(body, event) -> str:
    if event is not None:
        for side in ("left", "right"):
            if f"{side}_" in event.target:
                return side
    left, right = body.get("left_ankle"), body.get("right_ankle")
    if left is not None and right is not None:
        return "left" if left[1] > right[1] else "right"  # el más bajo, el que está apoyado
    return "left" if left is not None else "right"


def _ground(labels: np.ndarray | None, heel: np.ndarray, toe: np.ndarray, scale: float) -> np.ndarray:
    """Dónde toca el piso: bajo el pie, la última fila de la persona (la pose pone el talón y la punta
    en el tobillo de una bota, no en la suela)."""
    mid = (heel + toe) / 2
    if labels is None:
        return mid + np.array([0.0, 0.02 * scale])
    h, w = labels.shape[:2]
    x0, x1 = int(np.clip(min(heel[0], toe[0]), 0, w - 1)), int(np.clip(max(heel[0], toe[0]), 0, w - 1)) + 1
    y0, y1 = int(np.clip(min(heel[1], toe[1]), 0, h - 1)), int(np.clip(max(heel[1], toe[1]) + SOLE_REACH * scale, 0, h))
    rows = np.nonzero((labels[y0:y1, x0:x1] > 0).any(axis=1))[0]
    if len(rows) == 0:
        return mid
    # La primera fila vacía tras el pie (lo que sigue más abajo puede ser el otro pie o la sombra).
    gaps = np.nonzero(np.diff(rows) > 2)[0]
    bottom = rows[gaps[0]] if len(gaps) else rows[-1]
    return np.array([mid[0], float(y0 + bottom)])


def step_glint(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    side = _step_side(body, event)
    heel, toe, ankle = body.get(f"{side}_heel"), body.get(f"{side}_foot_index"), body.get(f"{side}_ankle")
    if toe is None or heel is None:  # el pie medio tapado: una suela plana bajo el tobillo
        if ankle is None:
            return []
        heel = ankle + np.array([-0.08, 0.06]) * scale
        toe = ankle + np.array([0.1, 0.06]) * scale
    fps = getattr(runtime, "fps", 30.0) or 30.0
    # El efecto se enciende cuando el pie se apoya (`anchor: end` en el catálogo).
    age = (max(getattr(runtime, "active_frames", 1), 1) - 1) * 30.0 / fps
    if age > STEP_FRAMES:
        return []
    u = max(age, 0.0) / STEP_FRAMES
    fade = (1.0 - u) ** 1.5
    tint = np.asarray(color, np.float32)
    shine = tint * 0.4 + WHITE * 0.6
    sole = toe - heel
    out: list = [(np.array([heel - sole * 0.1, toe + sole * 0.15]), shine * fade)]
    splat(layer, float(toe[0]), float(toe[1]), 0.05 * scale + 1.0, shine, alpha * fade, runtime.kernels)
    ground = _ground(getattr(runtime, "regions", None), heel, toe, scale)
    rx = (STEP_RING[0] + (STEP_RING[1] - STEP_RING[0]) * (1.0 - (1.0 - u) ** 2)) * scale
    t = np.linspace(0.0, TAU, 48)
    ring = ground + np.stack([np.cos(t) * rx, np.sin(t) * rx * STEP_FLAT], axis=1)
    out += [(ring[:25], tint * fade), (ring[24:], tint * fade * 0.4)]  # adelante brillante, atrás tenue
    rng = np.random.default_rng(zlib.crc32(f"step:{event.end_frame if event is not None else 0}:{side}".encode()))
    for k in range(STEP_SPARKS):  # chispas que salen a ras del piso
        way = (1.0 if k % 2 else -1.0) * rng.uniform(0.6, 1.0)
        at = ground + np.array([way * rx * 1.1, -rng.uniform(0.0, 0.12) * scale * u])
        splat(layer, float(at[0]), float(at[1]), 0.02 * scale + 0.6, shine, alpha * fade * 0.8, runtime.kernels)
    return out


DRAW = {"hair_lights": hair_lights, "joint_rings": joint_rings, "step_glint": step_glint}


def runway_fx(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    return DRAW[shape](shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
