"""Rostros de terror en neón sobre la cara (modo Halloween; adornos `type: adornment`).

Cada máscara es un archivo de assets/masks/<id>.yaml que sale de la cuadrícula de referencia con
tools/mask_from_grid.py: trazos con su rol (`eye_right`, `eye_left`, `mouth`, `nose`, `line`) y su
color, en coordenadas de cara (ojos en x = ±0,5, y hacia el mentón). La forma es `terror_<id>`
(`terror_ghostface`).

- Se ajusta a la cara por los ojos (engine/face_glow.Face: malla o plantilla de la pose), así que
  sigue la proporción, el giro y la inclinación de cada persona.
- Vive con la expresión: la boca se alarga cuando la persona abre la boca (`jawOpen`, el grito) y
  los ojos se achatan al parpadear.
- Aparece en orden: partículas que llegan a las líneas → el contorno se traza de afuera hacia
  adentro → ojos, nariz y boca → los huecos se llenan de una luz tenue → pulso. Al final se
  deshace en guiones y partículas.
- El color es el del dibujo (el degradado de la referencia).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.face_glow import Face, _trim
from vfxglow.engine.raster import fill_polygon, splat

ASSETS = Path(__file__).resolve().parents[3] / "assets" / "masks"
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
# Fases del momento (fracción): partículas, contorno, rasgos, relleno, salida.
PARTICLES_END = 0.12
OUTLINE = (0.06, 0.38)
FEATURES = (0.3, 0.55)
FILL_AT = 0.5
DISSOLVE = 0.88
# Cuánto se alarga la boca con la boca abierta (jawOpen = 1) y su tamaño con la boca cerrada.
MOUTH_CLOSED = 0.8
MOUTH_OPEN_GAIN = 0.7
FEATURE_ROLES = ("eye_right", "eye_left", "nose", "mouth")


@lru_cache(maxsize=None)
def load_mask(mask_id: str) -> dict:
    data = yaml.safe_load((ASSETS / f"{mask_id}.yaml").read_text(encoding="utf-8"))
    data["strokes"] = [dict(s, points=np.asarray(s["points"], dtype=np.float64), color=np.asarray(s["color"], np.float32)) for s in data["strokes"]]
    data["holes"] = {k: np.asarray(v, dtype=np.float64) for k, v in data.get("holes", {}).items()}
    return data


def _available() -> tuple[str, ...]:
    if not ASSETS.exists():
        return ()
    return tuple(f"terror_{p.stem}" for p in sorted(ASSETS.glob("*.yaml")))


HORROR_MASKS = _available()


# Se arma en BUILD_S segundos y se deshace en los últimos DISSOLVE_S, dure lo que dure el momento:
# en cara se queda varios segundos sin que la aparición vaya en cámara lenta.
BUILD_S = 1.4
DISSOLVE_S = 0.5


def _timeline(runtime, event) -> float:
    """La fracción del momento para las fases: la aparición y la salida a ritmo fijo, lo de en medio
    sostenido (con el pulso del relleno)."""
    triggers = runtime.effect.triggers
    hold = triggers[0].hold if triggers else 20
    span = (event.end_frame - event.start_frame + 1 + hold) if event is not None else 60
    fps = getattr(runtime, "fps", 30.0) or 30.0
    build, dissolve = BUILD_S * fps, DISSOLVE_S * fps
    age = runtime.active_frames
    if span <= build + dissolve:  # un momento corto: la escala de siempre
        return _phase(runtime, event)
    if age < build:
        return 0.62 * age / build
    remaining = span - age
    if remaining > dissolve:
        return 0.7
    return DISSOLVE + (1.0 - DISSOLVE) * float(np.clip(1.0 - remaining / dissolve, 0.0, 1.0))


def _warp(points: np.ndarray, role: str, anchors: dict, expressions: dict) -> np.ndarray:
    """Los rasgos con la expresión: la boca se alarga desde su borde de arriba, los ojos se achatan."""
    if role not in ("eye_right", "eye_left") and "mouth_top" in anchors:
        # La mandíbula: todo lo que está debajo del borde de arriba de la boca baja con ella, así la
        # boca no se sale de la cara al gritar.
        jaw = float(expressions.get("jawOpen", 0.0))
        top = anchors["mouth_top"][1]
        stretch = MOUTH_CLOSED + MOUTH_OPEN_GAIN * jaw
        out = points.copy()
        below = points[:, 1] > top
        out[below, 1] = top + (points[below, 1] - top) * stretch
        return out
    if role in ("eye_right", "eye_left") and role in anchors:
        side = "Right" if role == "eye_right" else "Left"
        blink = float(expressions.get(f"eyeBlink{side}", 0.0))
        cy = anchors[role][1]
        out = points.copy()
        out[:, 1] = cy + (points[:, 1] - cy) * max(1.0 - 0.85 * blink, 0.12)
        return out
    return points


def _order(strokes: list[dict]) -> list[tuple[int, dict]]:
    """Las líneas de afuera hacia adentro (la capucha antes que la cara)."""
    lines = [(k, s) for k, s in enumerate(strokes) if s["role"] == "line"]
    return sorted(lines, key=lambda item: -float(np.linalg.norm(item[1]["points"].mean(axis=0) - [0.0, 0.6])))


def _dashed(line: np.ndarray, keep: float, period: float) -> list[np.ndarray]:
    from vfxglow.engine.hand_props import _dashed as dashed

    return dashed(line, keep, period)


def horror_mask(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    mask_id = shape.removeprefix("terror_")
    try:
        mask = load_mask(mask_id)
    except FileNotFoundError:
        return []
    face = Face(body, scale)
    u = _timeline(runtime, event)
    expressions = getattr(runtime, "expressions", {}) or {}
    anchors = mask["anchors"]
    strokes = mask["strokes"]
    placed = {k: face.place(_warp(s["points"], s["role"], anchors, expressions)) for k, s in enumerate(strokes)}
    out: list = []
    rng = np.random.default_rng(len(strokes) + (event.start_frame if event else 0))
    if u < PARTICLES_END:  # las partículas llegan a las líneas
        k = u / PARTICLES_END
        for stroke_index, pts in placed.items():
            for p in pts[:: max(len(pts) // 3, 1)]:
                start = p + rng.normal(0.0, 1.0, 2) * face.unit * 1.2
                at = start + (p - start) * _ease(k)
                splat(layer, float(at[0]), float(at[1]), 0.04 * face.unit + 0.6, strokes[stroke_index]["color"] * 1.2, alpha * (0.4 + 0.6 * k), runtime.kernels)
    lines = _order(strokes)
    for rank, (k, stroke) in enumerate(lines):  # el contorno, de afuera hacia adentro
        a = OUTLINE[0] + (OUTLINE[1] - OUTLINE[0]) * rank / max(len(lines), 1) * 0.6
        part = _seg(u, a, a + (OUTLINE[1] - OUTLINE[0]) * 0.5)
        if part > 0:
            out.append((_trim(placed[k], _ease(part)), stroke["color"]))
    for k, stroke in enumerate(strokes):  # ojos, nariz y boca
        if stroke["role"] == "line":
            continue
        part = _seg(u, *FEATURES)
        if part > 0:
            out.append((_trim(placed[k], _ease(part)), stroke["color"]))
    if u >= FILL_AT:  # los huecos se llenan de una luz tenue, con un pulso
        glow = _seg(u, FILL_AT, FILL_AT + 0.08) * (0.75 + 0.25 * np.sin(frame_index * 0.3))
        for role in FEATURE_ROLES:
            hole = mask["holes"].get(role)
            if hole is None:
                continue
            shape_px = face.place(_warp(hole, role, anchors, expressions))
            tint = next((s["color"] for s in strokes if s["role"] == role), np.asarray(color, np.float32))
            fill_polygon(layer, shape_px, tint * 0.5, alpha * 0.22 * glow, 1.0, feather=1.5)
    if u >= DISSOLVE:  # se deshace en guiones y partículas
        keep = 1.0 - _seg(u, DISSOLVE, 1.0)
        broken = []
        for line, tint in out:
            broken += [(piece, tint) for piece in _dashed(line, keep, 0.18 * face.unit)]
            if keep < 0.7:
                for p in line[:: max(len(line) // 4, 1)]:
                    drift = p + rng.normal(0.0, 1.0, 2) * face.unit * 0.3 * (1.0 - keep)
                    splat(layer, float(drift[0]), float(drift[1]), 0.03 * face.unit + 0.5, tint, alpha * keep, runtime.kernels)
        out = broken
    return out
