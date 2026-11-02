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
- raven: el cuervo que aterriza en el hombro (engine/raven.py).
- laser_eyes: dos núcleos se cargan en los ojos mientras la persona los entrecierra; al abrirlos (o al
  llenarse la carga) disparan dos rayos hacia donde mira, que estallan en el borde del cuadro.
- cleopatra_eyes: maquillaje de oro y llamas que salen de los ojos (engine/cleopatra.py).
- ice_eyes: iris azul, grietas de luz, escarcha y cristales al parpadear (engine/ice_eyes.py).
- mini_me: la copia diminuta de la cara que flota al lado (engine/hologram.py).
- eye_curse: sellos diminutos alrededor de los ojos que se corren con la mirada, se apagan al cerrar
  los ojos y sueltan una onda al abrirlos.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.expressions import gaze_vector
from vfxglow.engine.cleopatra import cleopatra
from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import disintegrate, fine, melt
from vfxglow.engine.face_glow import _RUNES, WHITE, Face, _seed
from vfxglow.engine.face_signals import smooth as _smooth
from vfxglow.engine.firebend import cel, living_ribbon, teardrop
from vfxglow.engine.hologram import mini_me
from vfxglow.engine.ice_eyes import ice_eyes
from vfxglow.engine.raster import splat
from vfxglow.engine.raven import raven

TAU = 2.0 * np.pi
LIVING = ("dragon_breath", "sonic_pulse", "puppet_strings", "raven", "eye_curse", "laser_eyes", "mini_me", "cleopatra_eyes", "ice_eyes")
ON_THE_FACE = ("dragon_breath", "sonic_pulse", "eye_curse", "laser_eyes", "cleopatra_eyes", "ice_eyes")
FIRE = np.array([1.0, 0.45, 0.1], np.float32)
FLAME_HOT = np.array([1.0, 0.8, 0.2], np.float32)
FLAME_COOL = np.array([1.0, 0.12, 0.03], np.float32)
PUFFS = 64
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
# Hilos: empieza a romperlos en esta fracción, y cuánto vibran por píxel que se mueve el punto.
SNAP_AT = 0.8
STRING_SHAKE = 0.5
STRING_DAMP = 0.86
# Lo que queda más cerca que esto del centro de la cabeza no lleva hilo.
STRING_CLEAR = 1.2
# Láser: carga mínima y máxima (s), caída de los ojos entrecerrados que dispara y cuánto gira el rayo.
LASER_CHARGE = (0.3, 0.8)
LASER_RELEASE = 0.75
LASER_SWAY = 0.1
LASER_SPARKS = 18


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


def _laser(face: Face, u: float, frame_index: int, runtime, layer, color, alpha: float, event, rng) -> list:
    e = getattr(runtime, "expressions", {}) or {}
    height, width = layer.shape[:2]
    tint = np.asarray(color, np.float32)
    st = runtime.swoosh.setdefault(f"_laser:{event.start_frame if event else 0}", {"peak": 0.0, "shot": None})
    squint = (float(e.get("eyeSquintLeft", 0.0)) + float(e.get("eyeSquintRight", 0.0))) / 2.0
    st["peak"] = max(st["peak"], squint)
    held = runtime.active_frames / (getattr(runtime, "fps", 30.0) or 30.0)
    if st["shot"] is None and (held >= LASER_CHARGE[1] or (held >= LASER_CHARGE[0] and squint < st["peak"] * LASER_RELEASE)):
        st["shot"] = frame_index
    eyes = [face.at(f"{side}_iris", (0.5 * sign, 0.0)) for side, sign in (("right", -1.0), ("left", 1.0)) if face.visible(side)]
    if st["shot"] is None:  # la carga: chispas que caen al ojo y un núcleo que crece
        power = min(held / LASER_CHARGE[1], 1.0)
        for eye in eyes:
            for k in range(8):
                a = rng.uniform(0, TAU)
                at = eye + np.array([np.cos(a), np.sin(a)]) * (1.0 - power) * rng.uniform(0.5, 1.1) * face.unit
                splat(layer, float(at[0]), float(at[1]), 0.02 * face.unit + 0.6, tint, alpha, runtime.kernels)
            splat(layer, float(eye[0]), float(eye[1]), (0.03 + 0.09 * power) * face.unit, WHITE, alpha * (0.5 + 0.5 * power), runtime.kernels)
        return []
    gx = gaze_vector(e)[0]
    yaw = (getattr(runtime, "head_pose", None) or (0.0,))[0]
    lean = float(np.clip(yaw / 25.0 + gx, -1.0, 1.0))
    across, down = face.ux / face.unit, face.uy / face.unit
    if "side" not in st:
        st["side"] = float(np.sign(lean)) if abs(lean) > 0.15 else (1.0 if rng.uniform() < 0.5 else -1.0)
    aim = across * st["side"] * (0.8 + 0.2 * abs(lean)) + down * 0.32
    old = st.get("aim")
    st["aim"] = aim if old is None else old + (aim - old) * LASER_SWAY
    aim = st["aim"] / max(float(np.linalg.norm(st["aim"])), 1e-6)
    side = np.array([-aim[1], aim[0]])
    reach = _seg(frame_index - st["shot"], 0.0, 3.0) * float(np.hypot(height, width))
    q = np.linspace(0.0, 1.0, 30)
    out: list = []
    for k, eye in enumerate(eyes):
        wobble = np.sin(q * 18.0 - frame_index * 0.9 + k) * 0.015 * face.unit * (0.3 + q)
        out.append((eye + np.outer(q * reach, aim) + np.outer(wobble, side), tint))
        out.append((eye + np.outer(q * reach, aim) - np.outer(wobble, side), WHITE))
        splat(layer, float(eye[0]), float(eye[1]), 0.16 * face.unit, tint, alpha, runtime.kernels)
        hit = _edge_hit(eye, aim, width, height)
        if reach >= float(np.linalg.norm(hit - eye)):  # el rayo estalla donde llega al borde
            for _ in range(LASER_SPARKS):
                a = rng.uniform(0, TAU)
                at = hit + np.array([np.cos(a), np.sin(a)]) * rng.uniform(0.05, 0.75) * face.unit
                splat(layer, float(at[0]), float(at[1]), 0.03 * face.unit + 0.8, tint, alpha * rng.uniform(0.3, 1.0), runtime.kernels)
    return out


def _edge_hit(start: np.ndarray, aim: np.ndarray, width: int, height: int) -> np.ndarray:
    """Dónde sale del cuadro un rayo que nace en `start`."""
    limits = [((width if d > 0 else 0.0) - s) / d for s, d in ((start[0], aim[0]), (start[1], aim[1])) if abs(d) > 1e-6]
    ahead = [t for t in limits if t > 0.0]
    return start + aim * (min(ahead) if ahead else 0.0)


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
        return raven(face, body, scale, u, frame_index, runtime, layer, alpha, seed)
    if shape == "laser_eyes":
        return _laser(face, u, frame_index, runtime, layer, color, alpha, event, np.random.default_rng([seed, frame_index]))
    if shape == "cleopatra_eyes":
        return cleopatra(face, u, frame_index, runtime, layer, alpha, seed, event)
    if shape == "ice_eyes":
        return ice_eyes(face, u, frame_index, runtime, layer, alpha, seed, event)
    if shape == "mini_me":
        return mini_me(face, u, frame_index, runtime, layer, color, alpha, seed)
    if shape == "sonic_pulse":
        return _sonic(face, frame_index, runtime, layer, color, alpha, event)
    return melt(_eye_curse(face, u, frame_index, runtime, layer, color, alpha, seed), u, face, layer, color, alpha, runtime.kernels, seed)
