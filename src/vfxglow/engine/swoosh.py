"""Swoosh: la trayectoria reciente de una extremidad como trazo de neón.

No depende de eventos: cada articulación de cada persona deja estela mientras se mueve
rápido, con más brillo cuanto más rápido. La estela se corta si el punto salta de golpe
(el tracker cambió de persona o perdió la articulación), para no cruzar la pantalla.

El trazo imita un tubo de neón: halo ancho y tenue del color, cuerpo del color y núcleo
casi blanco. Se afina y se apaga hacia la cola.

Dos variantes de dibujo a mano:
- hebras (`style.strands`): varias líneas que se separan a mitad de la estela y se juntan
  en la mano, cada una de distinto largo.
- pintura (`style.paint_chance`): en algunas trayectorias largas se dibuja solo el borde de
  la forma que barrería un puño cargado de pintura: fina en la cola, ancha y redondeada
  en la mano, sin relleno. Se decide una vez por golpe, con semilla fija.
"""

from __future__ import annotations

import zlib
from collections import deque

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.anchors import joint_speed, torso_pixels
from vfxglow.engine.glyphs import boil_jitter
from vfxglow.engine.raster import stroke_batch
from vfxglow.geom import catmull_rom, normals

# Salto entre fotogramas (en torsos) que se trata como cambio de persona y corta la estela.
JUMP_TORSOS = 0.6
# Fotogramas sin la articulación tras los que la estela se descarta.
MAX_GAP = 2
# Caída por fotograma de la actividad cuando la extremidad frena.
RELEASE = 0.8
SEGMENTS = 8
# Cuerda / longitud mínima de la estela para dibujarla como contorno de pintura.
PAINT_STRAIGHTNESS = 0.6
PAINT_KEEP = 0.4


def swoosh_keys(track: FrameRecord | None, joints: list[str]) -> list[tuple[str, int]]:
    """(ancla, índice de persona). Con personas detectadas usa person_N:<joint>; si no, el joint plano."""
    if track is not None and track.people:
        keys = []
        for person in track.people:
            index = int(person.person_id.rsplit("_", 1)[-1]) if person.person_id.rsplit("_", 1)[-1].isdigit() else 0
            keys += [(f"{person.person_id}:{joint}", index) for joint in joints]
        return keys
    return [(joint, 0) for joint in joints]


def focused(event: MotionEvent | None, key: str) -> bool:
    """Con un evento que nombra una extremidad, solo esa extremidad dibuja; sin evento, todas."""
    if event is None or not event.target:
        return True
    if ":" in event.target:
        return key == event.target
    return key == event.target or key.endswith(f":{event.target}")


def draw_swoosh(runtime, track: FrameRecord | None, points: dict[str, np.ndarray], frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    effect = runtime.effect
    style = effect.style
    joints = [token.strip() for token in effect.target.id.split(",") if token.strip()]
    torso = torso_pixels(points, height)
    history: dict[str, deque] = runtime.swoosh
    activity: dict[str, float] = runtime.swoosh_activity
    strokes = []
    for key, person in swoosh_keys(track, joints):
        trail = history.setdefault(key, deque(maxlen=max(style.trail_frames, 3)))
        point = points.get(key)
        if trail and frame_index - trail[-1][0] > MAX_GAP:
            trail.clear()
        if point is not None:
            if trail and float(np.linalg.norm(point - trail[-1][1])) > JUMP_TORSOS * torso:
                trail.clear()
            trail.append((frame_index, point.copy()))
        speed = joint_speed(track, key) if point is not None else 0.0
        floor = max(style.min_speed, 1e-6)
        target = float(np.clip((speed - floor) / floor, 0.0, 1.0))
        active = max(target, activity.get(key, 0.0) * RELEASE)
        activity[key] = active
        if active < 0.03 or len(trail) < 3 or envelope <= 0 or not focused(event, key):
            runtime.swoosh_stroke.pop(key, None)
            runtime.swoosh_paint.discard(key)
            continue
        # Un golpe empieza cuando la extremidad se enciende; ahí se decide si es pintura.
        start = runtime.swoosh_stroke.setdefault(key, frame_index)
        color = np.asarray(style.colors[person % len(style.colors)], dtype=np.float32)
        # El tracker de la muñeca tiembla; un swoosh dibujado es un arco limpio.
        curve = catmull_rom(_smooth(np.stack([p for _f, p in trail])), samples_per_seg=6)
        width = max(1.2, style.thickness * torso)
        # Line boil: el arco entero se desplaza un poco cada N fotogramas, sin rizarse.
        curve = curve + boil_jitter(effect, frame_index, 1, width * 0.6)
        length = float(np.linalg.norm(np.diff(curve, axis=0), axis=1).sum())
        chord = float(np.linalg.norm(curve[-1] - curve[0]))
        # Una trayectoria que da la vuelta sobre sí misma enreda el contorno: ahí van hebras.
        # Histéresis: un golpe que ya es pintura sigue siéndolo mientras no se enrede del todo,
        # para que el contorno no parpadee uno o dos fotogramas.
        painting = key in runtime.swoosh_paint
        straight = chord >= (PAINT_KEEP if painting else PAINT_STRAIGHTNESS) * length
        long_enough = painting or length >= style.paint_min_length * torso
        if long_enough and straight and _chosen(style, key, start):
            runtime.swoosh_paint.add(key)
            outline = paint_outline(curve, style.paint_width * torso, frame_index)
            strokes += _neon(outline, color, width, active, taper=False)
            continue
        for strand in strands(curve, max(style.strands, 1), width):
            strokes += _neon(strand[0], color, width * strand[1], active * strand[2])
    stroke_batch(layer, strokes, style.hdr_gain * envelope)


def _chosen(style, key: str, start: int) -> bool:
    if style.paint_chance <= 0:
        return False
    seed = zlib.crc32(f"{style.seed_offset}:{key}:{start}".encode()) & 0xFFFFFFFF
    return float(np.random.default_rng(seed).random()) < style.paint_chance


def strands(curve: np.ndarray, count: int, width: float) -> list[tuple[np.ndarray, float, float]]:
    """(curva, factor de ancho, factor de alfa) por hebra. La primera es la estela principal.

    Las demás se apartan hacia los dos lados, más en el centro de la estela que en los
    extremos, y empiezan más tarde: son más cortas y se juntan en la mano.
    """
    out = [(curve, 1.0, 1.0)]
    if count <= 1 or len(curve) < 4:
        return out
    nrm = normals(curve)
    t = np.linspace(0.0, 1.0, len(curve))[:, None]
    bulge = np.sin(np.pi * np.clip(t * 1.15, 0.0, 1.0))
    for index in range(1, count):
        side = 1.0 if index % 2 else -1.0
        spread = width * (2.0 + 1.6 * ((index + 1) // 2))
        shifted = curve + nrm * bulge * spread * side
        skip = int(len(curve) * 0.18 * index)
        if len(curve) - skip >= 3:
            out.append((shifted[skip:], 0.65 ** index, 0.75 ** index))
    return out


def paint_outline(curve: np.ndarray, max_width: float, frame_index: int) -> np.ndarray:
    """Borde cerrado de la forma barrida: cola en punta, cuerpo que engorda, cabeza redonda."""
    nrm = normals(curve)
    t = np.linspace(0.0, 1.0, len(curve))
    # Un borde dibujado a mano no es perfecto: ondula un poco y cambia cada pocos fotogramas.
    wobble = 1.0 + 0.12 * np.sin(t * 9.0 + (frame_index // 3) * 1.7)
    half = max_width * 0.5 * t**0.75 * wobble
    left = curve + nrm * half[:, None]
    right = curve - nrm * half[:, None]
    head, back = curve[-1], curve[-1] - curve[-2]
    forward = back / max(float(np.linalg.norm(back)), 1e-6)
    side = nrm[-1]
    angles = np.linspace(0.0, np.pi, 12)
    cap = head + (np.cos(angles)[:, None] * side + np.sin(angles)[:, None] * forward) * half[-1]
    return np.vstack([left, cap, right[::-1], left[:1]])


def _smooth(points: np.ndarray, passes: int = 2) -> np.ndarray:
    """Media móvil 1-2-1 que conserva los extremos (la cabeza sigue pegada a la mano)."""
    out = points.astype(np.float64)
    for _ in range(passes):
        if len(out) < 3:
            break
        inner = (out[:-2] + 2 * out[1:-1] + out[2:]) * 0.25
        out = np.vstack([out[:1], inner, out[-1:]])
    return out


def neon_layers(curve: np.ndarray, color: np.ndarray, width: float, alpha: float) -> list:
    """Un tubo de neón: halo ancho del color, cuerpo del color y núcleo claro pero aún teñido.

    Un núcleo casi blanco y un halo tenue lavan el color; aquí el color domina y el núcleo
    solo lo aclara, para que el neón se vea vívido sobre el plano.
    """
    core = color * 0.5 + 0.5
    return [(curve, color, width * 3.4, alpha * 0.3), (curve, color, width, alpha), (curve, core, width * 0.35, alpha * 0.9)]


def _neon(curve: np.ndarray, color: np.ndarray, width: float, alpha: float, taper: bool = True) -> list:
    """Tramos de cola a cabeza, cada vez más anchos y opacos.

    Sin `taper` el trazo es uniforme (un contorno cerrado no tiene cola).
    """
    if not taper:
        return neon_layers(curve, color, width, alpha)
    strokes = []
    bounds = np.linspace(0, len(curve) - 1, SEGMENTS + 1).astype(int)
    for index in range(SEGMENTS):
        start, end = bounds[index], bounds[index + 1] + 1
        if end - start < 2:
            continue
        piece = curve[start:end]
        t = (index + 1) / SEGMENTS
        w = width * (0.3 + 0.7 * t)
        a = alpha * t**1.4
        strokes += neon_layers(piece, color, w, a)
    return strokes
