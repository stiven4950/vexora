"""Delinear la ropa (estilo desfile, docs/referencias/video_46.md): los trazos de la prenda que da
analysis/garment.py, en neón con el color del outfit.

- garment_lines: al empezar el outfit (la toma) elige sus trazos: los que más aparecen y más contraste
  tienen en esa toma (así son los mismos de principio a fin): el calzado y el bolso, un par de
  fronteras (prenda contra piel o contra el calzado) y unos pocos bordes de adentro (costuras,
  solapas, franjas). Cuántos, según la perilla `density`. Entra completo en el corte, sigue la tela
  cuadro a cuadro y en los últimos cuadros se parte en guiones (la salida de la referencia).
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.eye_family import pick_knobs
from vfxglow.engine.hand_props import _dashed

GARMENT_FX = ("garment_lines",)
# Cuántos trazos de cada clase elige un outfit (con la perilla `density`: 0,6, 1 o 1,5) y en cuántos de
# los cuadros de la toma tiene que aparecer uno para contar.
PICK = {"accessory": 4, "border": 2, "inner": 3}
PRESENCE = 0.3
# Un trazo que falta unos cuadros se sostiene donde estaba (la máscara parpadea).
HOLD_FRAMES = 3
# La salida: los últimos cuadros de la toma se parte en guiones de este largo (fracción del alto).
EXIT_FRAMES = 6
DASH = 0.03


def _choose(strokes_by_frame: dict, start: int, end: int, density: float, seed: int) -> set[int]:
    """Los trazos de este outfit: por clase, los que más aparecen por su contraste medio."""
    frames = [f for f in range(start, end + 1) if f in strokes_by_frame]
    if not frames:
        return set()
    seen: dict[int, list] = {}
    for f in frames:
        for stroke in strokes_by_frame[f]:
            seen.setdefault(stroke["id"], []).append(stroke)
    rng = np.random.default_rng(seed)
    chosen: set[int] = set()
    for kind, count in PICK.items():
        candidates = []
        for sid, rows in seen.items():
            if rows[0]["kind"] != kind or len(rows) < PRESENCE * len(frames):
                continue
            # Un poco de azar para que dos outfits parecidos no elijan igual (con semilla: repetible).
            candidates.append((len(rows) / len(frames) * float(np.mean([r["score"] for r in rows])) * rng.uniform(0.85, 1.15), sid))
        take = max(int(round(count * density)), 1 if kind != "inner" else 0)
        chosen |= {sid for _, sid in sorted(candidates, reverse=True)[:take]}
    return chosen


def garment_lines(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    strokes_by_frame = getattr(runtime, "garment", None) or {}
    if not strokes_by_frame or event is None:
        return []
    height, width = runtime.frame_shape
    knobs = pick_knobs(shape, body.prefix, event.start_frame, runtime.effect.style.variants)
    st = runtime.swoosh.setdefault(f"_garment:{event.start_frame}", {"last": {}})
    if "ids" not in st:
        seed = zlib.crc32(f"garment:{event.start_frame}:{runtime.effect.id}".encode())
        st["ids"] = _choose(strokes_by_frame, event.start_frame, event.end_frame, float(knobs["density"]), seed)
    for stroke in strokes_by_frame.get(frame_index, []):
        if stroke["id"] in st["ids"]:
            st["last"][stroke["id"]] = (frame_index, np.asarray(stroke["points"], dtype=np.float64) * [width, height])
    lines = [curve for sid, (seen, curve) in st["last"].items() if frame_index - seen <= HOLD_FRAMES]
    left = event.end_frame - frame_index
    if left < EXIT_FRAMES:  # la salida: se parte en guiones
        keep = max(left, 0) / EXIT_FRAMES
        lines = [piece for curve in lines for piece in _dashed(curve, keep, DASH * height)]
    return [(curve, np.asarray(color, np.float32)) for curve in lines if len(curve) >= 2]
