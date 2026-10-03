"""Swoosh: la trayectoria reciente de una extremidad como trazo de neón.

No depende de eventos: cada articulación de cada persona deja estela mientras se mueve
rápido, con más brillo cuanto más rápido. La estela se corta si el punto salta de golpe
(el tracker cambió de persona o perdió la articulación), para no cruzar la pantalla.

El trazo imita un tubo de neón: halo ancho y tenue del color, cuerpo del color y núcleo
casi blanco. Se afina y se apaga hacia la cola.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from vfxglow.analysis.schema import FrameRecord
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


def swoosh_keys(track: FrameRecord | None, joints: list[str]) -> list[tuple[str, int]]:
    """(ancla, índice de persona). Con personas detectadas usa person_N:<joint>; si no, el joint plano."""
    if track is not None and track.people:
        keys = []
        for person in track.people:
            index = int(person.person_id.rsplit("_", 1)[-1]) if person.person_id.rsplit("_", 1)[-1].isdigit() else 0
            keys += [(f"{person.person_id}:{joint}", index) for joint in joints]
        return keys
    return [(joint, 0) for joint in joints]


def draw_swoosh(runtime, track: FrameRecord | None, points: dict[str, np.ndarray], frame_index: int, height: int, envelope: float, layer: np.ndarray) -> None:
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
        if active < 0.03 or len(trail) < 3 or envelope <= 0:
            continue
        color = np.asarray(style.colors[person % len(style.colors)], dtype=np.float32)
        # El tracker de la muñeca tiembla; un swoosh dibujado es un arco limpio.
        curve = catmull_rom(_smooth(np.stack([p for _f, p in trail])), samples_per_seg=6)
        width = max(1.2, style.thickness * torso)
        # Line boil: el arco entero se desplaza un poco cada N fotogramas, sin rizarse.
        curve = curve + boil_jitter(effect, frame_index, 1, width * 0.6)
        strokes += _neon(curve, color, width, active)
        if style.rings >= 2 and len(curve) >= 3:
            # Segundo arco paralelo, más fino, como en un swoosh dibujado a mano.
            offset = curve + normals(curve) * width * 2.2
            strokes += _neon(offset, color, width * 0.6, active * 0.6)
    stroke_batch(layer, strokes, style.hdr_gain * envelope)


def _smooth(points: np.ndarray, passes: int = 2) -> np.ndarray:
    """Media móvil 1-2-1 que conserva los extremos (la cabeza sigue pegada a la mano)."""
    out = points.astype(np.float64)
    for _ in range(passes):
        if len(out) < 3:
            break
        inner = (out[:-2] + 2 * out[1:-1] + out[2:]) * 0.25
        out = np.vstack([out[:1], inner, out[-1:]])
    return out


def _neon(curve: np.ndarray, color: np.ndarray, width: float, alpha: float) -> list:
    """Tramos de cola a cabeza, cada vez más anchos y opacos; halo, cuerpo y núcleo."""
    core = color * 0.25 + 0.75
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
        strokes.append((piece, color, w * 3.0, a * 0.16))
        strokes.append((piece, color, w, a * 0.9))
        strokes.append((piece, core, w * 0.4, a))
    return strokes
