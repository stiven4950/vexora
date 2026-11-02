"""Expresiones de la cara como eventos (catálogo `cara`): lo que dispara los efectos del rostro.

Salen de las expresiones de MediaPipe (`FrameRecord.expressions`, 0-1) y de la orientación de la
cabeza (`FrameRecord.head_pose`, grados). Sin ellas (análisis viejo, cara perdida) no hay eventos.

- mouth_open: la boca abierta un rato.
- blink: los dos ojos se cierran poco tiempo (un parpadeo, no ojos cerrados).
- wink: un solo ojo cerrado (`kind` = el ojo de la persona).
- eyes_wide: los ojos muy abiertos.
- smile: sonrisa.
- brows_up: las cejas suben.
- cheeks_puff: las mejillas infladas.
- pucker: los labios en beso.
- surprise: cara de impresión: cejas arriba y, a la vez, ojos muy abiertos o boca abierta.
- gaze_shift: la mirada salta a otro lado (`kind` = hacia dónde: left, right, up o down, de la persona).
- speaking: habla o grita: suena fuerte y la boca se mueve a la vez.
- head_turn: la cabeza gira rápido hacia un lado (`kind` = hacia dónde).
- head_tilt: la cabeza se inclina hacia un hombro (`kind` = hacia dónde).

`cheekPuff` de MediaPipe casi no se mueve (expressions_1: 0,002 como máximo), así que `cheeks_puff` rara
vez sale; los labios fruncidos sí se ven (`pucker`).

Las cejas, la sonrisa, las mejillas y el beso se miden contra el valor habitual de esa persona en el
video (la mediana): en facil_1 las cejas en reposo ya marcan 0,5-0,7.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent

# Boca abierta y parpadeo: umbrales absolutos (en reposo están cerca de 0).
MOUTH_OPEN = 0.45
MOUTH_MIN_S = 0.2
BLINK = 0.55
BLINK_MAX_S = 0.4
WINK_CLOSED = 0.6
WINK_OPEN = 0.35
WINK_MIN_S = 0.15
# Lo que se mide contra el valor habitual de la persona: cuánto por encima de su mediana, y además
# un mínimo absoluto.
SMILE = (0.5, 0.15)
SMILE_MIN_S = 0.3
BROWS = (0.45, 0.2)
BROWS_MIN_S = 0.2
CHEEKS = (0.35, 0.2)
# Ojos abiertos: el valor es bajo en caras reales (expressions_1, ojos muy abiertos: 0,14; máximo 0,27).
EYES_WIDE = (0.12, 0.08)
EYES_WIDE_MIN_S = 0.2
PUCKER = (0.55, 0.2)
POSE_MIN_S = 0.2
# Cara tensa (ceño fruncido u ojos entrecerrados): con ella, la boca torcida no es un beso y la boca
# abierta no es asombro, es un grito (expressions_1: entrecerrados 0,18 al asombrarse, 0,45 al gritar).
FROWN = 0.35
SQUINT = 0.38
# Evento `frown`: ojos entrecerrados (mínimo, margen sobre lo habitual), sonrisa y ojos cerrados que lo
# descartan, y cuánto debe durar.
FROWN_SQUINT = (0.38, 0.15)
FROWN_SMILE = 0.35
FROWN_BLINK = 0.45
FROWN_MIN_S = 0.2
# Con la boca más abierta que esto, los labios redondos son habla, no un beso.
PUCKER_JAW = 0.35
# Impresión: las cejas arriba con los ojos algo abiertos o la boca algo abierta.
SURPRISE_EYES = 0.1
SURPRISE_JAW = 0.25
# La boca bien abierta y sostenida ya es asombro aunque las cejas casi no suban (expressions_1).
SURPRISE_MOUTH = 0.4
SURPRISE_MIN_S = 0.3
SURPRISE_GAP_S = 0.3
# Hablar: volumen (analysis/voice.py) y boca en movimiento; las pausas cortas no cortan la frase.
SPEAK_VOICE = 0.55
SPEAK_JAW_MOVE = 0.03
SPEAK_GAP_S = 0.3
SPEAK_MIN_S = 0.5
# Mirada: un salto de al menos GAZE_JUMP en GAZE_S (expresiones de 0 a 1), uno cada GAZE_GAP_S. Con
# los ojos medio cerrados no vale: al parpadear las expresiones marcan que mira abajo.
GAZE_JUMP = 0.3
GAZE_S = 0.2
GAZE_GAP_S = 0.8
GAZE_BLINK = 0.4
# Cabeza: un giro de al menos HEAD_TURN_DEG en HEAD_TURN_S; una inclinación de HEAD_TILT_DEG respecto
# de la habitual, sostenida.
HEAD_TURN_DEG = 25.0
HEAD_TURN_S = 0.5
HEAD_TILT_DEG = 15.0
HEAD_TILT_MIN_S = 0.3


def _series(frames: list[FrameRecord], key: str) -> np.ndarray:
    return np.array([f.expressions.get(key, np.nan) if f.expressions else np.nan for f in frames], dtype=np.float64)


def _spans(flags: np.ndarray, min_len: int, max_len: int | None = None) -> list[tuple[int, int]]:
    """Tramos (inicio, fin incluido) en que `flags` es verdadero, de `min_len` a `max_len` cuadros."""
    out, start = [], None
    for k, on in enumerate(list(flags) + [False]):
        if on and start is None:
            start = k
        elif not on and start is not None:
            if k - start >= min_len and (max_len is None or k - start <= max_len):
                out.append((start, k - 1))
            start = None
    return out


def _bridge(flags: np.ndarray, gap: int) -> np.ndarray:
    """Une los tramos separados por huecos de hasta `gap` cuadros."""
    out = flags.copy()
    idx = np.flatnonzero(flags)
    for a, b in zip(idx, idx[1:]):
        if 1 < b - a <= gap + 1:
            out[a:b] = True
    return out


def _nose(frame: FrameRecord) -> tuple[float, float] | None:
    for lm in frame.pose:
        if lm.name == "nose" and lm.c > 0.3:
            return (lm.x, lm.y)
    return None


def _event(frames: list[FrameRecord], name: str, span: tuple[int, int], detail: str, kind: str = "") -> MotionEvent:
    first = frames[span[0]]
    return MotionEvent(
        name=name,
        target=first.person_id,
        start_frame=first.frame,
        end_frame=frames[span[1]].frame,
        confidence=0.8,
        detail=detail,
        position=_nose(first),
        kind=kind,
    )


def _above(values: np.ndarray, floor_delta: tuple[float, float]) -> np.ndarray:
    """Por encima del mínimo absoluto y de la mediana de la persona más el margen."""
    floor, delta = floor_delta
    usual = float(np.nanmedian(values)) if np.isfinite(values).any() else 0.0
    with np.errstate(invalid="ignore"):
        return (values >= floor) & (values >= usual + delta)


def expression_events(frames: list[FrameRecord], fps: float) -> list[MotionEvent]:
    """Eventos de expresión de la cara a lo largo del video."""
    if not frames or not any(f.expressions for f in frames):
        return []
    def n(seconds: float) -> int:
        return max(int(round(seconds * fps)), 1)

    events: list[MotionEvent] = []
    with np.errstate(invalid="ignore"):
        jaw = _series(frames, "jawOpen")
        for span in _spans(jaw >= MOUTH_OPEN, n(MOUTH_MIN_S)):
            events.append(_event(frames, "mouth_open", span, "Abre la boca."))
        left, right = _series(frames, "eyeBlinkLeft"), _series(frames, "eyeBlinkRight")
        for span in _spans((left >= BLINK) & (right >= BLINK), 1, n(BLINK_MAX_S)):
            events.append(_event(frames, "blink", span, "Parpadea."))
        for side, closed, opened in (("left", left, right), ("right", right, left)):
            for span in _spans((closed >= WINK_CLOSED) & (opened <= WINK_OPEN), n(WINK_MIN_S)):
                events.append(_event(frames, "wink", span, "Guiña un ojo.", side))
        wide = (_series(frames, "eyeWideLeft") + _series(frames, "eyeWideRight")) / 2
        for span in _spans(_above(wide, EYES_WIDE), n(EYES_WIDE_MIN_S)):
            events.append(_event(frames, "eyes_wide", span, "Abre mucho los ojos."))
        smile = (_series(frames, "mouthSmileLeft") + _series(frames, "mouthSmileRight")) / 2
        for span in _spans(_above(smile, SMILE), n(SMILE_MIN_S)):
            events.append(_event(frames, "smile", span, "Sonríe."))
        brows = np.fmax(_series(frames, "browInnerUp"), (_series(frames, "browOuterUpLeft") + _series(frames, "browOuterUpRight")) / 2)
        for span in _spans(_above(brows, BROWS), n(BROWS_MIN_S)):
            events.append(_event(frames, "brows_up", span, "Sube las cejas."))
        frown = np.nan_to_num(np.fmax(_series(frames, "browDownLeft"), _series(frames, "browDownRight"))) >= FROWN
        frown |= np.nan_to_num((_series(frames, "eyeSquintLeft") + _series(frames, "eyeSquintRight")) / 2) >= SQUINT
        open_jaw, open_eyes = np.nan_to_num(jaw), np.nan_to_num(wide) >= SURPRISE_EYES
        raised = _above(brows, BROWS) & (open_eyes | (open_jaw >= SURPRISE_JAW))
        for span in _spans(_bridge((raised | (open_jaw >= SURPRISE_MOUTH)) & ~frown, n(SURPRISE_GAP_S)), n(SURPRISE_MIN_S)):
            events.append(_event(frames, "surprise", span, "Pone cara de impresión."))
        for span in _spans(_above(_series(frames, "cheekPuff"), CHEEKS), n(POSE_MIN_S)):
            events.append(_event(frames, "cheeks_puff", span, "Infla las mejillas."))
        pucker = np.fmax(_series(frames, "mouthPucker"), _series(frames, "mouthFunnel"))
        for span in _spans(_above(pucker, PUCKER) & ~frown & (open_jaw < PUCKER_JAW), n(POSE_MIN_S)):
            events.append(_event(frames, "pucker", span, "Pone los labios en beso."))
    events += _speech_events(frames, fps)
    events += _gaze_events(frames, fps)
    events += _head_events(frames, fps)
    return sorted(events, key=lambda e: e.start_frame)


def frown_spans(frames: list[FrameRecord], fps: float) -> list[MotionEvent]:
    """Ceño o ojos entrecerrados claros (por encima de lo habitual de esa cara): en expressions_1 el
    valor normal de `eyeSquint` ya es 0,31. Sonreír o cerrar los ojos también lo suben."""
    if not frames or not any(f.expressions for f in frames):
        return []
    with np.errstate(invalid="ignore"):
        brow = np.fmax(_series(frames, "browDownLeft"), _series(frames, "browDownRight"))
        squint = (_series(frames, "eyeSquintLeft") + _series(frames, "eyeSquintRight")) / 2
        smile = (_series(frames, "mouthSmileLeft") + _series(frames, "mouthSmileRight")) / 2
        blink = np.fmax(_series(frames, "eyeBlinkLeft"), _series(frames, "eyeBlinkRight"))
        tense = (np.nan_to_num(brow) >= FROWN) | _above(squint, FROWN_SQUINT)
        tense &= (np.nan_to_num(smile) < FROWN_SMILE) & (np.nan_to_num(blink) < FROWN_BLINK)
    return [_event(frames, "frown", span, "Frunce el ceño.") for span in _spans(tense, max(int(round(FROWN_MIN_S * fps)), 1))]


def gaze_vector(expressions: dict[str, float]) -> tuple[float, float]:
    """Hacia dónde mira: (x, y), con x hacia la izquierda de la persona e y hacia arriba."""
    get = expressions.get
    x = (get("eyeLookOutLeft", 0.0) - get("eyeLookInLeft", 0.0) + get("eyeLookInRight", 0.0) - get("eyeLookOutRight", 0.0)) / 2
    y = (get("eyeLookUpLeft", 0.0) + get("eyeLookUpRight", 0.0) - get("eyeLookDownLeft", 0.0) - get("eyeLookDownRight", 0.0)) / 2
    return x, y


def _speech_events(frames: list[FrameRecord], fps: float) -> list[MotionEvent]:
    voice = np.array([f.voice for f in frames], dtype=np.float64)
    if not voice.any():
        return []  # sin audio, o análisis anterior al volumen
    jaw = np.nan_to_num(_series(frames, "jawOpen"))
    moved = np.abs(np.diff(jaw, prepend=jaw[0]))
    width = max(int(round(SPEAK_GAP_S * fps)), 1)
    kernel = np.ones(width)
    loud = np.convolve((voice >= SPEAK_VOICE).astype(float), kernel, "same") > 0
    moving = np.convolve(moved, kernel / width, "same") >= SPEAK_JAW_MOVE / 3
    return [_event(frames, "speaking", span, "Habla.") for span in _spans(loud & moving, max(int(round(SPEAK_MIN_S * fps)), 1))]


def _gaze_events(frames: list[FrameRecord], fps: float) -> list[MotionEvent]:
    if not any("eyeLookInLeft" in (f.expressions or {}) for f in frames):
        return []  # análisis anterior a la mirada
    gaze = np.array([gaze_vector(f.expressions) if f.expressions else (np.nan, np.nan) for f in frames], dtype=np.float64)
    blink = np.fmax(_series(frames, "eyeBlinkLeft"), _series(frames, "eyeBlinkRight"))
    with np.errstate(invalid="ignore"):
        gaze[blink >= GAZE_BLINK] = np.nan
    window, gap = max(int(round(GAZE_S * fps)), 1), max(int(round(GAZE_GAP_S * fps)), 1)
    events: list[MotionEvent] = []
    k, last = window, -10_000
    while k < len(frames):
        change = gaze[k] - gaze[k - window]
        if np.isfinite(change).all() and float(np.linalg.norm(change)) >= GAZE_JUMP and k - last > gap:
            if abs(change[0]) >= abs(change[1]):
                kind = "left" if change[0] > 0 else "right"
            else:
                kind = "up" if change[1] > 0 else "down"
            events.append(_event(frames, "gaze_shift", (k - window, k), "Cambia la mirada.", kind))
            last = k
        k += 1
    return events


def _head_events(frames: list[FrameRecord], fps: float) -> list[MotionEvent]:
    yaw = np.array([f.head_pose[0] if f.head_pose else np.nan for f in frames], dtype=np.float64)
    roll = np.array([f.head_pose[2] if f.head_pose else np.nan for f in frames], dtype=np.float64)
    events: list[MotionEvent] = []
    window = max(int(round(HEAD_TURN_S * fps)), 1)
    k, last = window, -10_000
    while k < len(frames):
        change = yaw[k] - yaw[k - window]
        if np.isfinite(change) and abs(change) >= HEAD_TURN_DEG and k - last > window:
            side = "left" if change > 0 else "right"
            events.append(_event(frames, "head_turn", (k - window, k), "Gira la cabeza.", side))
            last = k
            k += window
            continue
        k += 1
    if np.isfinite(roll).any():
        usual = float(np.nanmedian(roll))
        with np.errstate(invalid="ignore"):
            for side, flags in (("left", roll - usual >= HEAD_TILT_DEG), ("right", roll - usual <= -HEAD_TILT_DEG)):
                for span in _spans(flags, max(int(round(HEAD_TILT_MIN_S * fps)), 1)):
                    events.append(_event(frames, "head_tilt", span, "Inclina la cabeza.", side))
    return events
