"""El cuervo: vuela alrededor de la cabeza y aterriza en el hombro (adorno `raven`).

La silueta es una sola: el cuerpo de vuelo y el de posado tienen los mismos puntos y se interpolan
con `fold` (0 en vuelo, 1 posado), así que el cuervo se transforma al aterrizar en vez de cambiar de
dibujo. Lo que lo hace leer como cuervo: pico grueso y largo, plumas erizadas en la garganta, cola
en cuña y alas con las plumas primarias separadas como dedos.

La vida del efecto: nace del polvo, da unas vueltas, aterriza sobre el contorno real del hombro, mira
alrededor y grazna, se asusta si la cabeza se mueve fuerte, y al final levanta vuelo y se deshace en
plumas. Aterriza siempre: no espera a que la persona se quede quieta.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _seg
from vfxglow.engine.dissolve import disintegrate, fine
from vfxglow.engine.duo_fx import body_mask
from vfxglow.engine.face_glow import steps
from vfxglow.engine.raster import fill_polygon, splat
from vfxglow.geom import catmull_rom

TAU = 2.0 * np.pi
INK = np.array([0.5, 0.42, 1.0], np.float32)
SHEEN = np.array([0.45, 0.85, 1.0], np.float32)
EYE = np.array([1.0, 0.12, 0.15], np.float32)
SIZE = 1.7  # unidades de cara (la mitad de esto, de la cola al pico)
FORM = 0.08
LAND_AT = 0.26
TAKE_OFF = 0.8
LEAVE = 0.88
SPRING = 0.05
DRAG = 0.82
STARTLE = 0.75
STARTLE_FRAMES = 24
ORBIT = (2.3, 2.5)

# El cuerpo, de la frente por arriba hasta la cola y de vuelta por abajo (sin el pico, que va aparte
# para que quede un ángulo marcado contra la cabeza). Mismos puntos en las dos poses. Mira hacia +x; y
# hacia abajo.
_PERCHED = np.array([
    (0.74, -0.60), (0.71, -0.72), (0.62, -0.83), (0.48, -0.88), (0.34, -0.80), (0.24, -0.62), (0.08, -0.40),
    (-0.18, -0.14), (-0.40, 0.11), (-0.64, 0.38), (-1.08, 0.84), (-0.94, 0.95), (-0.60, 0.66), (-0.36, 0.52),
    (-0.08, 0.50), (0.20, 0.33), (0.36, 0.06), (0.44, -0.16), (0.49, -0.27), (0.54, -0.35), (0.58, -0.42),
    (0.64, -0.47), (0.72, -0.50),
], dtype=np.float64)
_FLYING = np.array([
    (0.98, -0.06), (0.95, -0.17), (0.86, -0.27), (0.72, -0.32), (0.54, -0.27), (0.38, -0.20), (0.14, -0.15),
    (-0.14, -0.12), (-0.40, -0.09), (-0.66, -0.05), (-1.22, -0.10), (-1.20, 0.15), (-0.66, 0.10), (-0.40, 0.13),
    (-0.12, 0.20), (0.14, 0.22), (0.36, 0.18), (0.52, 0.13), (0.60, 0.09), (0.68, 0.06), (0.74, 0.04),
    (0.82, 0.03), (0.94, 0.02),
], dtype=np.float64)
# El pico: arriba (frente, lomo, gancho), comisura y abajo, en las dos poses.
_BEAK_PERCHED = np.array([(0.70, -0.74), (0.90, -0.72), (1.13, -0.54), (1.12, -0.47), (0.73, -0.60), (0.73, -0.50), (0.92, -0.49), (1.05, -0.50)], dtype=np.float64)
_BEAK_FLYING = np.array([(0.93, -0.20), (1.12, -0.17), (1.38, -0.03), (1.37, 0.04), (0.97, -0.06), (0.95, 0.03), (1.16, 0.03), (1.30, 0.02)], dtype=np.float64)
EYE_AT = ((0.60, -0.72), (0.84, -0.18))
ROOT_AT = ((0.2, -0.3), (0.3, -0.16))
THROAT = ((0.50, -0.42), (0.52, -0.30), (0.45, -0.34), (0.47, -0.21), (0.40, -0.26), (0.41, -0.12))
FINGERS = 6


def _rot(angle: float) -> np.ndarray:
    return np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])


def _chaikin(points: np.ndarray, rounds: int = 2) -> np.ndarray:
    """Redondea las esquinas sin perder la forma (las puntas de las plumas no quedan como agujas)."""
    for _ in range(rounds):
        q = points[:-1] * 0.75 + points[1:] * 0.25
        r = points[:-1] * 0.25 + points[1:] * 0.75
        points = np.vstack([points[:1], np.stack([q, r], axis=1).reshape(-1, 2), points[-1:]])
    return points


def _polar(angle: float, length: float) -> np.ndarray:
    return np.array([np.cos(angle), np.sin(angle)]) * length


def _wing(root: np.ndarray, flap: float, fold: float) -> tuple[np.ndarray, list[np.ndarray]]:
    """(contorno del ala, líneas de adentro). `flap`: 1 arriba, -1 abajo; plegada sobre el lomo con `fold`.

    Ala maciza: borde de ataque hasta la muñeca, dedos separados solo en la punta y borde de atrás
    festoneado hasta el cuerpo. Mano y brazo cambian de ángulo con el aleteo, como una articulación.
    """
    arm = np.radians(-105.0 - (1.0 - flap) * 52.0)
    hand = arm + np.radians(-22.0 - 22.0 * flap)
    arm_shut, hand_shut = np.radians(150.0), np.radians(144.0)
    arm_open, hand_open = arm, hand
    arm = arm_open + np.arctan2(np.sin(arm_shut - arm_open), np.cos(arm_shut - arm_open)) * fold
    hand = hand_open + np.arctan2(np.sin(hand_shut - hand_open), np.cos(hand_shut - hand_open)) * fold
    wrist = root + _polar(arm, 0.62 + (0.34 - 0.62) * fold)
    reach = 1.05 + (0.98 - 1.05) * fold
    fan = np.radians(11.0) * (1.0 - 0.9 * fold)
    tips = [wrist + _polar(hand - k * fan, reach * (1.0 - 0.012 * k**2 - 0.02 * k)) for k in range(FINGERS)]
    notches = [wrist + _polar(hand - (k + 0.5) * fan, reach * 0.68 * (1.0 - 0.03 * k)) for k in range(FINGERS - 1)]
    rear = root + np.array([-0.56, 0.22 + 0.1 * flap * (1.0 - fold)])
    fingers = []
    for k in range(FINGERS):
        fingers.append(tips[k])
        if k < FINGERS - 1:
            fingers.append(notches[k])
    # Borde de atrás: del último dedo al cuerpo, con un festón por pluma.
    last = tips[-1]
    along = rear - last
    side = np.array([along[1], -along[0]]) / max(float(np.linalg.norm(along)), 1e-6)
    scallop = []
    for k in range(1, 8):
        q = k / 8
        scallop.append(last + along * q - side * (0.08 if k % 2 == 0 else 0.0) * (1.0 - 0.7 * fold) + side * 0.2 * np.sin(np.pi * q) * (1.0 - fold))
    lead = catmull_rom(np.array([root + [0.14, 0.02], root + (wrist - root) * 0.55 + _polar(arm - np.pi / 2, 0.07), wrist]), 6)
    outline = np.vstack([lead, _chaikin(np.vstack([wrist, np.array(fingers), np.array(scallop), rear]), 2)])
    inside = [np.array([wrist + (tips[k] - wrist) * 0.2, wrist + (tips[k] - wrist) * 0.62]) for k in (0, 2, 4)]
    inside.append(catmull_rom(np.array([wrist + (last - wrist) * 0.1, (wrist + rear) * 0.5 + (last - rear) * 0.14, rear + (wrist - rear) * 0.16]), 7))
    return outline, inside


def _hackle(a, b) -> np.ndarray:
    a, b = np.asarray(a), np.asarray(b)
    mid = (a + b) / 2 + np.array([0.04, 0.0])
    q = np.linspace(0.0, 1.0, 6)[:, None]
    return (1 - q) ** 2 * a + 2 * (1 - q) * q * mid + q**2 * b


def raven_shape(at: np.ndarray, size: float, facing: float, flap: float, fold: float, caw: float = 0.0) -> dict:
    """Las piezas del cuervo centrado en `at`: `body`, `wing`, `far` (el ala de atrás), `beak`, `detail`, `legs` y `eye`."""
    shape = _FLYING + (_PERCHED - _FLYING) * fold
    beak = _BEAK_FLYING + (_BEAK_PERCHED - _BEAK_FLYING) * fold
    hinge = beak[4]

    def place(points) -> np.ndarray:
        return at + np.asarray(points, dtype=np.float64) * [facing * size, size]

    upper = beak[[0, 1, 2, 3, 4]]
    lower = beak[[4, 5, 6, 7]]
    if caw > 0.0:  # grazna: los dos picos giran en la comisura
        upper = hinge + (upper - hinge) @ _rot(-0.2 * caw).T
        lower = hinge + (lower - hinge) @ _rot(0.34 * caw).T
    root = np.array(ROOT_AT[1]) + (np.array(ROOT_AT[0]) - np.array(ROOT_AT[1])) * fold
    wing, inside = _wing(root, flap, fold)
    parts: dict = {"body": place(catmull_rom(np.vstack([shape, shape[:1]]), 5)), "wing": place(wing)}
    parts["beak"] = [place(_chaikin(upper, 1)), place(_chaikin(lower, 1))]
    detail = [place(c) for c in inside]
    if fold < 0.9:  # el ala de atrás asoma detrás del cuerpo
        parts["far"] = place(_wing(root + np.array([0.12, 0.02]), flap * 0.92, fold)[0])
    tail = shape[10:12].mean(axis=0)
    for k in (-0.5, 0.0, 0.5):  # las plumas de la cola, en cuña
        detail.append(place(np.array([shape[8] * 0.5 + shape[13] * 0.5, tail + (shape[10] - shape[11]) * k * 0.9])))
    if fold > 0.4:  # las plumas erizadas de la garganta: lo que más delata a un cuervo
        shift = shape[19] - _PERCHED[19]
        for a, b in np.array(THROAT).reshape(-1, 2, 2):
            detail.append(place(_hackle(a + shift, b + shift)))
    parts["detail"] = detail
    legs: list[np.ndarray] = []
    if fold > 0.7:  # las patas, con tres dedos
        grow = _seg(fold, 0.7, 1.0)
        for dx, base in ((0.0, (-0.04, 0.42)), (0.2, (0.13, 0.3))):
            foot, base = np.array([dx, 0.72]), np.array(base)
            legs.append(place(np.array([base, base + (foot - base) * grow])))
            if grow >= 1.0:
                legs += [place(np.array([foot, foot + [toe, 0.05]])) for toe in (-0.17, 0.07, 0.24)]
    parts["legs"] = legs
    eye = np.array(EYE_AT[1]) + (np.array(EYE_AT[0]) - np.array(EYE_AT[1])) * fold
    parts["eye"] = place(eye.reshape(1, 2))[0]
    parts["size"] = size
    return parts


def outlines(parts: dict) -> list[np.ndarray]:
    """Todas las líneas del cuervo, para soltarlas en polvo."""
    return [parts["body"], parts["wing"], *parts["beak"], *parts["detail"], *parts["legs"], *([parts["far"]] if "far" in parts else [])]


def draw(parts: dict, layer, alpha: float, kernels) -> None:
    if "far" in parts:
        fill_polygon(layer, parts["far"], INK * 0.18, alpha * 0.5, 1.0, feather=1.2)
        fine([parts["far"]], INK * 0.55, alpha * 0.7, layer, width=0.8)
    fill_polygon(layer, parts["body"], INK * 0.3, alpha * 0.6, 1.0, feather=1.5)
    fill_polygon(layer, parts["wing"], INK * 0.38, alpha * 0.6, 1.0, feather=1.2)
    fine([parts["body"]], INK, alpha, layer, width=1.3)
    fine([parts["wing"]], SHEEN, alpha, layer, width=1.2)
    fine(parts["detail"], SHEEN * 0.75, alpha * 0.75, layer, width=0.7)
    fine(parts["legs"], INK, alpha, layer, width=1.2)
    for piece in parts["beak"]:
        fill_polygon(layer, piece, INK * 0.45, alpha * 0.75, 1.0, feather=0.8)
    fine(parts["beak"], INK, alpha, layer, width=1.2)
    eye = parts["eye"]
    splat(layer, float(eye[0]), float(eye[1]), max(float(parts["size"]) * 0.05, 1.5), EYE, alpha, kernels)


def feather(center: np.ndarray, size: float, spin: float) -> list[np.ndarray]:
    """Una pluma de cuervo suelta, para el final."""
    d = np.array([np.cos(spin), np.sin(spin)])
    n = np.array([-d[1], d[0]])
    q = np.linspace(-1.0, 1.0, 11)
    edge = np.sqrt(np.maximum(1.0 - q**2, 0.0)) * (0.36 - 0.1 * q)
    bend = 0.18 * (q**2 - 1.0)
    spine = center + np.outer(q * size * 1.7, d) + np.outer(bend * size * 1.7, n)
    return [spine + np.outer(edge * size * 1.7, n), spine - np.outer(edge * size * 1.7, n), np.vstack([center - d * size * 2.3 + n * size * 0.3, spine])]


def _perch(body, runtime, layer, face, pos: np.ndarray) -> np.ndarray | None:
    """El punto del contorno sobre el hombro más cercano. Sin contorno, algo arriba de la articulación."""
    height, width = layer.shape[:2]
    head = face.place([(0.0, 0.0)])[0]
    best = None
    for name in ("left_shoulder", "right_shoulder"):
        joint = body.get(name)
        if joint is None or not 0 <= joint[1] < height:
            continue
        # Entre el cuello y la punta del hombro: la parte plana del hombro.
        margin = 0.6 * SIZE * face.unit  # que quepa entero en el cuadro, con la cola
        x = float(np.clip(head[0] + (joint[0] - head[0]) * 0.88, margin, width - margin))
        y = float(joint[1]) - 0.2 * face.unit
        for outline in getattr(runtime, "silhouettes", []) or []:
            near = outline[np.abs(outline[:, 0] - x) < 0.14 * face.unit]
            near = near[near[:, 1] > head[1] + 1.2 * face.unit]  # debajo de la cara: no el pelo
            if len(near):  # sin irse del hombro: el contorno puede ser un brazo o lo que tenga en la mano
                y = float(np.clip(near[:, 1].min(), joint[1] - 0.6 * face.unit, joint[1] + 0.2 * face.unit))
        point = np.array([x, y])
        if best is None or float(np.linalg.norm(point - pos)) < float(np.linalg.norm(best - pos)):
            best = point
    return best


def raven(face, body, scale: float, u: float, frame_index: int, runtime, layer, alpha: float, seed: int) -> list:
    st = runtime.swoosh.setdefault("_raven", {"pos": None, "vel": np.zeros(2), "angle": -0.6, "frame": -1, "fold": 0.0, "startle": 0, "perch": None, "facing": 1.0})
    center = face.place([(0.0, 0.2)])[0]
    energy = float(getattr(runtime, "energy", 0.0))
    size = SIZE * face.unit * 0.5
    if st["pos"] is None:
        st["pos"] = center + np.array([2.4, -1.6]) * face.unit
    if st["frame"] != frame_index:
        st["frame"] = frame_index
        n = steps(runtime)
        if energy >= STARTLE:
            st["startle"] = STARTLE_FRAMES
        st["startle"] = max(st["startle"] - n, 0)
        perch = _perch(body, runtime, layer, face, st["pos"])
        if perch is not None:
            st["perch"] = perch if st["perch"] is None else st["perch"] + (perch - st["perch"]) * 0.3
        landing = st["perch"] is not None and LAND_AT < u < TAKE_OFF and st["startle"] == 0
        st["angle"] += (0.055 + 0.2 * energy) * n
        if landing:
            target = st["perch"] - np.array([0.0, 0.72 * size])
        else:
            target = center + np.array([np.cos(st["angle"]) * ORBIT[0], np.sin(st["angle"]) * ORBIT[1] + 0.4]) * face.unit
        for _ in range(n):
            st["vel"] = (st["vel"] + (target - st["pos"]) * SPRING) * DRAG
            st["pos"] = st["pos"] + st["vel"]
        close = landing and float(np.linalg.norm(target - st["pos"])) < 0.3 * face.unit
        st["fold"] += ((1.0 if close else 0.0) - st["fold"]) * (1.0 - 0.8**n)
        if st["fold"] > 0.85 and landing:
            st["pos"] = target  # ya está parado: sigue al hombro sin flotar
            st["vel"] = np.zeros(2)
        if st["fold"] < 0.5 and abs(st["vel"][0]) > 0.02 * face.unit:
            st["facing"] = 1.0 if st["vel"][0] > 0 else -1.0
        elif st["fold"] >= 0.5:  # parado, mira a la persona y a veces hacia afuera
            inward = 1.0 if center[0] > st["pos"][0] else -1.0
            st["facing"] = inward if np.sin(frame_index * 0.035 + seed % 7) > -0.55 else -inward
    pos, fold = st["pos"], st["fold"]
    if fold < 0.3 and np.sin(st["angle"]) < 0:  # detrás de la cabeza
        mask = body_mask(body, layer.shape[:2], scale)
        x, y = int(np.clip(pos[0], 0, layer.shape[1] - 1)), int(np.clip(pos[1], 0, layer.shape[0] - 1))
        if mask is not None and mask[y, x]:
            return []
    # Bate más al frenar para aterrizar; casi planea cuando va rápido y derecho.
    beat = 0.5 + 0.5 * min(float(np.linalg.norm(st["vel"])) / (0.1 * face.unit), 1.0)
    flap = 0.2 + 0.8 * float(np.sin(frame_index * (0.42 + 0.3 * (1.0 - beat) + 0.3 * energy)))  # el ala apenas baja del cuerpo
    caw = _ease(max(np.sin(frame_index * 0.09 + 1.0) - 0.82, 0.0) / 0.18) if fold > 0.9 else 0.0
    parts = raven_shape(pos, size, st["facing"], flap, fold, caw)
    pairs = [(c, INK) for c in outlines(parts)]
    if u < FORM:
        return disintegrate(pairs, 1.0 - u / FORM, face.unit, layer, alpha, runtime.kernels, seed, figure=feather)
    if u >= LEAVE:
        return disintegrate(pairs, _seg(u, LEAVE, 1.0), face.unit, layer, alpha, runtime.kernels, seed, figure=feather)
    draw(parts, layer, alpha, runtime.kernels)
    return []
