"""Efectos que responden por grados a la persona, no solo se encienden (adornos `type: adornment`).

Leen en cada fotograma cuánto abre la boca, qué tan fuerte suena, cuánto se mueve la cabeza y hacia
dónde mira, y cambian con eso: si la persona hace más, el efecto hace más.

- dragon_breath: las mejillas o la boca cargan brasas y sale una llamarada; su largo sigue a la
  apertura de la boca o al soplido y apunta hacia donde gira la cabeza.
- sonic_pulse: la voz sale de la boca en ondas; el tamaño de cada onda sigue al volumen, y a los lados
  de la cabeza hay barras de ecualizador. Sin audio usa la apertura de la boca.
- puppet_strings: hilos que bajan de una cruceta y sostienen la cabeza, los hombros y las muñecas.
  Vibran con la velocidad de cada punto y la cruceta sigue a la cabeza con retraso. Al final se
  rompen uno por uno.
- raven: un cuervo se forma de polvo, vuela alrededor de la cabeza (más rápido si la cabeza se mueve),
  se posa en el hombro si la persona se queda quieta y levanta vuelo si se mueve. Termina en plumas.
- eye_curse: sellos diminutos alrededor de los ojos que se corren con la mirada, se apagan al cerrar
  los ojos y sueltan una onda al abrirlos.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.expressions import gaze_vector
from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import disintegrate, fine, melt
from vfxglow.engine.duo_fx import body_mask
from vfxglow.engine.face_glow import _RUNES, WHITE, Face, _seed, steps
from vfxglow.engine.firebend import cel, living_ribbon, teardrop
from vfxglow.engine.raster import splat

TAU = 2.0 * np.pi
LIVING = ("dragon_breath", "sonic_pulse", "puppet_strings", "raven", "eye_curse")
ON_THE_FACE = ("dragon_breath", "sonic_pulse", "eye_curse")
FIRE = np.array([1.0, 0.45, 0.1], np.float32)
FLAME_HOT = np.array([1.0, 0.8, 0.2], np.float32)
FLAME_COOL = np.array([1.0, 0.12, 0.03], np.float32)
PUFFS = 64
RAVEN = np.array([0.55, 0.4, 1.0], np.float32)
EYE_RED = np.array([1.0, 0.1, 0.15], np.float32)
THREAD = np.array([0.85, 0.95, 1.0], np.float32)
# Llamarada: boca abierta que ya cuenta como máxima, lo mínimo que sale y su largo (unidades de cara).
JAW_FULL = 0.45
FLAME_MIN = 0.3
FLAME_LENGTH = 3.4
FLAME_TURN = 0.7
# Ondas de voz: cuadros entre una y otra, y cuánto debe subir el volumen para soltar una nueva.
PULSE_GAP = 4
PULSE_RISE = 0.05
PULSE_LOUD = 0.6
PULSE_LIFE = (14, 32)
BARS = 6
# Cuervo: cuerda hacia su objetivo, roce y cuadros quieto antes de posarse.
RAVEN_SPRING = 0.035
RAVEN_DRAG = 0.86
RAVEN_CALM = 0.2
RAVEN_PERCH_AFTER = 18
RAVEN_FORM = 0.1
RAVEN_LEAVE = 0.86
RAVEN_SIZE = 0.62
# Hilos: empieza a romperlos en esta fracción, y cuánto vibran por píxel que se mueve el punto.
SNAP_AT = 0.8
STRING_SHAKE = 0.5
STRING_DAMP = 0.86
# Lo que queda más cerca que esto del centro de la cabeza no lleva hilo.
STRING_CLEAR = 1.2


def _smooth(runtime, key: str, value: float, rise: float = 0.35, fall: float = 0.12) -> float:
    """Un valor que sube rápido y baja lento: la señal cruda tiembla."""
    st = runtime.swoosh.setdefault("_living", {})
    old = st.get(key, 0.0)
    rate = 1.0 - (1.0 - (rise if value > old else fall)) ** steps(runtime)
    st[key] = old + (value - old) * rate
    return st[key]


def _dragon(face: Face, u: float, frame_index: int, runtime, layer, alpha: float, event, rng) -> list:
    e = getattr(runtime, "expressions", {}) or {}
    mouth = face.at("mouth_center", (0.0, 1.0))
    blow = max(float(e.get("jawOpen", 0.0)) / JAW_FULL, float(e.get("mouthFunnel", 0.0)), float(e.get("mouthPucker", 0.0)) * 0.8)
    level = _smooth(runtime, "flame", float(np.clip(blow, 0.0, 1.0)))
    charge = _seg(u, 0.0, 0.18)
    st = runtime.swoosh.setdefault(f"_dragon:{event.start_frame if event else 0}", {})
    if u < 0.2:  # las brasas llegan a la boca (más si infla las mejillas)
        count = int(10 + 22 * float(e.get("cheekPuff", 0.0)))
        for k in range(count):
            a = rng.uniform(0, TAU)
            at = mouth + np.array([np.cos(a), np.sin(a)]) * (1.0 - charge) * rng.uniform(0.6, 1.5) * face.unit
            splat(layer, float(at[0]), float(at[1]), 0.022 * face.unit + 0.5, FIRE * 1.4, alpha * charge, runtime.kernels)
        return []
    yaw = (getattr(runtime, "head_pose", None) or (0.0,))[0]
    gaze = gaze_vector(e)[0]
    lean = float(np.clip(yaw / 25.0 + gaze, -1.0, 1.0))
    # Se queda de un lado (de frente, el que le toca) y solo cambia con un giro claro de la cabeza: con
    # la mirada de cada cuadro saltaba de un lado a otro cruzando la cara (expressions_1).
    if "side" not in st:
        st["side"] = float(np.sign(lean)) if abs(lean) >= FLAME_TURN else (1.0 if rng.uniform() < 0.5 else -1.0)
    elif abs(lean) >= FLAME_TURN:
        st["side"] = float(np.sign(lean))
    lean = st["side"] * max(abs(lean), 0.6)
    across, down = face.ux / face.unit, face.uy / face.unit
    aim = across * np.sign(lean) * (0.65 + 0.35 * abs(lean)) + down * 0.55
    old = st.get("aim")
    aim = aim if old is None else old * 0.8 + aim * 0.2  # sigue a la cabeza con inercia
    st["aim"] = aim / max(float(np.linalg.norm(aim)), 1e-6)
    aim = st["aim"]
    side = np.array([-aim[1], aim[0]])
    power = FLAME_MIN + (1.0 - FLAME_MIN) * level
    length = FLAME_LENGTH * face.unit * power
    q = np.linspace(0, 1, 34)
    wave = np.sin(q * 6.0 - frame_index * 0.35) * 0.09 * length * q
    spine = mouth + np.outer(q * length, aim) + np.outer(wave, side) - np.outer(q**2 * 0.2 * length, [0.0, 1.0])
    widths = (0.015 + 0.2 * q**1.1 * (1.0 - 0.5 * q**4)) * face.unit * (0.6 + 0.5 * power)
    life = float(np.clip((u - 0.18) / 0.82, 0.0, 1.0))
    living_ribbon(layer, spine, widths, life, st, frame_index, FIRE, alpha, runtime, grow_from_end=False, tongues=6.0, phase=1.3)
    fade = 1.0 - _seg(u, 0.82, 1.0)
    for k in range(PUFFS):  # el volumen: bocanadas en cono, de amarillo a rojo
        age = (frame_index * 0.055 + k * 0.618) % 1.0
        spread = np.sin(k * 2.4) * (0.1 + 0.9 * age) * 0.55 * power
        lift = np.sin(age * 5.0 + k) * 0.08
        at = mouth + (aim * age * FLAME_LENGTH * power * 1.15 + side * (spread + lift)) * face.unit - np.array([0.0, age**2 * 0.5 * face.unit])
        tint = FLAME_HOT + (FLAME_COOL - FLAME_HOT) * min(age * 1.5, 1.0)
        splat(layer, float(at[0]), float(at[1]), (0.05 + 0.3 * age) * face.unit * (0.6 + 0.5 * power), tint, alpha * fade * 0.55 * (1.0 - age) ** 1.2, runtime.kernels)
    if u < 0.85:
        tip = spine[-1]
        for j, turn in enumerate((-0.8, -0.3, 0.3, 0.8)):  # la punta se abre en lenguas
            d = aim * np.cos(turn) + side * np.sin(turn) - np.array([0.0, 0.5])
            d = d / float(np.linalg.norm(d))
            cel(layer, teardrop(tip - aim * 0.15 * length, d, 0.7 * face.unit * power, 0.08 * face.unit + 0.5, frame_index, j * 2.1, 0.3 * np.sign(turn)), FIRE, alpha, runtime)
    return []


def _sonic(face: Face, frame_index: int, runtime, layer, color, alpha: float, event) -> list:
    e = getattr(runtime, "expressions", {}) or {}
    jaw = float(e.get("jawOpen", 0.0))
    voice = float(getattr(runtime, "voice", 0.0))
    raw = voice * (0.65 + 0.35 * min(jaw / 0.2, 1.0)) if voice > 0 else min(jaw / JAW_FULL, 1.0)
    level = _smooth(runtime, "voice", raw, 0.6, 0.2)
    st = runtime.swoosh.setdefault(f"_sonic:{event.start_frame if event else 0}", {"rings": [], "last": -99, "prev": 0.0})
    mouth = face.at("mouth_center", (0.0, 1.0))
    if frame_index - st["last"] >= PULSE_GAP and level > 0.3 and (level - st["prev"] > PULSE_RISE or level > PULSE_LOUD):
        st["rings"].append({"born": frame_index, "power": level, "at": mouth.copy()})
        st["last"] = frame_index
    st["prev"] = st["prev"] * 0.6 + level * 0.4
    tint = np.asarray(color, np.float32)
    out: list = []
    kept = []
    for ring in st["rings"]:
        life = PULSE_LIFE[0] + (PULSE_LIFE[1] - PULSE_LIFE[0]) * ring["power"]
        age = (frame_index - ring["born"]) / life
        if age >= 1.0:
            continue
        kept.append(ring)
        radius = (0.3 + (1.2 + 3.2 * ring["power"]) * (1.0 - (1.0 - age) ** 2)) * face.unit
        # Hacia abajo y a los lados: no cruza los ojos.
        a = np.linspace(np.radians(-20.0), np.radians(200.0), 48)
        ripple = 1.0 + 0.05 * ring["power"] * np.sin(a * 11.0 + frame_index * 0.5) * (1.0 - age)
        arc = mouth + np.stack([np.cos(a) * radius * ripple, np.sin(a) * radius * ripple * 0.8], axis=1)
        out.append((arc, tint * (1.0 - age) * (0.5 + 0.5 * ring["power"])))
    st["rings"] = kept
    across, down = face.ux / face.unit, face.uy / face.unit
    center = face.place([(0.0, 0.3)])[0]
    for sign in (-1.0, 1.0):  # el ecualizador a los lados de la cabeza
        for k in range(BARS):
            base = center + across * sign * (1.5 + 0.17 * k) * face.unit
            wobble = 0.55 + 0.45 * np.sin(frame_index * 0.7 + k * 1.9 + sign)
            tall = (0.06 + 0.42 * level * wobble * (1.0 - k / (BARS + 1))) * face.unit
            out.append((np.array([base - down * tall, base + down * tall]), tint * (0.5 + 0.5 * level)))
    return out


def _puppet(face: Face, body, u: float, frame_index: int, runtime, layer, color, alpha: float, seed: int) -> None:
    height, width = layer.shape[:2]
    st = runtime.swoosh.setdefault("_puppet", {"x": None, "shake": {}, "prev": {}})
    head = face.place([(0.0, -0.3)])[0]
    st["x"] = float(head[0]) if st["x"] is None else st["x"] + (float(head[0]) - st["x"]) * 0.09  # la cruceta sigue con retraso
    lag = (float(head[0]) - st["x"]) / max(face.unit, 1.0)
    top = max(float(height) * 0.075, float(head[1]) - 4.2 * face.unit)
    bar_tilt = float(np.clip(lag * 0.5, -0.5, 0.5)) + float(np.arctan2(face.ux[1], face.ux[0]))
    bar_dir = np.array([np.cos(bar_tilt), np.sin(bar_tilt)])
    bar_mid = np.array([st["x"], top])
    half = 2.3 * face.unit
    grow = _ease(_seg(u, 0.0, 0.14))
    tint = np.asarray(color, np.float32) * 0.5 + THREAD * 0.5
    bar = np.array([bar_mid - bar_dir * half * grow, bar_mid + bar_dir * half * grow])
    cross = np.array([bar_mid - np.array([-bar_dir[1], bar_dir[0]]) * 0.5 * face.unit * grow, bar_mid + np.array([-bar_dir[1], bar_dir[0]]) * 0.5 * face.unit * grow])
    fine([bar, cross], tint, alpha, layer, width=1.8)
    anchors: dict[str, np.ndarray] = {"sien_d": face.place([(-1.0, -0.4)])[0], "sien_i": face.place([(1.0, -0.4)])[0]}
    for name in ("right_shoulder", "left_shoulder", "right_wrist", "left_wrist"):
        p = body.get(name)
        if p is None or not (0 <= p[0] < width and 0 <= p[1] < height):
            continue
        if abs(float(p[0]) - float(head[0])) >= STRING_CLEAR * face.unit:  # un hilo no cruza la cara
            anchors[name] = p
    names = sorted(anchors, key=lambda name: float(anchors[name][0]))  # de izquierda a derecha: no se enredan
    for k, name in enumerate(names):
        at = anchors[name]
        moved = float(np.linalg.norm(at - st["prev"].get(name, at)))
        st["prev"][name] = at.copy()
        shake = st["shake"].get(name, 0.0) * STRING_DAMP + moved * STRING_SHAKE
        shake = min(shake, 0.35 * face.unit)
        st["shake"][name] = shake
        root = bar_mid + bar_dir * half * ((2.0 * (k + 0.5) / len(names)) - 1.0) * grow
        q = np.linspace(0.0, 1.0, 26)[:, None]
        n = at - root
        n = np.array([-n[1], n[0]]) / max(float(np.linalg.norm(n)), 1e-6)
        wave = np.sin(q * np.pi * 3.0 + frame_index * 1.4 + k) * np.sin(q * np.pi) * shake
        reach = _ease(_seg(u, 0.04 + 0.02 * k, 0.2 + 0.02 * k))
        line = root + (at - root) * q * reach + n * wave
        snap = _seg(u, SNAP_AT + 0.022 * k, SNAP_AT + 0.022 * k + 0.1)
        if snap > 0.0:
            left = disintegrate([(line, tint)], snap, face.unit, layer, alpha, runtime.kernels, seed + k)
            fine([c for c, _ in left], tint, alpha, layer, width=1.2)
            continue
        fine([line], tint, alpha, layer, width=1.2)
        if reach >= 1.0:
            splat(layer, float(at[0]), float(at[1]), 0.05 * face.unit + 0.5, tint, alpha * 0.8, runtime.kernels)


def _raven_shape(at: np.ndarray, size: float, facing: float, flap: float, perched: bool) -> list[np.ndarray]:
    """Un cuervo de perfil mirando hacia `facing`; `flap` (-1 a 1) sube o baja el ala."""
    def p(points) -> np.ndarray:
        return at + np.asarray(points, dtype=np.float64) * [facing * size, size]

    t = np.linspace(0, TAU, 20)
    body = p(np.stack([-0.05 + np.cos(t) * 0.42, 0.05 + np.sin(t) * 0.2], axis=1))
    head = p(np.stack([0.42 + np.cos(t) * 0.15, -0.12 + np.sin(t) * 0.14], axis=1))
    beak = p([[0.55, -0.18], [0.82, -0.09], [0.55, -0.04]])
    tail = p([[-0.42, 0.02], [-0.92, 0.0], [-0.88, 0.14], [-0.42, 0.14]])
    if perched:
        wing = p([[0.25, -0.05], [-0.15, -0.1], [-0.68, 0.1], [-0.2, 0.2], [0.2, 0.08]])
        legs = [p([[0.05, 0.22], [0.08, 0.42]]), p([[-0.12, 0.22], [-0.1, 0.42]])]
        return [body, head, beak, tail, wing, *legs]
    lift = -0.75 * flap
    wing = p([[0.22, -0.05], [0.02, -0.05 + lift * 0.6], [-0.3, -0.05 + lift * 1.25], [-0.42, -0.02 + lift * 0.7], [-0.22, 0.03]])
    near = p([[0.12, -0.05], [-0.1, -0.05 + lift * 0.45], [-0.38, -0.05 + lift * 0.9]])
    return [body, head, beak, tail, wing, near]


def _feather(center: np.ndarray, size: float, spin: float) -> list[np.ndarray]:
    d = np.array([np.cos(spin), np.sin(spin)])
    n = np.array([-d[1], d[0]])
    q = np.linspace(-1.0, 1.0, 9)
    rim = np.sqrt(1.0 - q**2) * 0.32
    return [center + np.outer(q, d) * size * 1.4 + np.outer(rim, n) * size * 1.4, center + np.outer(q[::-1], d) * size * 1.4 - np.outer(rim[::-1], n) * size * 1.4, np.array([center - d * size * 1.9, center + d * size * 1.4])]


def _raven(face: Face, body, scale: float, u: float, frame_index: int, runtime, layer, alpha: float, seed: int) -> list:
    st = runtime.swoosh.setdefault("_raven", {"pos": None, "vel": np.zeros(2), "angle": 0.0, "calm": 0, "perched": False, "frame": -1})
    center = face.place([(0.0, 0.2)])[0]
    energy = float(getattr(runtime, "energy", 0.0))
    if st["pos"] is None:
        st["pos"] = center + np.array([1.8, -0.8]) * face.unit
    shoulders = [p for p in (body.get("left_shoulder"), body.get("right_shoulder")) if p is not None and 0 <= p[0] < layer.shape[1] and 0 <= p[1] < layer.shape[0]]
    size = RAVEN_SIZE * face.unit
    if st["frame"] != frame_index:
        st["frame"] = frame_index
        st["calm"] = st["calm"] + steps(runtime) if energy < RAVEN_CALM else 0
        st["perched"] = bool(shoulders) and 0.2 < u < RAVEN_LEAVE and st["calm"] >= RAVEN_PERCH_AFTER
        n = steps(runtime)
        st["angle"] += (0.05 + 0.22 * energy) * n
        if st["perched"]:
            perch = min(shoulders, key=lambda p: float(np.linalg.norm(p - st["pos"])))
            target = perch - np.array([0.0, size * 0.42])
        else:
            target = center + np.array([np.cos(st["angle"]) * 2.2, np.sin(st["angle"]) * 2.6 + 0.5]) * face.unit  # por delante, a la altura del pecho
        for _ in range(n):
            st["vel"] = (st["vel"] + (target - st["pos"]) * RAVEN_SPRING) * RAVEN_DRAG
            st["pos"] = st["pos"] + st["vel"]
    pos = st["pos"]
    near = st["perched"] and float(np.linalg.norm(st["vel"])) < 0.05 * face.unit
    facing = 1.0 if (st["vel"][0] if not near else center[0] - pos[0]) >= 0 else -1.0
    if not near and np.sin(st["angle"]) < 0:  # detrás de la cabeza
        mask = body_mask(body, layer.shape[:2], scale)
        x, y = int(np.clip(pos[0], 0, layer.shape[1] - 1)), int(np.clip(pos[1], 0, layer.shape[0] - 1))
        if mask is not None and mask[y, x]:
            return []
    curves = _raven_shape(pos, size, facing, float(np.sin(frame_index * (0.45 + 0.5 * energy))), near)
    eye = pos + np.array([0.46 * facing, -0.15]) * size
    pairs = [(c, RAVEN) for c in curves]
    if u < RAVEN_FORM:  # se forma de polvo: la desintegración al revés
        return disintegrate(pairs, 1.0 - u / RAVEN_FORM, face.unit, layer, alpha, runtime.kernels, seed, figure=_feather)
    if u >= RAVEN_LEAVE:
        return disintegrate(pairs, _seg(u, RAVEN_LEAVE, 1.0), face.unit, layer, alpha, runtime.kernels, seed, figure=_feather)
    splat(layer, float(eye[0]), float(eye[1]), max(0.035 * face.unit, 0.8), EYE_RED, alpha, runtime.kernels)
    return pairs


def _eye_curse(face: Face, u: float, frame_index: int, runtime, layer, color, alpha: float, seed: int) -> list:
    e = getattr(runtime, "expressions", {}) or {}
    tint = np.asarray(color, np.float32)
    gx, gy = gaze_vector(e)
    st = runtime.swoosh.setdefault("_curse", {"shut": 0.0, "waves": []})
    blink = max(float(e.get("eyeBlinkLeft", 0.0)), float(e.get("eyeBlinkRight", 0.0)))
    if st["shut"] > 0.5 and blink < 0.35:  # abrió los ojos: suelta la onda
        st["waves"].append(frame_index)
    st["shut"] = blink
    lit = 1.0 - min(blink * 1.4, 1.0)
    t = np.linspace(0, TAU, 28)
    circle = np.stack([np.cos(t), np.sin(t)], axis=1)
    grow = _ease(_seg(u, 0.0, 0.12))
    out: list = []
    for side, sign in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        eye = face.at(f"{side}_iris", (0.5 * sign, 0.0))
        out.append((eye + circle * 0.25 * face.unit * grow, tint * (0.2 + 0.8 * lit)))
        for k in range(5):
            a = frame_index * 0.03 * sign + TAU * k / 5
            glyph = eye + (np.array([np.cos(a), np.sin(a) * 0.8]) * 0.36 + np.array([gx, -gy]) * 0.14) * face.unit * grow
            for stroke in _RUNES[(seed + k) % len(_RUNES)]:
                out.append((glyph + (np.asarray(stroke, dtype=np.float64) - 0.5) * 0.075 * face.unit, tint * lit))
        for born in st["waves"]:
            age = (frame_index - born) / 16.0
            if 0.0 <= age < 1.0:
                out.append((eye + circle * (0.25 + 1.4 * age) * face.unit, tint * (1.0 - age)))
    return out


def living_fx(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    seed = _seed(shape, body, event)
    if shape == "dragon_breath":
        return _dragon(face, u, frame_index, runtime, layer, alpha, event, np.random.default_rng(seed))
    if shape == "puppet_strings":
        _puppet(face, body, u, frame_index, runtime, layer, color, alpha, seed)
        return []
    if shape == "raven":
        return _raven(face, body, scale, u, frame_index, runtime, layer, alpha, seed)
    if shape == "sonic_pulse":
        return _sonic(face, frame_index, runtime, layer, color, alpha, event)
    return melt(_eye_curse(face, u, frame_index, runtime, layer, color, alpha, seed), u, face, layer, color, alpha, runtime.kernels, seed)
