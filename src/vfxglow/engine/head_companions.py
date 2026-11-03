"""Criaturas de luz que acompañan a la cabeza sin tapar la cara (efectos periféricos, engine/face_zone.py).

Usan la base de la familia de ojos (engine/eye_family.py): fases, perillas de variación y señales de la
cara (engine/face_signals.py).

- eye_butterflies: mariposas pequeñas que salen de los párpados, se alejan hasta una órbita alrededor
  de la cabeza y aletean ahí. Cada parpadeo suelta una nueva; la órbita se corre hacia donde mira.
- medusa_snakes: serpientes de neón que nacen del nacimiento del pelo, se mecen en curvas y enroscan la
  punta hacia afuera (nunca sobre la cara); el cuerpo pasa de rosa a azul con escamas naranjas. Con la
  boca abierta se yerguen y sacan la lengua; al girar la cabeza se mecen más rápido.
- holo_snake: una serpiente holográfica que se desliza alrededor de la cabeza, por fuera del contorno
  de la cara. Gira más rápido y hacia el lado al que gira la cabeza; con la boca abierta, su cabeza se
  acerca a la cara (sin entrar) y, sin malla facial (la cara perdida), se repliega.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import fine, melt
from vfxglow.engine.eye_family import ENTRY_END, EXIT_AT, phase, pick_knobs
from vfxglow.engine.face_glow import Face, _seed, steps
from vfxglow.engine.face_signals import signals
from vfxglow.engine.head_beasts import _snake
from vfxglow.engine.raster import fill_polygon, splat
from vfxglow.geom import catmull_rom

TAU = 2.0 * np.pi
COMPANIONS = ("eye_butterflies", "holo_snake", "medusa_snakes")
HOLO = (0.3, 1.0, 0.85)
RUBY_TONGUE = np.array([1.0, 0.15, 0.3], np.float32)
# Centro de la cabeza (unidades de cara) alrededor del que giran.
HEAD_CENTER = (0.0, -0.15)
# Mariposas: cuántas salen al entrar (por densidad 1), tope, órbita (radio en unidades de cara),
# cuadros de 30 fps que tardan en llegar a ella, tamaño y cuánto se corre la órbita con la mirada.
# Vuelan en vaivén por la mitad de arriba de la órbita: por abajo pasarían sobre la boca y el mentón.
BUTTERFLIES = 3
BUTTERFLIES_MAX = 8
ORBIT = 1.9
FLY_OUT = 24
BUTTERFLY_SIZE = 0.38
GAZE_PULL = 0.4
# Vaivén: velocidad (por cuadro de 30 fps), hasta qué ángulo baja por los costados y la separación de
# fase entre una mariposa y la siguiente (el ángulo áureo: nunca coinciden).
SWING_SPEED = 0.05
SWING = 1.2
GOLDEN = 2.4
# Serpiente: radio de su camino, largo (radianes del camino), ancho, ondulación y cuánto se acerca
# con la boca abierta (el contorno de la cara queda a ~1,25 unidades del centro).
SNAKE_RADIUS = 1.75
SNAKE_ARC = 2.3
SNAKE_WIDTH = 0.085
SNAKE_WAVE = 0.07
SNAKE_CLOSEST = 1.3
JAW_FULL = 0.45


# Mariposas por especie, sacadas de referencias de ilustración que dio el usuario: cada una con su
# silueta (ala de adelante y de atrás en su caja: x a lo largo del cuerpo hacia la cabeza, y hacia un
# costado, en tamaños), si el borde es festoneado, sus adornos y sus dos colores.
BUTTERFLY_SPECIES = {
    "monarca": {
        "fore": ((0.08, 0.04), (0.3, 0.36), (0.52, 0.94), (0.34, 1.02), (0.02, 0.95), (-0.14, 0.52), (-0.04, 0.06)),
        "hind": ((-0.04, 0.05), (-0.12, 0.5), (-0.38, 0.78), (-0.62, 0.7), (-0.78, 0.48), (-0.56, 0.22), (-0.14, 0.04)),
        "scallop": False, "ornaments": ("inset", "dots", "veins"), "colors": ((1.0, 0.55, 0.15), (1.0, 0.95, 0.85)),
    },
    "golondrina": {
        "fore": ((0.08, 0.04), (0.36, 0.42), (0.62, 1.0), (0.4, 1.04), (0.02, 0.86), (-0.12, 0.42), (-0.04, 0.06)),
        "hind": ((-0.04, 0.05), (-0.1, 0.42), (-0.32, 0.62), (-0.52, 0.56), (-0.98, 0.38), (-0.6, 0.22), (-0.14, 0.04)),
        "scallop": False, "ornaments": ("inset", "drops"), "colors": ((0.55, 0.95, 1.0), (1.0, 0.85, 0.3)),
    },
    "paisley": {
        "fore": ((0.08, 0.04), (0.26, 0.4), (0.5, 0.82), (0.68, 0.92), (0.6, 1.04), (0.36, 0.98), (0.0, 0.84), (-0.1, 0.42), (-0.04, 0.06)),
        "hind": ((-0.04, 0.05), (-0.16, 0.48), (-0.4, 0.74), (-0.7, 0.84), (-0.82, 0.68), (-0.62, 0.62), (-0.48, 0.34), (-0.14, 0.04)),
        "scallop": False, "ornaments": ("inset", "drops", "dots"), "colors": ((0.3, 1.0, 0.75), (0.35, 0.45, 1.0)),
    },
    "festoneada": {
        "fore": ((0.08, 0.04), (0.28, 0.34), (0.46, 0.84), (0.3, 1.0), (0.0, 0.96), (-0.14, 0.54), (-0.04, 0.06)),
        "hind": ((-0.04, 0.05), (-0.14, 0.54), (-0.4, 0.86), (-0.66, 0.78), (-0.76, 0.52), (-0.54, 0.24), (-0.14, 0.04)),
        "scallop": True, "ornaments": ("inset", "drops", "dots"), "colors": ((1.0, 0.45, 0.75), (1.0, 0.8, 0.9)),
    },
    "polilla": {
        "fore": ((0.08, 0.04), (0.26, 0.4), (0.38, 0.86), (0.18, 1.02), (-0.08, 0.92), (-0.16, 0.5), (-0.04, 0.06)),
        "hind": ((-0.04, 0.05), (-0.2, 0.56), (-0.44, 0.88), (-0.7, 0.8), (-0.72, 0.5), (-0.5, 0.2), (-0.14, 0.04)),
        "scallop": False, "ornaments": ("inset", "veins", "dots"), "colors": ((0.75, 0.5, 1.0), (0.5, 1.0, 0.7)),
    },
    "ocelo": {
        "fore": ((0.08, 0.04), (0.34, 0.38), (0.58, 0.96), (0.36, 1.04), (0.02, 0.92), (-0.12, 0.5), (-0.04, 0.06)),
        "hind": ((-0.04, 0.05), (-0.12, 0.5), (-0.36, 0.8), (-0.64, 0.74), (-0.8, 0.5), (-0.56, 0.22), (-0.14, 0.04)),
        "scallop": True, "ornaments": ("inset", "ocelli"), "colors": ((1.0, 0.5, 0.2), (0.4, 0.75, 1.0)),
    },
}
SPECIES = tuple(BUTTERFLY_SPECIES)


def _wing_shape(points: np.ndarray, root: np.ndarray, scallop: bool) -> np.ndarray:
    """El contorno suave del ala; festoneado, ondula el borde hacia afuera de la raíz."""
    outline = catmull_rom(np.vstack([points, points[:1]]), 6)
    if scallop:
        q = np.linspace(0.0, 1.0, len(outline))
        away = outline - root
        reach = np.linalg.norm(away, axis=1, keepdims=True)
        bumps = 0.06 * np.abs(np.sin(q * np.pi * 14.0))[:, None] * np.clip(reach / max(float(reach.max()), 1e-6) - 0.35, 0.0, 1.0)
        outline = outline + away / np.maximum(reach, 1e-6) * bumps * float(reach.max())
    return outline


def _butterfly(at: np.ndarray, size: float, flap: float, heading: float, species: str = "monarca") -> tuple[list, list, list]:
    """(contornos de las alas, líneas finas de adorno, puntos). El aleteo, visto desde arriba, acorta
    las alas hacia el cuerpo (escorzo)."""
    kind = BUTTERFLY_SPECIES[species]
    spread = 0.3 + 0.7 * abs(flap)
    d = np.array([np.cos(heading), np.sin(heading)])
    n = np.array([-d[1], d[0]])
    place = lambda pts, sign: at + np.outer(np.asarray(pts)[:, 0] * size, d) + np.outer(np.asarray(pts)[:, 1] * size * spread * sign, n)  # noqa: E731
    wings, details, spots = [], [], []
    for sign in (-1.0, 1.0):
        for part in ("fore", "hind"):
            outline = _wing_shape(place(kind[part], sign), at, kind["scallop"])
            wings.append(outline)
            middle = outline.mean(axis=0)
            if "inset" in kind["ornaments"]:  # el contorno interior, paralelo al borde
                details.append(middle + (outline - middle) * 0.72)
            if "dots" in kind["ornaments"]:  # una fila de puntos junto al borde
                ring = middle + (outline - middle) * 0.86
                spots += list(ring[:: max(len(ring) // 9, 1)])
            if "veins" in kind["ornaments"]:
                for k in (len(outline) // 4, len(outline) // 2, 3 * len(outline) // 4):
                    details.append(np.array([at + (outline[k] - at) * 0.15, at + (outline[k] - at) * 0.8]))
            if "drops" in kind["ornaments"]:  # gotas que apuntan hacia la raíz
                for frac in (0.45, 0.68):
                    tip = at + (middle - at) * frac * 0.9
                    bulb = middle + (outline[len(outline) // 3] - middle) * 0.35 * frac
                    axis = bulb - tip
                    side_ = np.array([-axis[1], axis[0]]) * 0.35
                    details.append(catmull_rom(np.array([tip, bulb + side_ - axis * 0.1, bulb + axis * 0.25, bulb - side_ - axis * 0.1, tip]), 5))
            if "ocelli" in kind["ornaments"] and part == "hind":  # el ojo del ala de atrás
                t = np.linspace(0.0, 2.0 * np.pi, 18)
                r = size * 0.13 * spread + 0.5
                circle = np.stack([np.cos(t), np.sin(t)], axis=1)
                details += [middle + circle * r, middle + circle * r * 0.5]
    details.append(np.array([at - d * size * 0.5, at + d * size * 0.34]))  # el cuerpo
    for sign in (-1.0, 1.0):  # las antenas, curvadas hacia afuera
        details.append(catmull_rom(np.array([at + d * size * 0.34, at + d * size * 0.55 + n * sign * size * 0.14, at + d * size * 0.66 + n * sign * size * 0.3]), 5))
    return wings, details, spots


def _butterflies(face: Face, ctx: dict) -> list:
    sig, st, frame_index, knobs = ctx["sig"], ctx["st"], ctx["frame_index"], ctx["knobs"]
    born = st.setdefault("born", [])
    if not born:  # las primeras salen escalonadas, una de cada ojo
        born += [(frame_index + 6 * k, "right" if k % 2 == 0 else "left") for k in range(int(round(BUTTERFLIES * float(knobs["density"]))))]
    if sig.blink_start and ctx["stage"] == "active" and len(born) < BUTTERFLIES_MAX:
        born.append((frame_index, "right" if len(born) % 2 == 0 else "left"))
    center = face.place([HEAD_CENTER])[0] + (face.ux * sig.gaze[0] - face.uy * sig.gaze[1]) * GAZE_PULL
    speed = SWING_SPEED * float(knobs["speed"]) * (1.0 if int(knobs["motion"]) != 1 else -1.0)
    height, width = getattr(ctx["runtime"], "frame_shape", (None, None))
    out = []
    for k, (birth, side) in enumerate(born):
        age = frame_index - birth
        if age < 0 or not face.visible(side):
            continue
        lid = face.feature(f"{side}_eye")
        start = lid[: len(lid) // 2 + 1].mean(axis=0) if lid is not None and len(lid) > 4 else face.at(f"{side}_iris", (0.5 if side == "left" else -0.5, 0.0))
        phase_k = frame_index * speed + k * GOLDEN  # cada una con su fase: si no, vuelan juntas
        a = -np.pi / 2 + np.sin(phase_k) * SWING  # de un costado de la cabeza al otro, por arriba
        orbit = center + (face.ux * np.cos(a) + face.uy * np.sin(a) * 0.8) * ORBIT
        if width:  # dentro del cuadro
            margin = BUTTERFLY_SIZE * face.unit
            orbit = np.clip(orbit, [margin, margin], [width - margin, height - margin])
        out_t = _ease(min(age / FLY_OUT, 1.0))
        at = start + (orbit - start) * out_t - face.uy * np.sin(np.pi * out_t) * 0.4  # sale hacia arriba y se va
        heading = np.arctan2(*(orbit - start)[::-1]) if out_t < 1.0 else float(np.arctan2(*(face.ux * -np.sin(a) + face.uy * np.cos(a))[::-1])) + (np.pi if np.cos(phase_k) < 0 else 0.0)
        size = BUTTERFLY_SIZE * face.unit * (0.4 + 0.6 * out_t)
        species = SPECIES[int(np.random.default_rng([ctx["seed"], k]).integers(0, len(SPECIES)))]
        tint, accent = (np.asarray(c, np.float32) for c in BUTTERFLY_SPECIES[species]["colors"])
        # Órbita en 3D: en un sentido del vaivén van por delante; en el otro, por detrás de la cabeza (si
        # caen sobre la persona, no se ven). Al salir del párpado siempre van por delante.
        behind = out_t >= 1.0 and np.cos(phase_k) < 0
        if behind and _on_person(ctx, at):
            continue
        wings, details, spots = _butterfly(at, size, np.sin(frame_index * 0.9 + k * 1.7), heading, species)
        for wing in wings:  # alas apenas rellenas, contorno nítido, venas y cuerpo más tenues
            fill_polygon(ctx["layer"], wing, tint, ctx["alpha"] * 0.18, 1.0, feather=1.0)
        for spot in spots:
            splat(ctx["layer"], float(spot[0]), float(spot[1]), size * 0.045 + 0.5, accent, ctx["alpha"] * 0.85, ctx["runtime"].kernels)
        out += [(curve, tint) for curve in wings] + [(curve, accent * 0.75) for curve in details]
    return out


def _holo_snake(face: Face, ctx: dict) -> list:
    sig, st, frame_index, knobs = ctx["sig"], ctx["st"], ctx["frame_index"], ctx["knobs"]
    direction = 1.0 if int(knobs["motion"]) != 1 else -1.0
    turn = float(np.clip(sig.yaw_rate / 120.0, -1.0, 1.0))
    k = steps(ctx["runtime"])
    if st.get("frame") != frame_index:
        st["frame"] = frame_index
        st["angle"] = st.get("angle", -np.pi / 2) + (0.03 * float(knobs["speed"]) * direction + 0.05 * turn) * k
        # Sin malla facial, la cara se perdió: se repliega (el cuerpo se acorta).
        st["reach"] = st.get("reach", 0.0) + ((1.0 if face.mesh else 0.25) - st.get("reach", 0.0)) * (1.0 - 0.85**k)
    grow = _ease(_seg(ctx["u"], 0.0, ENTRY_END * 2.0)) * st["reach"]
    if grow <= 0.02:
        return []
    near = float(np.clip(sig.jaw / JAW_FULL, 0.0, 1.0))
    center = face.place([HEAD_CENTER])[0]
    q = np.linspace(0.0, 1.0, 40)
    a = st["angle"] - direction * SNAKE_ARC * grow * (1.0 - q)  # q = 1 es la cabeza
    wave = SNAKE_WAVE * np.sin(q * 11.0 - frame_index * 0.35 * float(knobs["speed"])) * (1.0 - 0.6 * q)
    approach = near * q**3 * (SNAKE_RADIUS - SNAKE_CLOSEST)
    radius = (SNAKE_RADIUS + wave - approach) * face.unit
    spine = center + np.outer(np.cos(a) * radius, face.ux / face.unit) + np.outer(np.sin(a) * radius * 0.9, face.uy / face.unit)
    flicker = 0.85 + 0.15 * np.sin(frame_index * 1.3)  # el parpadeo del holograma
    tint = ctx["main"] * flicker
    # La mitad de arriba de su vuelta va por detrás: si cae sobre la persona (un peinado alto), no se ve.
    # Se dibuja aparte y se borra eso. El aro no se aplasta sobre la cabeza: con la silueta de la pose,
    # que no siempre cubre la frente, cruzaba la cara.
    mask = _person(ctx)
    drawn = np.zeros_like(ctx["layer"])
    pairs = _snake(spine, SNAKE_WIDTH * face.unit, tint, frame_index, ctx["seed"], drawn, ctx["alpha"] * flicker, ctx["runtime"].kernels)
    if mask is not None:
        drawn[(mask > 0) & (np.arange(mask.shape[0])[:, None] < center[1])] = 0.0
        pairs = [piece for curve, tint_ in pairs for piece in _front(curve, tint_, center, mask)]
    ctx["layer"] += drawn
    for k in range(0, len(spine) - 2, 4):  # líneas de barrido del holograma, cruzando el cuerpo
        d = spine[k + 1] - spine[k]
        n = np.array([-d[1], d[0]]) / max(float(np.linalg.norm(d)), 1e-6)
        fine([np.array([spine[k] - n * SNAKE_WIDTH * face.unit * 1.4, spine[k] + n * SNAKE_WIDTH * face.unit * 1.4])], tint, ctx["alpha"] * 0.35, ctx["layer"], width=1.0)
    return pairs


# Medusa: raíces (unidades de cara, en el nacimiento del pelo), largo, ancho, cuánto se mecen y cuánto
# enroscan la punta; colores de la cabeza a la cola y de las escamas.
MEDUSA_ROOTS = ((-1.0, -0.3), (-0.85, -0.9), (-0.35, -1.25), (0.35, -1.25), (0.85, -0.9), (1.0, -0.3))
MEDUSA_LENGTH = 1.7
MEDUSA_WIDTH = 0.16
MEDUSA_SWAY = 2.6
MEDUSA_CURL = 7.0
MEDUSA_HEAD = np.array([1.0, 0.35, 0.8], np.float32)
MEDUSA_TAIL = np.array([0.3, 0.5, 1.0], np.float32)
MEDUSA_SCALES = np.array([1.0, 0.6, 0.2], np.float32)
MEDUSA_SHADOW = np.array([0.12, 0.15, 0.75], np.float32)


def _medusa_spine(face: Face, root: np.ndarray, out: np.ndarray, length: float, phase_: float, curl: float) -> np.ndarray:
    """El cuerpo, de la raíz a la cabeza: se mece en curvas y la punta se enrosca hacia afuera."""
    steps_ = 36
    heading = float(np.arctan2(out[1], out[0]))
    side = 1.0 if out[0] >= 0 else -1.0  # se enrosca hacia afuera de la cara
    pts = [root]
    ds = length / steps_
    for i in range(steps_):
        q = i / steps_
        bend = MEDUSA_SWAY * np.sin(TAU * q * 0.75 - phase_) * (0.6 + 0.4 * q)
        if q > 0.5:  # la punta se enrosca en espiral: la curva se cierra cada vez más
            bend += side * curl * ((q - 0.5) / 0.5) * (1.0 + 2.5 * ((q - 0.5) / 0.5) ** 2)
        heading += bend * ds
        pts.append(pts[-1] + np.array([np.cos(heading), np.sin(heading)]) * ds)
    local = np.array(pts)
    return face.place(local)


# Volumen de las serpientes (luz aditiva: no hay sombra negra, el volumen sale del brillo): la luz
# llega desde arriba a la izquierda del cuadro; franjas a lo ancho del cuerpo, tramos a lo largo, y
# las escamas por fila (ángulo sobre el cilindro, en grados).
LIGHT_DIR = np.array([-0.6, -0.8])
BODY_BANDS = 5
BODY_CHUNK = 3
SCALE_ROWS = (-55.0, -20.0, 20.0, 55.0)


def _medusa_body(spine: np.ndarray, n: np.ndarray, half: np.ndarray, q: np.ndarray, emerge: np.ndarray, phase_: float, layer, alpha: float, kernels) -> list:
    """El cuerpo como un cilindro iluminado: franjas más claras del lado de la luz, una línea de brillo
    húmedo por el lomo con destellos que corren, el borde de la luz claro y el de la sombra tenue, y
    escamas curvas que se achican y se apagan hacia los costados."""
    facing = np.sign(n @ LIGHT_DIR)[:, None]  # de qué lado del cuerpo llega la luz
    toward = n * np.where(facing == 0, 1.0, facing)
    tints = MEDUSA_TAIL[None, :] + (MEDUSA_HEAD - MEDUSA_TAIL)[None, :] * q[:, None]
    edges = np.linspace(-1.0, 1.0, BODY_BANDS + 1)  # -1 a la sombra, 1 a la luz
    for b0, b1 in zip(edges[:-1], edges[1:]):
        mid = (b0 + b1) / 2
        light = 0.08 + 0.92 * max(np.cos((mid - 0.35) * np.pi / 2.2), 0.0) ** 2.5
        for i in range(0, len(spine) - 1, BODY_CHUNK):
            j = min(i + BODY_CHUNK, len(spine) - 1)
            a_side = spine[i : j + 1] + toward[i : j + 1] * (half[i : j + 1, None] * b0)
            b_side = spine[i : j + 1] + toward[i : j + 1] * (half[i : j + 1, None] * b1)
            strip = np.vstack([a_side, b_side[::-1]])
            # Dos tonos: la sombra se va a un azul profundo y la luz al color del cuerpo, casi blanco al
            # centro del brillo (así se lee redondo aunque la luz sea aditiva).
            tint = MEDUSA_SHADOW + (tints[i] - MEDUSA_SHADOW) * light + light**4 * 0.45
            fill_polygon(layer, strip, tint * (0.35 + 0.65 * light), alpha * 0.7 * emerge[i], 1.0, feather=0.7)
    # La línea de brillo: del lado de la luz, con destellos que corren por el cuerpo.
    gloss = spine + toward * half[:, None] * 0.42
    glints = []
    for i in range(1, len(spine) - 1):
        shine = 0.5 + 0.5 * np.sin(q[i] * 14.0 - phase_ * 3.0)
        if shine > 0.35:
            glints.append((np.array([gloss[i - 1], gloss[i + 1]]), (tints[i] * 0.3 + 0.7) * shine * emerge[i]))
    for curve, tint in glints:
        fine([curve], tint, alpha, layer, width=1.0)
    # Escamas: arcos que miran hacia la cola, a lo largo y en filas sobre el cilindro.
    scales = []
    for i in range(2, len(spine) - 2, 2):
        back = spine[i - 1] - spine[i + 1]
        back = back / max(float(np.linalg.norm(back)), 1e-6)
        for r, angle in enumerate(SCALE_ROWS):
            if (i // 2 + r) % 2:
                continue
            theta = np.radians(angle)
            center = spine[i] + toward[i] * half[i] * np.sin(theta) * 0.9
            size = half[i] * 0.42 * np.cos(theta)
            light = 0.35 + 0.65 * max(np.cos(theta - 0.6), 0.0)
            side_ = toward[i] * size
            arc = catmull_rom(np.array([center - side_, center + back * size * 0.9, center + side_]), 4)
            scales.append((arc, MEDUSA_SCALES * light * emerge[i]))
    for curve, tint in scales:
        fine([curve], tint, alpha * 0.9, layer, width=1.0)
    # Bordes: claro del lado de la luz, tenue del de la sombra (se devuelven al motor).
    lit, dark = spine + toward * half[:, None], spine - toward * half[:, None]
    out = []
    for i in range(3, len(spine) - 1, BODY_CHUNK):
        j = min(i + BODY_CHUNK + 1, len(spine))
        out += [(lit[i:j], tints[i] * 0.45 + 0.55), (dark[i:j], tints[i] * 0.45)]
    return out


def _medusa(face: Face, ctx: dict) -> list:
    sig, frame_index, knobs, layer, alpha, kernels = ctx["sig"], ctx["frame_index"], ctx["knobs"], ctx["layer"], ctx["alpha"], ctx["runtime"].kernels
    grow = _ease(_seg(ctx["u"], 0.0, ENTRY_END * 2.5))
    rear = float(np.clip(sig.jaw / JAW_FULL, 0.0, 1.0))
    speed = (0.08 + 0.1 * min(abs(sig.yaw_rate) / 90.0, 1.0)) * float(knobs["speed"])
    center = np.array(HEAD_CENTER)
    out_lines: list = []
    for k, root in enumerate(np.asarray(MEDUSA_ROOTS)):
        direction = (root - center) / np.linalg.norm(root - center)
        direction = direction * np.array([1.4, 1.0]) + np.array([0.0, -0.15])  # hacia los costados, rodeando la cabeza
        length = MEDUSA_LENGTH * grow * (1.0 + 0.25 * rear) * (0.85 + 0.15 * ((k * 5) % 3))
        spine = _medusa_spine(face, root, direction, length, frame_index * speed + k * GOLDEN, MEDUSA_CURL * (1.0 - 0.5 * rear))
        if len(spine) < 4:
            continue
        n = np.gradient(spine, axis=0)
        n = np.stack([-n[:, 1], n[:, 0]], axis=1) / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)
        q = np.linspace(0.0, 1.0, len(spine))
        half = (MEDUSA_WIDTH * face.unit * (1.0 - 0.45 * q) * (0.6 + 0.4 * np.minimum(q * 6.0, 1.0)))[:, None]
        emerge = np.clip(q / 0.15, 0.0, 1.0)  # la raíz sale del pelo: aparece de a poco
        out_lines += _medusa_body(spine, n, half[:, 0], q, emerge, frame_index * speed + k, layer, alpha, kernels)
        tip, d = spine[-1], spine[-1] - spine[-3]
        d = d / max(float(np.linalg.norm(d)), 1e-6)
        s_ = np.array([-d[1], d[0]])
        w = MEDUSA_WIDTH * face.unit * 0.9
        head = catmull_rom(np.array([tip - s_ * w * 0.8, tip + d * w * 1.1 - s_ * w * 0.7, tip + d * w * 2.2, tip + d * w * 1.1 + s_ * w * 0.7, tip + s_ * w * 0.8]), 5)
        fill_polygon(layer, head, MEDUSA_HEAD * 0.55, alpha * 0.5, 1.0, feather=1.0)
        crown = tip + d * w * 1.0 + LIGHT_DIR * w * 0.35  # el brillo de la cabeza, del lado de la luz
        fill_polygon(layer, crown + (head - head.mean(axis=0)) * 0.45, MEDUSA_HEAD * 0.6 + 0.4, alpha * 0.45, 1.0, feather=1.5)
        out_lines.append((head, MEDUSA_HEAD))
        for sign in (-1.0, 1.0):
            eye = tip + d * w * 1.2 + s_ * sign * w * 0.4
            splat(layer, float(eye[0]), float(eye[1]), w * 0.14 + 0.4, MEDUSA_SCALES, alpha, kernels)
        if rear > 0.3 or (frame_index // 7 + k) % 4 == 0:  # la lengua
            mouth = tip + d * w * 2.2
            fork = mouth + d * w * 0.9
            out_lines += [(np.array([mouth, fork]), RUBY_TONGUE)] + [(np.array([fork, fork + (d + s_ * sign * 0.6) * w * 0.45]), RUBY_TONGUE) for sign in (-1.0, 1.0)]
    return out_lines


def _person(ctx: dict) -> np.ndarray | None:
    """La silueta de la persona en el cuadro (para lo que pasa por detrás de la cabeza)."""
    if "mask" not in ctx:
        from vfxglow.engine.duo_fx import body_mask

        ctx["mask"] = body_mask(ctx["body"], ctx["layer"].shape[:2], ctx["scale"])
    return ctx["mask"]


def _on_person(ctx: dict, at: np.ndarray) -> bool:
    mask = _person(ctx)
    if mask is None:
        return False
    x, y = int(np.clip(at[0], 0, mask.shape[1] - 1)), int(np.clip(at[1], 0, mask.shape[0] - 1))
    return bool(mask[y, x])


def _front(curve: np.ndarray, tint, center: np.ndarray, mask: np.ndarray) -> list:
    """Los tramos de una línea que se ven: por delante (debajo del centro de la cabeza) o, por detrás,
    fuera de la persona."""
    from vfxglow.engine.duo_fx import visible

    curve = np.asarray(curve, dtype=np.float64)
    return [(curve[a:b], tint) for a, b in visible(curve, curve[:, 1] - center[1], mask)]


DRAW = {"eye_butterflies": _butterflies, "holo_snake": _holo_snake, "medusa_snakes": _medusa}


def head_companion(shape: str, body, frame, scale, frame_index: int, runtime, layer, color, alpha: float, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    stage, t = phase(u)
    start = event.start_frame if event is not None else 0
    knobs = pick_knobs(shape, body.prefix, start, runtime.effect.style.variants)
    main = np.asarray(color if knobs["palette"] == "chapter" else HOLO, np.float32)
    power = alpha * float(knobs["intensity"])
    ctx = {
        "sig": signals(runtime, frame_index, body.prefix), "st": runtime.swoosh.setdefault(f"_companion:{shape}:{start}:{body.prefix}", {}),
        "u": u, "stage": stage, "frame_index": frame_index, "runtime": runtime, "layer": layer, "knobs": knobs, "seed": _seed(shape, body, event),
        "main": main, "alpha": power * (1.0 - _ease(t) if stage == "exit" else 1.0), "body": body, "scale": scale,
    }
    items = melt(DRAW[shape](face, ctx), u, face, layer, main, power, runtime.kernels, ctx["seed"], start=EXIT_AT)
    # Línea fina con poco halo (con neón grueso eran manchas y un tubo pesado); las serpientes de Medusa
    # son grandes y llevan un borde más marcado.
    width = max(1.5, 0.012 * face.unit) if shape == "medusa_snakes" else max(1.0, 0.006 * face.unit)
    ratio = (ctx["alpha"] if stage != "exit" else power) / max(alpha, 1e-6)
    return [(curve, np.asarray(tint, np.float32) * ratio, width) for curve, tint in items]
