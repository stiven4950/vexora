"""Reacciones a lo que hace la cara: besos, impresión y mirada (adornos `type: adornment`).

- kiss_blow: los labios se encienden y sueltan corazones que vuelan hacia la cámara, creciendo; al
  final una marca de labios llega de frente y estalla en corazoncitos (`pucker`, mano en la boca).
- shock_face: cara de impresión: anillos que laten alrededor de los ojos (más grandes si los abre
  más), la boca en "O" que sigue a la de verdad, cejas que saltan y gotas de susto.
- shock_burst: líneas de impacto de cómic alrededor de la cabeza, "!!" a los lados y estrellas.
- gaze_burst: al cambiar la mirada, los ojos disparan partículas hacia donde mira (`gaze_shift`). Es
  una ráfaga de verdad: cada partícula sale del ojo en el cuadro en que nace, sigue su camino y se
  frena, aunque la cabeza siga moviéndose.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.expressions import gaze_vector
from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import melt
from vfxglow.engine.face_glow import WHITE, Face, _palette, _seed
from vfxglow.engine.raster import fill_polygon, splat
from vfxglow.engine.season import _heart, _star

TAU = 2.0 * np.pi
MOODS = ("kiss_blow", "shock_face", "shock_burst", "gaze_burst")
HEARTS = 9
KISS_RED = np.array([1.0, 0.12, 0.42], np.float32)
KISS_PINK = np.array([1.0, 0.45, 0.72], np.float32)
# Ráfaga de la mirada: cuadros que disparan, partículas por ojo y cuadro, velocidad (unidades de cara
# por cuadro) y cuánto se frena en cada cuadro.
GAZE_FRAMES = 14
GAZE_GRAINS = 9
GAZE_SPEED = (0.1, 0.3)
GAZE_DRAG = 0.93
GAZE_LIFE = (14, 28)
# Para fiarse de la mirada del momento y no del evento.
GAZE_MIN = 0.12


def _lip_print(center: np.ndarray, size: float, tilt: float) -> list[np.ndarray]:
    """Una marca de labios: los dos arcos de arriba, el de abajo y la línea entre ambos."""
    q = np.linspace(-1.0, 1.0, 25)
    upper = np.stack([q, -0.2 - 0.34 * np.abs(np.sin(q * np.pi)) * (1 - q**2) ** 0.5 + 0.1 * q**2], axis=1)
    lower = np.stack([q, 0.05 + 0.5 * (1 - q**2)], axis=1)
    middle = np.stack([q, 0.03 * np.sin(q * 9.0) + 0.1 * q**2 - 0.03], axis=1)
    rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
    return [center + (curve * size) @ rot.T for curve in (upper, lower, middle)]


def _kiss(face: Face, u: float, frame_index: int, layer, alpha: float, kernels, rng) -> list:
    mouth = face.at("mouth_center", (0.0, 1.0))
    lips = face.feature("lips_outer")
    side = 1.0 if rng.uniform() < 0.5 else -1.0
    out: list = []
    if lips is not None and u < 0.45:  # los labios encendidos, latiendo, soplan
        beat = 1.0 + 0.1 * np.sin(frame_index * 0.7)
        center = lips.mean(axis=0)
        out.append(((np.vstack([lips, lips[:1]]) - center) * beat + center, KISS_RED * (1.0 - _seg(u, 0.32, 0.45))))
        splat(layer, float(center[0]), float(center[1]), 0.2 * face.unit, KISS_PINK, alpha * 0.3, kernels)
    across, up = face.ux / face.unit, -face.uy / face.unit
    for k in range(HEARTS):
        begin = 0.08 + k * 0.05
        t = _seg(u, begin, begin + 0.42)
        spread = rng.uniform(-1.1, 1.1)
        wobble = rng.uniform(0, TAU)
        if t <= 0.0 or t >= 1.0:
            continue
        glide = 1.0 - (1.0 - t) ** 2  # sale de los labios y se acerca a la cámara
        at = mouth + (across * (side * 1.1 + spread) * glide * 1.4 + up * glide * 2.1 + across * np.sin(t * 7.0 + wobble) * 0.14 * t) * face.unit
        size = (0.05 + 0.34 * glide**1.6) * face.unit
        fade = np.clip((1.0 - t) / 0.3, 0.0, 1.0)
        tint = KISS_RED if k % 2 == 0 else KISS_PINK
        out.append((_heart(at, size), tint * fade))
        for j in range(1, 4):  # su estela de chispas
            back = max(t - j * 0.035, 0.0)
            g = 1.0 - (1.0 - back) ** 2
            p = mouth + (across * (side * 1.1 + spread) * g * 1.4 + up * g * 2.1) * face.unit
            splat(layer, float(p[0]), float(p[1]), 0.02 * face.unit + 0.5, tint, alpha * fade * (0.6 - 0.15 * j), kernels)
    fly = _seg(u, 0.5, 0.82)
    burst = _seg(u, 0.82, 1.0)
    target = mouth + (across * side * 0.9 + up * 1.8) * face.unit
    if 0.0 < fly and burst <= 0.0:  # la marca de labios llega de frente
        glide = _ease(fly)
        at = mouth + (target - mouth) * glide
        for curve in _lip_print(at, (0.12 + 0.95 * glide) * face.unit, side * 0.25):
            out.append((curve, KISS_RED))
    if burst > 0.0:  # y estalla en corazoncitos que se abren
        for k in range(26):
            angle = TAU * k / 26 + rng.uniform(-0.2, 0.2)
            reach = (0.3 + 3.0 * (1.0 - (1.0 - burst) ** 2.2) * rng.uniform(0.4, 1.0)) * face.unit
            at = target + np.array([np.cos(angle), np.sin(angle)]) * reach
            out.append((_heart(at, 0.07 * face.unit * (1.0 - 0.5 * burst)), (KISS_RED if k % 2 else KISS_PINK) * (1.0 - burst)))
    return out


def _shock_face(face: Face, u: float, frame_index: int, expressions: dict, layer, color, alpha: float, kernels) -> list:
    wide = max(float(expressions.get("eyeWideLeft", 0.0)), float(expressions.get("eyeWideRight", 0.0)))
    jaw = float(expressions.get("jawOpen", 0.0))
    pop = 1.0 + 0.5 * np.exp(-u * 16.0) * np.cos(u * 40.0)  # entra con un rebote
    tint = np.asarray(color, np.float32)
    t = np.linspace(0, TAU, 28)
    circle = np.stack([np.cos(t), np.sin(t)], axis=1)
    out: list = []
    for side, sign in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        eye = face.at(f"{side}_iris", (0.5 * sign, 0.0))
        radius = (0.2 + 0.14 * wide) * pop * face.unit
        out.append((eye + circle * radius * 1.25, tint))
        for k in range(2):  # anillos que laten hacia afuera; el ojo queda a la vista
            g = (u * 2.5 + k / 2.0) % 1.0
            out.append((eye + circle * radius * (1.25 + 1.2 * g), tint * (1.0 - g) * 0.7))
    lips = face.feature("lips_inner")
    mouth = face.at("mouth_center", (0.0, 1.0))
    if lips is not None and jaw > 0.2:  # la boca de verdad, encendida por dentro
        fill_polygon(layer, lips, tint * 0.6, alpha * 0.3, 1.0, feather=1.5)
        out.append((np.vstack([lips, lips[:1]]), tint))
    else:
        out.append((mouth + circle * [0.17 * pop * face.unit, (0.11 + 0.2 * jaw) * pop * face.unit], tint))
    q = np.linspace(-1.0, 1.0, 14)
    lift = _ease(_seg(u, 0.0, 0.14)) * 0.2 + 0.03 * np.sin(frame_index * 0.8)
    for sign in (-1.0, 1.0):  # una ceja alta y curva sobre cada ojo
        arc = np.stack([sign * 0.52 + q * 0.3, -0.42 - lift + 0.17 * q**2], axis=1)
        out.append((face.place(arc), tint))
    for k, sign in enumerate((1.0, -1.0)):  # gotas de susto en la sien
        fall = (u * 2.4 + k * 0.5) % 1.0
        at = face.place([(sign * 1.05, -0.25 + 0.8 * fall)])[0]
        ang = np.linspace(0, TAU, 18)
        drop = at + np.stack([np.sin(ang) * (1 - np.cos(ang)) * 0.05, -np.cos(ang) * 0.1], axis=1) * face.unit
        out.append((drop, np.array([0.5, 0.85, 1.0], np.float32) * (1.0 - fall)))
    return out


def _shock_burst(face: Face, u: float, frame_index: int, layer, color, alpha: float, kernels, seed: int) -> list:
    rng = np.random.default_rng((seed + frame_index // 2) & 0xFFFFFFFF)  # las líneas titilan
    center = face.place([(0.0, 0.42)])[0]
    across, down = face.ux / face.unit, face.uy / face.unit
    open_ = _ease(_seg(u, 0.0, 0.1))
    tint = np.asarray(color, np.float32)
    out: list = []
    for k in range(24):
        a = TAU * k / 24 + rng.uniform(-0.05, 0.05)
        ray = across * np.cos(a) * 1.25 + down * np.sin(a) * 1.55
        inner = 1.55 + rng.uniform(0.0, 0.25)
        length = rng.uniform(0.25, 0.75) * open_
        out.append((np.array([center + ray * inner * face.unit, center + ray * (inner + length) * face.unit]), tint if k % 3 else WHITE * 0.85))
    bounce = 1.0 + 0.6 * np.exp(-u * 12.0) * np.cos(u * 34.0)
    for sign in (-1.0, 1.0):
        for k in (0, 1):
            base = center + (across * sign * (1.55 + 0.26 * k) - down * (1.5 - 0.1 * k)) * face.unit
            tip = base - (down * 0.5 - across * sign * 0.07) * face.unit * bounce
            out.append((np.array([tip, base]), WHITE))
            dot = base + down * 0.16 * face.unit
            splat(layer, float(dot[0]), float(dot[1]), 0.05 * face.unit, tint, alpha, kernels)
    grow = 1.0 - (1.0 - u) ** 2
    stars = np.random.default_rng(seed & 0xFFFFFFFF)
    for k in range(10):
        a = stars.uniform(0, TAU)
        at = center + (across * np.cos(a) + down * np.sin(a)) * (1.2 + 2.2 * grow * stars.uniform(0.5, 1.0)) * face.unit
        out.append((_star(at, 0.07 * face.unit * (1.0 - u)), tint * (1.0 - u)))
    return out


def _look(face: Face, expressions: dict, kind: str) -> np.ndarray:
    """Hacia dónde mira, en píxeles (vector unitario): la mirada del cuadro o la del evento."""
    across, down = face.ux / face.unit, face.uy / face.unit
    x, y = gaze_vector(expressions)
    if abs(x) + abs(y) < GAZE_MIN:
        x, y = {"left": (1.0, 0.0), "right": (-1.0, 0.0), "up": (0.0, 1.0), "down": (0.0, -1.0)}.get(kind, (0.0, 1.0))
    d = across * x - down * y
    return d / max(float(np.linalg.norm(d)), 1e-6)


def _gaze(face: Face, frame_index: int, runtime, expressions: dict, layer, colors, alpha: float, event, seed: int) -> list:
    st = runtime.swoosh.setdefault(f"_gaze:{event.start_frame if event else 0}", {"grains": [], "frame": -1})
    rng = np.random.default_rng((seed + frame_index) & 0xFFFFFFFF)
    if st["frame"] != frame_index:
        st["frame"] = frame_index
        kept = []
        for grain in st["grains"]:
            grain["at"] = grain["at"] + grain["v"]
            grain["v"] = grain["v"] * GAZE_DRAG
            grain["age"] += 1
            if grain["age"] < grain["life"]:
                kept.append(grain)
        st["grains"] = kept
        if runtime.active_frames <= GAZE_FRAMES:
            d = _look(face, expressions, event.kind if event else "")
            n = np.array([-d[1], d[0]])
            for side, sign in (("right", -1.0), ("left", 1.0)):
                if not face.visible(side):
                    continue
                eye = face.at(f"{side}_iris", (0.5 * sign, 0.0))
                for _ in range(GAZE_GRAINS):
                    speed = rng.uniform(*GAZE_SPEED) * face.unit
                    st["grains"].append({"at": eye + rng.normal(0.0, 0.02, 2) * face.unit, "v": (d + n * rng.normal(0.0, 0.22)) * speed, "age": 0,
                                         "life": int(rng.integers(*GAZE_LIFE)), "tint": colors[int(rng.integers(len(colors)))]})
                splat(layer, float(eye[0]), float(eye[1]), 0.1 * face.unit, WHITE, alpha, runtime.kernels)
    out: list = []
    for k, grain in enumerate(st["grains"]):
        fade = 1.0 - grain["age"] / grain["life"]
        at = grain["at"]
        splat(layer, float(at[0]), float(at[1]), (0.012 + 0.03 * fade) * face.unit + 0.5, grain["tint"] * 1.5, alpha * fade, runtime.kernels)
        if k % 3 == 0:  # algunas dejan una raya, como un disparo
            out.append((np.array([at - grain["v"] * 2.4, at]), grain["tint"] * fade))
    return out


def face_mood(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    seed = _seed(shape, body, event)
    rng = np.random.default_rng(seed)
    expressions = getattr(runtime, "expressions", {}) or {}
    if shape == "kiss_blow":
        return _kiss(face, u, frame_index, layer, alpha, runtime.kernels, rng)
    if shape == "gaze_burst":
        return _gaze(face, frame_index, runtime, expressions, layer, _palette(runtime, color), alpha, event, seed)
    if shape == "shock_face":
        items = _shock_face(face, u, frame_index, expressions, layer, color, alpha, runtime.kernels)
    else:
        items = _shock_burst(face, u, frame_index, layer, color, alpha, runtime.kernels, seed)
    return melt(items, u, face, layer, color, alpha, runtime.kernels, seed)
