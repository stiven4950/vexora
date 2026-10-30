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
  adentro → ojos, nariz y boca → los huecos se llenan de una luz tenue. Al final se suelta en polvo
  de luz y figuritas (engine/dissolve.py) que se expanden lejos de la cara.
- Ya armada, la figura queda quieta y la luz corre por dentro de cada línea, como agua por una
  zanja: un tramo brillante recorre cada trazo y suelta chispas por delante.
- El color se sortea en cada aparición entre varias paletas (MASK_PALETTES), con un degradado de lado a
  lado y un acento en ojos y boca; una de ellas es la del dibujo original.
"""

from __future__ import annotations

import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import disintegrate
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
# Cuánto se alarga la boca con la boca abierta (jawOpen = 1) y su tamaño con la boca cerrada (cada
# máscara trae el suyo en `anchors.jaw_rest`).
MOUTH_CLOSED = 0.8
MOUTH_OPEN_GAIN = 0.7
FIT_MIN, FIT_MAX = 0.8, 1.3
# Paletas de la máscara: (izquierda, derecha, acento de ojos y boca). None: los colores del dibujo.
MASK_PALETTES = (
    None,
    ((1.0, 0.25, 0.05), (1.0, 0.75, 0.1), (1.0, 0.95, 0.5)),  # fuego
    ((0.2, 1.0, 0.3), (0.8, 1.0, 0.15), (1.0, 0.2, 0.75)),  # tóxico
    ((1.0, 0.05, 0.12), (0.75, 0.05, 0.5), (1.0, 0.8, 0.8)),  # sangre
    ((1.0, 0.72, 0.15), (1.0, 0.45, 0.25), (1.0, 0.1, 0.1)),  # oro
    ((0.65, 0.2, 1.0), (1.0, 0.25, 0.7), (0.3, 1.0, 0.85)),  # veneno
    ((1.0, 0.4, 0.0), (0.55, 0.15, 1.0), (0.4, 1.0, 0.2)),  # Halloween
    ((0.8, 0.95, 1.0), (0.3, 0.7, 1.0), (1.0, 0.15, 0.2)),  # hielo
)
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
BUILD_S = 0.8
DISSOLVE_S = 1.1


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


def _colored(mask: dict, seed: int) -> list[dict]:
    """Los trazos con la paleta de esta aparición (la máscara cargada no se toca)."""
    palette = MASK_PALETTES[np.random.default_rng(seed).integers(len(MASK_PALETTES))]
    strokes = mask["strokes"]
    if palette is None:
        return strokes
    left, right, accent = (np.asarray(c, np.float32) for c in palette)
    xs = np.array([float(s["points"][:, 0].mean()) for s in strokes])
    lo, hi = float(xs.min()), max(float(xs.max()), float(xs.min()) + 1e-6)
    out = []
    for s, x in zip(strokes, xs):
        color = accent if s["role"] in ("eye_right", "eye_left", "mouth") else left + (right - left) * float((x - lo) / (hi - lo))
        out.append(dict(s, color=color))
    return out


def _fit(face, anchors: dict) -> np.ndarray:
    """Escala de la máscara en coordenadas de cara: de alto, la boca del dibujo cae sobre la boca de
    la persona (con la malla, y solo en las caras de proporción humana)."""
    mouth = anchors.get("mouth")
    if mouth is None or not face.mesh or anchors.get("jaw_rest", MOUTH_CLOSED) < 1.0:
        return np.ones(2)
    real = face.local("mouth_center", (0.0, mouth[1]))[1]
    return np.array([1.0, float(np.clip(real / max(mouth[1], 0.1), FIT_MIN, FIT_MAX))])


def _warp(points: np.ndarray, role: str, anchors: dict, expressions: dict) -> np.ndarray:
    """Los rasgos con la expresión: la boca se alarga desde su borde de arriba, los ojos se achatan."""
    if role not in ("eye_right", "eye_left") and "mouth_top" in anchors:
        # La mandíbula: todo lo que está debajo del borde de arriba de la boca baja con ella, así la
        # boca no se sale de la cara al gritar.
        jaw = float(expressions.get("jawOpen", 0.0))
        top = anchors["mouth_top"][1]
        stretch = anchors.get("jaw_rest", MOUTH_CLOSED) + MOUTH_OPEN_GAIN * jaw
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


# El neón fluye (pedido del usuario): las líneas son zanjas y la luz corre por dentro como agua. La
# figura no se mueve: cada trazo queda tenue (FLOW_BASE) y un tramo brillante de FLOW_LEN de su
# largo lo recorre una vez cada FLOW_PERIOD fotogramas, soltando chispas por delante. Cada trazo
# arranca desfasado, así la luz no corre a la vez por toda la cara.
FLOW_BASE = 0.45
FLOW_LEN = 0.28
FLOW_PERIOD = 40
FLOW_BOOST = 1.6


def _window(line: np.ndarray, a: float, b: float) -> np.ndarray:
    """El tramo de la línea entre las fracciones `a` y `b` de su largo."""
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    total = acc[-1]
    if total <= 0:
        return line[:1]
    marks = np.linspace(max(a, 0.0) * total, min(b, 1.0) * total, max(int((b - a) * len(line) * 3), 3))
    return np.stack([np.interp(marks, acc, line[:, 0]), np.interp(marks, acc, line[:, 1])], axis=1)


def _flow(placed: dict, strokes: list[dict], age: int, face, layer, alpha: float, kernels) -> list:
    """La luz que corre por las líneas: el tramo brillante y sus chispas."""
    out = []
    for k, pts in placed.items():
        if len(pts) < 2:
            continue
        head = ((age + k * 7) % FLOW_PERIOD) / FLOW_PERIOD * (1.0 + FLOW_LEN)
        tail = head - FLOW_LEN
        piece = _window(pts, max(tail, 0.0), min(head, 1.0))
        if len(piece) < 2 or head <= 0.0 or tail >= 1.0:
            continue
        color = strokes[k]["color"]
        out.append((piece, color * FLOW_BOOST))
        tip, behind = piece[-1], piece[max(len(piece) - 3, 0)]
        ahead = (tip - behind) / max(float(np.linalg.norm(tip - behind)), 1e-6)
        if head <= 1.0:  # chispas por delante de la luz que avanza
            for j in range(3):
                fly = tip + ahead * (0.05 + 0.07 * j) * face.unit
                splat(layer, float(fly[0]), float(fly[1]), 0.03 * face.unit + 0.6, color * 1.4, alpha * (0.8 - 0.2 * j), kernels)
    return out


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
    strokes = _colored(mask, zlib.crc32(f"{mask_id}:{event.start_frame if event else 0}".encode()))
    fit = _fit(face, anchors)
    placed = {k: face.place(_warp(s["points"], s["role"], anchors, expressions) * fit) for k, s in enumerate(strokes)}
    flowing = u >= 0.62  # ya armada: la luz corre por las líneas, también mientras se deshace
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
    if flowing:
        out = [(line, tint * FLOW_BASE) for line, tint in out] + _flow(placed, strokes, frame_index, face, layer, alpha, runtime.kernels)
    if u >= FILL_AT:  # los huecos se llenan de una luz tenue, con un pulso
        glow = _seg(u, FILL_AT, FILL_AT + 0.08) * (0.75 + 0.25 * np.sin(frame_index * 0.3))
        for role in FEATURE_ROLES:
            hole = mask["holes"].get(role)
            if hole is None:
                continue
            shape_px = face.place(_warp(hole, role, anchors, expressions) * fit)
            tint = next((s["color"] for s in strokes if s["role"] == role), np.asarray(color, np.float32))
            fill_polygon(layer, shape_px, tint * 0.5, alpha * 0.22 * glow, 1.0, feather=1.5)
    if u >= DISSOLVE:  # se suelta en polvo: el de las líneas enteras, aunque la luz vaya por un tramo
        sources = [(placed[k], strokes[k]["color"]) for k in placed]
        seed = len(strokes) + (event.start_frame if event else 0)
        out = disintegrate(sources, _seg(u, DISSOLVE, 1.0), face.unit, layer, alpha, runtime.kernels, seed, lines=out)
    return out
