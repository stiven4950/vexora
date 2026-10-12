"""La energía que recorre el cuerpo (docs/criterio_de_analisis.md, P2 y P3).

- limb_rings: aros con perspectiva que viajan por una extremidad, de la punta (muñeca, tobillo)
  hacia la raíz (hombro, cadera) y de vuelta, como en video_33 seg. 15: suben por el brazo
  izquierdo casi hasta el hombro, regresan y, cuando el movimiento pasa al brazo derecho, hacen
  el mismo juego ahí. La extremidad es la del evento (`spotlight` con kind left_arm, right_arm,
  legs) o `target.id`. `rings` = aros a la vez; `trail_frames` = fotogramas de una ida.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import MotionEvent
from vfxglow.engine.raster import stroke_batch
from vfxglow.engine.swoosh import neon_layers

CHAINS = {
    "left_arm": [("left_wrist", "left_elbow", "left_shoulder")],
    "right_arm": [("right_wrist", "right_elbow", "right_shoulder")],
    "legs": [("left_ankle", "left_knee", "left_hip"), ("right_ankle", "right_knee", "right_hip")],
}
# Radio del aro en anchos de hombros, inclinación (eje corto / largo) y alfa de la mitad de atrás.
RADIUS = {"left_arm": 0.2, "right_arm": 0.2, "legs": 0.24}
TILT = 0.35
BACK = 0.3


def _point_along(chain: list[np.ndarray], s: float) -> tuple[np.ndarray, np.ndarray]:
    """Punto y dirección a la fracción `s` del largo de la cadena (0 = punta)."""
    lengths = [float(np.linalg.norm(b - a)) for a, b in zip(chain, chain[1:])]
    total = sum(lengths) or 1.0
    target = s * total
    for (a, b), length in zip(zip(chain, chain[1:]), lengths):
        if target <= length or (a is chain[-2]):
            u = target / max(length, 1e-6)
            direction = (b - a) / max(length, 1e-6)
            return a + (b - a) * min(u, 1.0), direction
        target -= length
    return chain[-1], (chain[-1] - chain[-2]) / max(lengths[-1], 1e-6)


def draw_limb_rings(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    style = runtime.effect.style
    if envelope <= 0:
        return
    part = event.kind if event is not None and event.kind in CHAINS else runtime.effect.target.id
    if part not in CHAINS:
        return
    person = event.target.split(":")[0] if event is not None and event.target.startswith("person_") else None
    prefix = f"{person}:" if person else ""

    def get(name: str) -> np.ndarray | None:
        return points.get(f"{prefix}{name}", points.get(name) if not prefix else None)

    shoulders = get("left_shoulder"), get("right_shoulder")
    if shoulders[0] is None or shoulders[1] is None:
        return
    scale = max(float(np.linalg.norm(shoulders[0] - shoulders[1])), 12.0)
    period = max(style.trail_frames, 4)
    rings = max(style.rings, 1)
    line = max(1.5, style.thickness * scale)
    strokes = []
    for names in CHAINS[part]:
        chain = [get(name) for name in names]
        if any(p is None for p in chain):
            continue
        for ring in range(rings):
            # Va y vuelve: de la punta a la raíz en `period` fotogramas, y de regreso.
            phase = ((runtime.active_frames / period) + ring / rings) % 2.0
            s = phase if phase < 1.0 else 2.0 - phase
            center, direction = _point_along(chain, 0.08 + 0.84 * s)
            across = np.array([-direction[1], direction[0]])
            radius = RADIUS[part] * scale
            theta = np.linspace(0.0, 2.0 * np.pi, 41)
            ellipse = center + np.outer(np.cos(theta) * radius, across) + np.outer(np.sin(theta) * radius * TILT, direction)
            color = np.asarray(style.colors[0 if phase < 1.0 else 1 % len(style.colors)], dtype=np.float32)
            front = np.sin(theta) >= 0
            for mask, alpha in ((front, 1.0), (~front, BACK)):
                idx = np.nonzero(mask)[0]
                if len(idx) >= 2:
                    pieces = np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1)
                    for piece in pieces:
                        if len(piece) >= 2:
                            strokes += neon_layers(ellipse[piece], color, line, envelope * alpha)
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)
