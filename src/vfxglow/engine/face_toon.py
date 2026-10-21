"""Cara de caricatura dibujada sobre la cara real (video_33, seg. 6,8-9,2).

Usa los puntos de la cara de la pose (ojos, orejas, nariz, comisuras) y no la malla facial: con
la gorra puesta y la mano en la cara, Face Mesh se pierde justo en esos fotogramas.

- face_toon, formas (`style.shapes`):
  - `tint`: óvalo de la cara relleno (con `blend: tint`, la cara teñida del color del capítulo).
  - `kiss`: ojos cerrados con pestañas y labios grandes de beso (la mano toca la cara).
  - `caricature`: mandíbula, orejas, ojos de punto, nariz y boca (la gorra recién puesta).
  - Expresiones (exagerar lo que hace la cara cuando es protagonista): `sweat` (gotas de sudor
    en la sien), `exclaim` ("!!"), `question` ("?"), `anger` (marca de enojo y nubecita) y
    `heart_eyes` (corazones en los ojos). Se elige una por activación; con la boca abierta
    gana "!!".
- Disparada por `face_touch`, cuando la mano se aparta (después de `end_frame`) llega el
  "jalón": los labios viajan hasta los dedos y los ojos y el tinte se estiran hacia la mano.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.analysis.touch import face_frame, fingertips
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import FACE_HALO, neon_layers
from vfxglow.geom import catmull_rom


def _face_neon(*args, **kwargs) -> list:
    """Neón sobre la cara: con poco halo (FACE_HALO), para no lavarla de luz."""
    return neon_layers(*args, halo=FACE_HALO, **kwargs)


SHAPES = ("tint", "kiss", "caricature", "sweat", "exclaim", "question", "anger", "heart_eyes")
# Expresiones: una por activación. Con la boca abierta (malla facial) gana la sorpresa ("!!").
EMOTES = ("sweat", "exclaim", "question", "anger", "heart_eyes")
MOUTH_OPEN = 0.12  # separación de los labios internos, en tamaños de cara
# Los signos ("!!", "?", sudor, enojo) crecen alrededor de un punto sobre la cabeza: con la cara
# lejos (video_33), a tamaño real quedan del tamaño del halo del neón y no se leen.
EMOTE_SCALE = 2.5
EMOTE_PIVOT = np.array([0.5, 0.75])
# Duración del jalón, en segundos.
YANK_S = 0.3

# Plantillas en coordenadas de cara: x a lo largo de la línea de los ojos, y hacia la frente, en
# tamaños de cara (distancia entre orejas). Origen: el punto medio entre los ojos.
_LIP_UPPER = np.array([(-1.0, 0.0), (-0.55, 0.45), (-0.15, 0.5), (0.0, 0.3), (0.15, 0.5), (0.55, 0.45), (1.0, 0.0)])
_LIP_LOWER = np.array([(1.0, 0.0), (0.6, -0.55), (0.0, -0.7), (-0.6, -0.55), (-1.0, 0.0)])
_LIP_SEAM = np.array([(-0.9, 0.0), (0.0, -0.1), (0.9, 0.0)])
_JAW = np.array([(-0.5, 0.0), (-0.47, -0.35), (-0.3, -0.68), (0.0, -0.8), (0.3, -0.68), (0.47, -0.35), (0.5, 0.0)])
_EAR = np.array([(0.5, 0.05), (0.62, 0.02), (0.63, -0.14), (0.52, -0.2)])
_NOSE = np.array([(0.02, -0.08), (-0.07, -0.3), (0.05, -0.33)])
_MOUTH = np.array([(-0.13, -0.5), (0.0, -0.53), (0.13, -0.5)])


class FaceFrame:
    """Ejes de la cara en píxeles: centro entre los ojos, eje de los ojos y eje hacia la frente."""

    def __init__(self, pts: dict[str, np.ndarray], size: float) -> None:
        self.size = size
        left, right = pts["left_eye"], pts["right_eye"]
        self.origin = (left + right) * 0.5
        across = right - left
        norm = float(np.linalg.norm(across))
        # Sin línea de ojos fiable (de perfil), la cara se dibuja derecha.
        self.x = across / norm if norm > size * 0.15 else np.array([1.0, 0.0])
        self.y = np.array([self.x[1], -self.x[0]])
        if self.y[1] > 0:
            self.y = -self.y
            self.x = -self.x

    def place(self, local: np.ndarray, scale: float = 1.0, origin: np.ndarray | None = None) -> np.ndarray:
        base = self.origin if origin is None else origin
        local = np.asarray(local, dtype=np.float64) * self.size * scale
        return base + np.outer(local[:, 0], self.x) + np.outer(local[:, 1], self.y)


def _face_points(person) -> dict[str, np.ndarray]:
    return {lm.name: np.array([lm.x, lm.y]) for lm in person.pose if lm.c > 0.3}


def _people(track: FrameRecord, event: MotionEvent | None, style) -> list:
    from vfxglow.analysis.touch import _people as people

    found = people(track)
    if event is not None:
        owner = event.target.split(":")[0]
        found = [p for p in found if p.person_id == owner]
    if style.people:
        found = [p for p in found if p.person_id in style.people]
    return found


def _ellipse(face: FaceFrame, stretch_to: np.ndarray | None = None, amount: float = 0.0) -> np.ndarray:
    theta = np.linspace(0.0, 2.0 * np.pi, 48, endpoint=False)
    local = np.stack([0.55 * np.cos(theta), -0.25 + 0.75 * np.sin(theta)], axis=1)
    oval = face.place(local)
    if stretch_to is None or amount <= 0:
        return oval
    # El tinte se alarga hacia la mano: envolvente del óvalo y una copia más chica desplazada.
    import cv2

    pulled = (oval - face.origin) * (1.0 - 0.5 * amount) + face.origin + (stretch_to - face.origin) * amount * 0.6
    hull = cv2.convexHull(np.vstack([oval, pulled]).astype(np.float32))
    return hull[:, 0, :].astype(np.float64)


def _closed_eye(face: FaceFrame, center: np.ndarray) -> list[np.ndarray]:
    """Párpado cerrado (arco hacia abajo) con tres pestañas."""
    half, depth = 0.15, 0.11
    xs = np.linspace(-1.0, 1.0, 11)
    lid = face.place(np.stack([xs * half, -depth * (1.0 - xs**2)], axis=1), origin=center)
    lashes = []
    for k in (-0.7, 0.0, 0.7):
        base = np.array([[k * half, -depth * (1.0 - k**2)]])
        tip = base + np.array([[k * 0.04, -0.05]])
        lashes.append(face.place(np.vstack([base, tip]), origin=center))
    return [lid, *lashes]


def _lips(face: FaceFrame, center: np.ndarray, scale: float, angle: float = 0.0) -> list[np.ndarray]:
    hw, hh = 0.3 * scale, 0.2 * scale
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    shapes = []
    for template in (_LIP_UPPER, _LIP_LOWER, _LIP_SEAM):
        local = (template * [hw, hh]) @ rot.T
        shapes.append(catmull_rom(face.place(local, origin=center), 6))
    return shapes


def draw_face_toon(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    style = runtime.effect.style
    if envelope <= 0 or track is None:
        return
    width = layer.shape[1]
    shapes = set(style.shapes) & set(SHAPES) or {"kiss"}
    color = np.asarray(style.colors[0], dtype=np.float32)
    strokes: list = []
    for person in _people(track, event, style):
        frame = face_frame(person, width, height)
        pts = {name: value * [width, height] for name, value in _face_points(person).items()}
        if frame is None or "left_eye" not in pts or "right_eye" not in pts:
            continue
        _, size = frame
        face = FaceFrame(pts, size)
        mouth = (pts["mouth_left"] + pts["mouth_right"]) * 0.5 if "mouth_left" in pts and "mouth_right" in pts else face.place(np.array([[0.0, -0.5]]))[0]
        # Jalón: después del toque, todo tira hacia la mano que se aparta.
        yank, hand = 0.0, None
        if event is not None and event.name == "face_touch" and frame_index > event.end_frame:
            yank = float(np.clip((frame_index - event.end_frame) / max(YANK_S * runtime.fps, 1.0), 0.0, 1.0))
            tips = fingertips(person, event.kind, width, height) if event.kind in ("left", "right") else []
            hand = np.mean(tips, axis=0) if tips else None
            if hand is None:
                yank = 0.0
        line = max(1.5, style.thickness * size)
        if "tint" in shapes and style.fill > 0:
            fill_polygon(layer, _ellipse(face, hand, yank), color, style.fill * envelope * (1.0 - 0.4 * yank), 0.9, feather=size * 0.08)
        if "kiss" in shapes:
            for eye in ("left_eye", "right_eye"):
                if yank > 0:
                    # Los ojos se vuelven rayas que apuntan a la mano.
                    pull = (hand - pts[eye]) * 0.35 * yank
                    strokes += _face_neon(np.stack([pts[eye], pts[eye] + pull]), color, line, envelope)
                else:
                    for piece in _closed_eye(face, pts[eye]):
                        strokes += _face_neon(piece, color, line, envelope)
            center, scale, angle = mouth, 1.0, 0.0
            if yank > 0:
                ease = yank**0.7
                center = mouth + (hand - mouth) * ease
                scale = 1.0 - 0.3 * ease
                # De lado al llegar a los dedos (como un "3").
                direction = hand - mouth
                angle = float(np.arctan2(np.dot(direction, face.y), np.dot(direction, face.x))) * ease
            for piece in _lips(face, center, scale, angle):
                strokes += _face_neon(piece, color, line, envelope)
        emotes = [name for name in EMOTES if name in shapes]
        if emotes:
            strokes += _emote(_pick_emote(emotes, points, size, event, style, frame_index), face, pts, frame_index, color, line, envelope)
        if "caricature" in shapes:
            jaw = catmull_rom(face.place(_JAW), 6)
            strokes += _face_neon(jaw, color, line, envelope)
            for side in (1.0, -1.0):
                strokes += _face_neon(catmull_rom(face.place(_EAR * [side, 1.0]), 5), color, line, envelope)
            for eye in ("left_eye", "right_eye"):
                theta = np.linspace(0.0, 2.0 * np.pi, 13)
                dot = pts[eye] + np.stack([np.cos(theta), np.sin(theta)], axis=1) * size * 0.035
                strokes += _face_neon(dot, color, line, envelope)
            strokes += _face_neon(face.place(_NOSE), color, line, envelope)
            strokes += _face_neon(catmull_rom(face.place(_MOUTH), 5), color, line, envelope)
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)


def _pick_emote(emotes: list[str], points, size: float, event, style, frame_index: int) -> str:
    upper, lower = points.get("face_13"), points.get("face_14")
    if "exclaim" in emotes and upper is not None and lower is not None and float(np.linalg.norm(upper - lower)) / size > MOUTH_OPEN:
        return "exclaim"
    key = event.start_frame if event is not None else frame_index // 60
    return emotes[zlib.crc32(f"{style.seed_offset}:emote:{key}".encode()) % len(emotes)]


def _heart_local(center: tuple[float, float], size: float) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, 32)
    x = 16 * np.sin(t) ** 3 / 17
    y = (13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)) / 17
    return np.stack([center[0] + x * size, center[1] + y * size], axis=1)


def _emote(name: str, face: FaceFrame, pts, frame_index: int, color, line: float, envelope: float) -> list:
    bob = 0.03 * np.sin(frame_index * 0.4)

    def place(local: np.ndarray) -> np.ndarray:
        # Crece alrededor de un punto sobre la cabeza: grande sin irse lejos de la cara.
        local = np.asarray(local, dtype=np.float64)
        return face.place(EMOTE_PIVOT + (local - EMOTE_PIVOT) * EMOTE_SCALE)

    strokes: list = []
    if name == "sweat":
        for k, (x, y) in enumerate(((0.62, 0.35), (0.7, 0.15))):
            fall = ((frame_index * 0.02 + k * 0.4) % 1.0) * 0.25
            t = np.linspace(0, 2 * np.pi, 24)
            drop = np.stack([x + 0.05 * np.sin(t) * (1 - np.cos(t)) / 2 * 1.6, y - fall + 0.08 * np.cos(t)], axis=1)
            strokes += _face_neon(place(drop), color, line, envelope)
    elif name == "exclaim":
        for x in (0.55, 0.72):
            strokes += _face_neon(place(np.array([[x, 1.35 + bob], [x - 0.02, 0.98 + bob]])), color, line * 1.4, envelope)
            strokes += _face_neon(place(np.array([[x - 0.025, 0.88 + bob], [x - 0.03, 0.85 + bob]])), color, line * 1.6, envelope)
    elif name == "question":
        t = np.linspace(np.pi * 0.9, -np.pi * 0.5, 16)
        hook = np.stack([0.62 + 0.12 * np.cos(t), 1.25 + bob + 0.12 * np.sin(t)], axis=1)
        stem = np.array([[0.62, 1.13 + bob], [0.62, 1.02 + bob]])
        strokes += _face_neon(place(np.vstack([hook, stem])), color, line * 1.3, envelope)
        strokes += _face_neon(place(np.array([[0.62, 0.93 + bob], [0.62, 0.9 + bob]])), color, line * 1.6, envelope)
    elif name == "anger":
        # Marca de enojo (cuatro corchetes curvos) en la sien y una nubecita encima.
        pulse = 1.0 + 0.15 * max(np.sin(frame_index * 0.7), 0.0)
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            corner = np.array([[0.62 + sx * 0.03 * pulse, 0.62 + sy * 0.09 * pulse], [0.62 + sx * 0.03 * pulse, 0.62 + sy * 0.03 * pulse], [0.62 + sx * 0.09 * pulse, 0.62 + sy * 0.03 * pulse]])
            strokes += _face_neon(place(corner), color, line, envelope)
        t = np.linspace(0, 2 * np.pi, 60)
        cloud = np.stack([0.15 * np.cos(t) * (1 + 0.15 * np.cos(6 * t)), 1.25 + bob + 0.08 * np.sin(t) * (1 + 0.15 * np.cos(6 * t))], axis=1)
        strokes += _face_neon(place(cloud), color, line, envelope)
    elif name == "heart_eyes":
        pulse = 1.0 + 0.2 * max(np.sin(frame_index * 0.6), 0.0)
        for eye in ("left_eye", "right_eye"):
            local = np.linalg.lstsq(np.stack([face.x, face.y], axis=1), (pts[eye] - face.origin), rcond=None)[0] / face.size
            strokes += _face_neon(face.place(_heart_local((float(local[0]), float(local[1])), 0.11 * pulse)), color, line, envelope)
    return strokes
