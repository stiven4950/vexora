"""Señales de la cara por fotograma, comunes a los efectos que reaccionan (adornos de la cara).

Las expresiones, la orientación de la cabeza y la voz llegan crudas al motor (`runtime.expressions`,
`runtime.head_pose`, `runtime.voice`): tiemblan de un cuadro al siguiente. Aquí se suavizan una vez
y se derivan las señales que cada efecto leía a su manera:

- Niveles (0-1, suben rápido y bajan lento): parpadeo de cada ojo, ojos muy abiertos, boca, sonrisa,
  ceño, cejas, voz y energía de la cabeza.
- Flancos (solo en el cuadro en que pasan): empieza un parpadeo, abre los ojos después de cerrarlos,
  guiña un ojo (cuál), abre la boca.
- Derivadas: la mirada suavizada, cuántos grados por segundo gira la cabeza, su inclinación, la mirada
  fija (cabeza y ojos quietos un rato, sin parpadear) y la cara relajada (nada se mueve un rato).

Los umbrales son los del análisis (analysis/expressions.py), así un flanco coincide con su evento.
Todo cuenta en pasos de 30 fps: un video de 15 fps reacciona en el mismo tiempo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vfxglow.analysis.expressions import BLINK, FROWN, MOUTH_OPEN, WINK_CLOSED, WINK_OPEN, gaze_vector
from vfxglow.engine.face_glow import steps

# Mirada fija: cuánto puede moverse por paso de 30 fps (mirada de 0 a 1 y grados de la cabeza), desde
# cuándo cuenta (s) y en cuánto tiempo llega a ser plena.
STARE_GAZE = 0.02
STARE_DEG = 0.6
STARE_FROM_S = 0.3
STARE_FULL_S = 0.6
# Cara relajada: la actividad (boca, sonrisa, ceño, energía) por debajo de esto durante RELAXED_S.
RELAXED_BELOW = 0.35
RELAXED_S = 1.0
# Con los ojos así de cerrados la mirada no cuenta: al parpadear las expresiones marcan que mira abajo.
GAZE_BLINK = 0.4


def smooth(runtime, key: str, value: float, rise: float = 0.35, fall: float = 0.12, store: str = "_living") -> float:
    """Un valor que sube rápido y baja lento: la señal cruda tiembla."""
    st = runtime.swoosh.setdefault(store, {})
    old = st.get(key, 0.0)
    rate = 1.0 - (1.0 - (rise if value > old else fall)) ** steps(runtime)
    st[key] = old + (value - old) * rate
    return st[key]


@dataclass
class FaceSignals:
    blink: float = 0.0
    blink_l: float = 0.0
    blink_r: float = 0.0
    wide: float = 0.0
    jaw: float = 0.0
    smile: float = 0.0
    frown: float = 0.0
    brows: float = 0.0
    voice: float = 0.0
    energy: float = 0.0
    blink_start: bool = False
    eyes_opened: bool = False
    wink: str | None = None  # "left" o "right": el ojo que se cerró
    jaw_open_start: bool = False
    gaze: np.ndarray = field(default_factory=lambda: np.zeros(2))  # x hacia la izquierda de la persona, y hacia arriba
    gaze_raw: np.ndarray = field(default_factory=lambda: np.zeros(2))  # la del cuadro, sin suavizar
    yaw_rate: float = 0.0  # grados por segundo, con signo
    roll: float = 0.0
    stare: float = 0.0
    relaxed: float = 0.0


def signals(runtime, frame_index: int, person: str = "") -> FaceSignals:
    """Las señales de este fotograma; se calculan una vez aunque las pidan varios dibujos."""
    st = runtime.swoosh.setdefault(f"_signals:{person}", {"frame": None})
    frame = frame_index
    if st["frame"] == frame:
        return st["out"]
    first = st["frame"] is None
    st["frame"] = frame
    e = getattr(runtime, "expressions", {}) or {}
    get = lambda name: float(e.get(name, 0.0))  # noqa: E731
    store = f"_signals_level:{person}"
    raw_l, raw_r = get("eyeBlinkLeft"), get("eyeBlinkRight")
    raw_blink, raw_jaw = max(raw_l, raw_r), get("jawOpen")
    out = FaceSignals(
        blink=smooth(runtime, "blink", raw_blink, 0.7, 0.4, store),
        blink_l=smooth(runtime, "blink_l", raw_l, 0.7, 0.4, store),
        blink_r=smooth(runtime, "blink_r", raw_r, 0.7, 0.4, store),
        wide=smooth(runtime, "wide", (get("eyeWideLeft") + get("eyeWideRight")) / 2, store=store),
        jaw=smooth(runtime, "jaw", raw_jaw, store=store),
        smile=smooth(runtime, "smile", (get("mouthSmileLeft") + get("mouthSmileRight")) / 2, store=store),
        frown=smooth(runtime, "frown", max(get("browDownLeft"), get("browDownRight")), store=store),
        brows=smooth(runtime, "brows", max(get("browInnerUp"), (get("browOuterUpLeft") + get("browOuterUpRight")) / 2), store=store),
        voice=smooth(runtime, "voice", float(getattr(runtime, "voice", 0.0) or 0.0), 0.6, 0.2, store),
        energy=smooth(runtime, "energy", float(getattr(runtime, "energy", 0.0) or 0.0), store=store),
    )
    # Flancos: contra el cuadro anterior, con los umbrales del análisis. Los ojos se abren en varios
    # cuadros: "cerrados" dura hasta que el más cerrado de los dos baja de WINK_OPEN.
    both, closed, jaw_was = min(raw_l, raw_r), st.get("closed", False), st.get("jaw", 0.0)
    out.blink_start = not first and both >= BLINK and not closed
    out.eyes_opened = closed and raw_blink < WINK_OPEN
    st["closed"] = both >= BLINK or (closed and not out.eyes_opened)
    winking = "left" if raw_l >= WINK_CLOSED and raw_r <= WINK_OPEN else "right" if raw_r >= WINK_CLOSED and raw_l <= WINK_OPEN else None
    out.wink = winking if winking is not None and st.get("winking") != winking else None
    out.jaw_open_start = not first and raw_jaw >= MOUTH_OPEN > jaw_was
    st["jaw"], st["winking"] = raw_jaw, winking
    # La mirada: con los ojos medio cerrados se queda donde estaba.
    gaze = np.asarray(gaze_vector(e), dtype=np.float64) if raw_blink < GAZE_BLINK else st.get("gaze_raw", np.zeros(2))
    previous_gaze = st.get("gaze_raw", gaze)
    st["gaze_raw"] = gaze
    out.gaze_raw = gaze
    out.gaze = np.array([smooth(runtime, "gaze_x", gaze[0], 0.5, 0.5, store), smooth(runtime, "gaze_y", gaze[1], 0.5, 0.5, store)])
    # La cabeza: grados por segundo de giro e inclinación.
    pose = getattr(runtime, "head_pose", None)
    fps = float(getattr(runtime, "fps", 30.0) or 30.0)
    turn = 0.0
    if pose is not None:
        yaw, pitch, roll = (float(v) for v in pose)
        last = st.get("pose", (yaw, pitch, roll))
        turn = float(np.hypot(yaw - last[0], pitch - last[1]))
        out.yaw_rate = smooth(runtime, "yaw_rate", (yaw - last[0]) * fps, 0.5, 0.5, store)
        out.roll = roll
        st["pose"] = (yaw, pitch, roll)
    # Mirada fija: ojos y cabeza quietos, sin parpadear.
    k = steps(runtime)
    moved = float(np.abs(gaze - previous_gaze).max()) > STARE_GAZE * k or turn > STARE_DEG * k
    st["quiet_s"] = 0.0 if moved or raw_blink >= GAZE_BLINK else st.get("quiet_s", 0.0) + 1.0 / fps
    out.stare = float(np.clip((st["quiet_s"] - STARE_FROM_S) / STARE_FULL_S, 0.0, 1.0))
    # Cara relajada: boca, sonrisa, ceño y cabeza en calma un rato.
    activity = max(out.jaw / MOUTH_OPEN, out.smile / 0.5, out.frown / FROWN, out.energy)
    st["calm_s"] = st.get("calm_s", 0.0) + 1.0 / fps if activity < RELAXED_BELOW else 0.0
    out.relaxed = float(np.clip((st["calm_s"] - RELAXED_S) / RELAXED_S, 0.0, 1.0))
    st["out"] = out
    return out
