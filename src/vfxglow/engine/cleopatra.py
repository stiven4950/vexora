"""Ojos de Cleopatra: maquillaje de oro que se traza solo y llamas que salen de los ojos.

Primero se dibuja en oro lo que en el trend se pinta con maquillaje: el delineado hacia la sien, la
gota y la cola enroscada del ojo de Horus, puntos bajo el ojo y una diadema en la frente. Así funciona aunque la persona no
se maquille. Después el delineado se enciende: cintas de fuego (engine/firebend.py) nacen del rabillo
del ojo y van hacia las sienes, sin cruzar el ojo.

Nacen del rabillo y giran con la cabeza, no con la mirada: la mirada salta de un cuadro a otro y la
llama cruzaba la cara (lo mismo que en el aliento de dragón, expressions_1). Al parpadear se contraen y
vuelven a encenderse. Sin video de referencia todavía: la forma sale de la descripción del trend.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _seg
from vfxglow.engine.dissolve import fine, melt
from vfxglow.engine.face_glow import Face, _trim, steps
from vfxglow.engine.firebend import GROW_END, living_ribbon
from vfxglow.engine.raster import splat

GOLD = np.array([1.0, 0.76, 0.22], np.float32)
FIRE = np.array([1.0, 0.45, 0.1], np.float32)
EMBER_HOT = np.array([1.0, 0.8, 0.25], np.float32)
EMBER_COOL = np.array([1.0, 0.18, 0.04], np.float32)
# Fases: el oro se traza, el fuego crece y al final se contrae.
TRACE_END = 0.2
FIRE_AT = 0.2
FIRE_GROW = 0.12
CONTRACT_AT = 0.9
# Cintas de cada ojo: (ángulo sobre la horizontal en radianes, largo en unidades de cara).
TONGUES = ((0.5, 2.2), (0.9, 1.5), (0.2, 1.3))
TONGUE_WIDTH = 0.2
# Cuánto se tarda en volver a encender tras parpadear (fracción por paso de 30 fps) y en apagarse.
RELIGHT = 0.16
BLINK_DROP = 0.55
EMBERS = 54
# Chispas que saltan a lo largo de cada llama, y cuánto tiembla su forma (fracción del largo y del ancho).
SPARKS = 16
SHAKE = 0.1
FLUTTER = 0.45


def _corner(face: Face, side: str, out: float) -> np.ndarray:
    """El rabillo externo: el punto del ojo más alejado del centro de la cara."""
    eye = face.feature(f"{side}_eye")
    if eye is None or not len(eye):
        return face.place([(0.85 * out, 0.0)])[0]
    return eye[int(np.argmax(eye @ (face.ux / face.unit) * out))]


def _makeup(corner: np.ndarray, across: np.ndarray, down: np.ndarray, out: float, unit: float) -> list[np.ndarray]:
    def place(x, y) -> np.ndarray:
        return corner + np.outer(np.asarray(x) * out * unit, across) + np.outer(np.asarray(y) * unit, down)

    q = np.linspace(0.0, 1.0, 22)
    wing = place(q * 0.95, -0.3 * q**1.6)
    # El ojo de Horus: una gota recta bajo el ojo y, aparte, la cola que se abre y se enrosca.
    drop = place(np.full(22, -0.4), 0.2 + q * 0.4)
    sweep = place(-0.12 + q * 0.5, 0.2 + 0.26 * q)
    a = np.linspace(-0.5 * np.pi, 1.2 * np.pi, 20)
    size = 0.13 * (1.0 - 0.45 * np.linspace(0.0, 1.0, 20))
    curl = place(0.38 + size * np.cos(a), 0.59 + size * np.sin(a))
    return [wing, drop, np.vstack([sweep, curl])]


def _diadem(face: Face) -> list[np.ndarray]:
    """La diadema de la frente: la banda curva y una joya en rombo con su gota."""
    q = np.linspace(-1.0, 1.0, 34)
    band = face.place(np.stack([q * 1.15, -0.78 - 0.2 * (1.0 - q**2)], axis=1))
    gem = face.place([(0.0, -1.2), (0.15, -0.98), (0.0, -0.76), (-0.15, -0.98), (0.0, -1.2)])
    tear = face.place([(0.0, -0.76), (0.0, -0.58)])
    return [band, gem, tear]


def _noise(q: np.ndarray, frame_index: int, seed: int) -> np.ndarray:
    """Ruido que hierve: varias ondas de distinta escala que corren a distinta velocidad, -1 a 1."""
    t = frame_index * 0.3
    return (
        0.5 * np.sin(q * 5.5 - t + seed)
        + 0.3 * np.sin(q * 13.0 - t * 1.9 + seed * 2.3)
        + 0.2 * np.sin(q * 29.0 - t * 3.1 + seed * 4.1)
    )


def _level(runtime, key: str, blink: float) -> float:
    """El fuego baja rápido al cerrar el ojo y vuelve a encender de a poco."""
    st = runtime.swoosh.setdefault(key, {"level": 1.0})
    target = 1.0 - min(blink * 1.3, 1.0)
    rate = BLINK_DROP if target < st["level"] else RELIGHT
    st["level"] += (target - st["level"]) * (1.0 - (1.0 - rate) ** steps(runtime))
    return st["level"]


def cleopatra(face: Face, u: float, frame_index: int, runtime, layer, alpha: float, seed: int, event) -> list:
    e = getattr(runtime, "expressions", {}) or {}
    across, down = face.ux / face.unit, face.uy / face.unit
    up = -down
    start = event.start_frame if event else 0
    trace = _ease(_seg(u, 0.0, TRACE_END))
    fading = 1.0 - _ease(_seg(u, CONTRACT_AT, 1.0))
    lines: list[np.ndarray] = []
    for side, out, blink_name in (("right", -1.0, "eyeBlinkRight"), ("left", 1.0, "eyeBlinkLeft")):
        if not face.visible(side):
            continue
        corner = _corner(face, side, out)
        lines += [_trim(curve, trace) for curve in _makeup(corner, across, down, out, face.unit)]
        below = corner + across * out * -0.32 * face.unit + down * 0.2 * face.unit
        for k in range(4):  # los puntos bajo el ojo
            at = below + across * out * (k - 1.5) * 0.11 * face.unit + down * 0.015 * (k - 1.5) ** 2 * face.unit
            splat(layer, float(at[0]), float(at[1]), 0.03 * face.unit + 0.6, GOLD, alpha * trace, runtime.kernels)
        power = _level(runtime, f"_cleo:{start}:{side}", float(e.get(blink_name, 0.0))) * fading
        if u < FIRE_AT or power < 0.05:
            continue
        life = _seg(u, FIRE_AT, FIRE_AT + FIRE_GROW) * GROW_END
        outward = across * out
        tips = []
        for k, (angle, length) in enumerate(TONGUES):
            aim = outward * np.cos(angle) + up * np.sin(angle)
            normal = np.array([-aim[1], aim[0]])
            reach = length * face.unit * power * (0.86 + 0.14 * np.sin(frame_index * 0.23 + k * 2.1))
            q = np.linspace(0.0, 1.0, 26)
            wave = _noise(q, frame_index, k) * SHAKE * reach * q
            spine = corner + np.outer(q * reach, aim) + np.outer(wave, normal) + np.outer(q**2 * 0.2 * reach, up)
            widths = (0.012 + TONGUE_WIDTH * q**0.55 * (1.0 - q) ** 1.25) * face.unit * (0.45 + 0.55 * power)
            widths = widths * (1.0 + FLUTTER * _noise(q * 2.3, frame_index + 40, k + 5))  # el borde se come y se hincha
            st = runtime.swoosh.setdefault(f"_cleo:{start}:{side}:{k}", {})
            # Sin `runtime`: la luz que el fuego echa alrededor teñía de naranja todo el cuadro.
            living_ribbon(layer, spine, widths, life, st, frame_index, FIRE, alpha, None, grow_from_end=False, tongues=9.0, phase=float(k))
            tips.append((spine[-1], aim))
            for m in range(SPARKS):  # chispas que se sueltan del cuerpo de la llama y suben
                age = (frame_index * 0.07 + m * 0.381 + k * 0.17) % 1.0
                root = spine[int((m * 0.618 % 1.0) * (len(spine) - 1))]
                sway = np.array([np.sin(m * 3.7 + age * 7.0), 0.0]) * 0.16 * age * face.unit
                at = root + up * age * (0.45 + 0.5 * (m % 3) / 2.0) * face.unit + sway
                tint = EMBER_HOT + (EMBER_COOL - EMBER_HOT) * age
                splat(layer, float(at[0]), float(at[1]), (0.012 + 0.016 * (m % 3)) * face.unit + 0.6, tint, alpha * power * (1.0 - age) ** 0.7, runtime.kernels)
        scatter = np.random.default_rng(seed).uniform((0.8, -1.0, 0.4), (2.2, 1.0, 1.5), (EMBERS, 3))
        for k in range(EMBERS):  # las brasas que se desprenden de las puntas
            tip, aim = tips[k % len(tips)]
            # Cada brasa con su velocidad y su rumbo: con una regla común se alineaban en curvas punteadas.
            speed, spread, reach = scatter[k]
            age = (frame_index * 0.03 * speed + k * 0.618) % 1.0
            drift = spread * 0.9 * age * face.unit
            at = tip + aim * age * reach * face.unit + np.array([-aim[1], aim[0]]) * drift + up * age**2 * 0.7 * face.unit
            tint = EMBER_HOT + (EMBER_COOL - EMBER_HOT) * age
            splat(layer, float(at[0]), float(at[1]), 0.022 * face.unit + 0.6, tint, alpha * power * (1.0 - age), runtime.kernels)
        splat(layer, float(corner[0]), float(corner[1]), 0.06 * face.unit + 0.6, EMBER_HOT, alpha * power, runtime.kernels)
    lines += [_trim(curve, trace) for curve in _diadem(face)]
    # Línea fina: sobre la piel, con el neón grueso el dibujo se vuelve una mancha.
    left = melt([(curve, GOLD) for curve in lines], u, face, layer, GOLD, alpha, runtime.kernels, seed)
    fine([item[0] if isinstance(item, tuple) else item for item in left], GOLD, alpha, layer, width=max(1.3, 0.016 * face.unit))
    return []
