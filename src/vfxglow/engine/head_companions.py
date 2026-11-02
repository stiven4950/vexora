"""Criaturas de luz que acompañan a la cabeza sin tapar la cara (efectos periféricos, engine/face_zone.py).

Usan la base de la familia de ojos (engine/eye_family.py): fases, perillas de variación y señales de la
cara (engine/face_signals.py).

- eye_butterflies: mariposas pequeñas que salen de los párpados, se alejan hasta una órbita alrededor
  de la cabeza y aletean ahí. Cada parpadeo suelta una nueva; la órbita se corre hacia donde mira.
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
COMPANIONS = ("eye_butterflies", "holo_snake")
BUTTERFLY_COLORS = ((1.0, 0.45, 0.85), (0.5, 0.85, 1.0), (1.0, 0.85, 0.35))
HOLO = (0.3, 1.0, 0.85)
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


# Mariposa en su caja (x a lo largo del cuerpo, hacia la cabeza; y hacia un costado), en tamaños.
FOREWING = ((0.08, 0.04), (0.32, 0.38), (0.5, 0.92), (0.34, 1.02), (0.02, 0.95), (-0.14, 0.52), (-0.04, 0.06))
HINDWING = ((-0.04, 0.05), (-0.12, 0.5), (-0.38, 0.78), (-0.62, 0.7), (-0.8, 0.5), (-0.56, 0.24), (-0.14, 0.04))
VEINS = (((0.02, 0.06), (0.36, 0.78)), ((0.0, 0.06), (0.06, 0.8)), ((-0.08, 0.06), (-0.46, 0.56)))
SPOTS = ((0.26, 0.78), (-0.48, 0.5))


def _butterfly(at: np.ndarray, size: float, flap: float, heading: float) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
    """(contornos de las alas, líneas finas: venas, cuerpo y antenas, manchas). El aleteo, visto desde
    arriba, acorta las alas hacia el cuerpo (escorzo)."""
    spread = 0.3 + 0.7 * abs(flap)
    d = np.array([np.cos(heading), np.sin(heading)])
    n = np.array([-d[1], d[0]])
    place = lambda pts, sign: at + np.outer(np.asarray(pts)[:, 0] * size, d) + np.outer(np.asarray(pts)[:, 1] * size * spread * sign, n)  # noqa: E731
    wings, details, spots = [], [], []
    for sign in (-1.0, 1.0):
        for shape in (FOREWING, HINDWING):
            outline = catmull_rom(place(shape, sign), 6)
            wings.append(np.vstack([outline, outline[:1]]))
        details += [place(vein, sign) for vein in VEINS]
        spots += list(place(SPOTS, sign))
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
        tint = np.asarray(BUTTERFLY_COLORS[k % len(BUTTERFLY_COLORS)], np.float32)
        wings, details, spots = _butterfly(at, size, np.sin(frame_index * 0.9 + k * 1.7), heading)
        for wing in wings:  # alas apenas rellenas, contorno nítido, venas y cuerpo más tenues
            fill_polygon(ctx["layer"], wing, tint, ctx["alpha"] * 0.18, 1.0, feather=1.0)
        for spot in spots:
            splat(ctx["layer"], float(spot[0]), float(spot[1]), size * 0.07 + 0.5, tint, ctx["alpha"] * 0.8, ctx["runtime"].kernels)
        out += [(curve, tint) for curve in wings] + [(curve, tint * 0.6) for curve in details]
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
    pairs = _snake(spine, SNAKE_WIDTH * face.unit, tint, frame_index, ctx["seed"], ctx["layer"], ctx["alpha"] * flicker, ctx["runtime"].kernels)
    for k in range(0, len(spine) - 2, 4):  # líneas de barrido del holograma, cruzando el cuerpo
        d = spine[k + 1] - spine[k]
        n = np.array([-d[1], d[0]]) / max(float(np.linalg.norm(d)), 1e-6)
        fine([np.array([spine[k] - n * SNAKE_WIDTH * face.unit * 1.4, spine[k] + n * SNAKE_WIDTH * face.unit * 1.4])], tint, ctx["alpha"] * 0.35, ctx["layer"], width=1.0)
    return pairs


DRAW = {"eye_butterflies": _butterflies, "holo_snake": _holo_snake}


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
        "main": main, "alpha": power * (1.0 - _ease(t) if stage == "exit" else 1.0),
    }
    items = melt(DRAW[shape](face, ctx), u, face, layer, main, power, runtime.kernels, ctx["seed"], start=EXIT_AT)
    for curve, tint in items:  # línea fina con poco halo: con neón grueso eran manchas y un tubo pesado
        fine([curve], tint, ctx["alpha"] if stage != "exit" else power, layer, width=max(1.0, 0.006 * face.unit))
    return []
