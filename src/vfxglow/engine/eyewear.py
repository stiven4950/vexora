"""Figuras de neón sobre los ojos: gafas reales realzadas o accesorios inventados.

Todo se ancla a los dos ojos de cada persona (pose o malla) y se escala con la distancia
entre ellos, así que sigue la cabeza aunque gire o se acerque. Cada activación elige una
figura de `style.shapes` con semilla: la misma persona puede llevar gafas de estrellas en un
tramo y un antifaz en el siguiente.

Figuras (unidad = distancia entre ojos, eje x = de ojo a ojo):
- frames: monturas redondeadas con puente y patillas.
- stars: cristales de cinco puntas.
- hearts: cristales de corazón.
- mask: antifaz de una pieza con alas hacia las sienes.
- visor: barra única de lado a lado con línea de barrido.
- rings: anillos concéntricos que giran (hipnosis).
- glint: monturas con destellos diagonales sobre los cristales.
- band: banda gruesa de luz sobre los ojos, con un gancho en un extremo (video_39: la mirada
  encendida al empezar).
- dots: un punto brillante en cada ojo (con el sombrero del seg. 28).
- x_eyes: una X sobre cada ojo ("ya valió", video_33 seg. 11,9, tras el corte de cuello).
- plus_eyes: una "+" sobre cada ojo (video_52 seg. 33,4).
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.raster import stroke_batch
from vfxglow.engine.swoosh import FACE_HALO, neon_layers

SHAPES = ("frames", "stars", "hearts", "mask", "visor", "rings", "glint", "band", "x_eyes", "plus_eyes", "dots")
# Grosor relativo por figura: la banda es un trazo grueso de lado a lado (mirada encendida).
WIDTH = {"band": 9.0}
TAU = 2.0 * np.pi
# Distancia mínima entre ojos (px) para dibujar: más pequeño sería un borrón.
MIN_EYE_DIST = 6.0
# Separación de los ojos como fracción del ancho de hombros. En planos lejanos la pose junta
# los ojos (11 px a 720 de ancho) y las gafas saldrían invisibles; los hombros dan la escala.
EYES_PER_SHOULDERS = 0.22


def _face_neon(*args, **kwargs) -> list:
    """Neón sobre la cara: con poco halo (FACE_HALO), para no lavarla de luz."""
    return neon_layers(*args, halo=FACE_HALO, **kwargs)


def eyes_of(points: dict[str, np.ndarray], person: str | None) -> tuple[np.ndarray, np.ndarray] | None:
    """(ojo izquierdo de la imagen, ojo derecho de la imagen) de una persona, o de la plana."""
    prefix = f"{person}:" if person else ""
    pairs = [(f"{prefix}left_eye", f"{prefix}right_eye")]
    if not person or person == "person_0":
        pairs.insert(0, ("left_iris", "right_iris"))
    for a, b in pairs:
        if a in points and b in points:
            left, right = points[a], points[b]
            return (left, right) if left[0] <= right[0] else (right, left)
    return None


def draw_eyewear(runtime, track: FrameRecord | None, points: dict[str, np.ndarray], frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    if envelope <= 0:
        return
    owner = None
    if event is not None:
        owner = event.attacker or (event.target.split(":", 1)[0] if event.target.startswith("person_") else None)
    if owner is not None:
        people = [owner]
    else:
        # Evento de escena (una pausa) o sin evento: todas las personas visibles.
        people = [person.person_id for person in track.people] if track is not None and track.people else [None]
    strokes = []
    if style.people:
        people = [person for person in people if person in style.people]
    for person in people:
        eyes = eyes_of(points, person)
        if eyes is None:
            continue
        left, right = eyes
        unit = float(np.linalg.norm(right - left))
        if unit < MIN_EYE_DIST:
            continue
        prefix = f"{person}:" if person else ""
        shoulders = [points.get(f"{prefix}left_shoulder"), points.get(f"{prefix}right_shoulder")]
        if all(s is not None for s in shoulders):
            wide = float(np.linalg.norm(shoulders[0] - shoulders[1])) * EYES_PER_SHOULDERS
            if wide > unit:
                middle = (left + right) * 0.5
                axis = (right - left) / unit
                left, right = middle - axis * wide * 0.5, middle + axis * wide * 0.5
                unit = wide
        start = event.start_frame if event is not None else 0
        seed = zlib.crc32(f"{style.seed_offset}:eyewear:{person}:{start}".encode()) & 0xFFFFFFFF
        names = [name for name in style.shapes if name in SHAPES] or ["frames"]
        shape = names[int(np.random.default_rng(seed).integers(0, len(names)))]
        index = int(person.rsplit("_", 1)[-1]) if person and person[-1].isdigit() else 0
        color = np.asarray(style.colors[index % len(style.colors)], dtype=np.float32)
        width = max(1.0, unit * style.thickness * WIDTH.get(shape, 1.0))
        for line in figure(shape, left, right, frame_index):
            strokes += _face_neon(line, color, width, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


def figure(shape: str, left: np.ndarray, right: np.ndarray, frame_index: int = 0) -> list[np.ndarray]:
    """Polilíneas de la figura en píxeles."""
    ux = right - left
    unit = float(np.linalg.norm(ux))
    ux = ux / max(unit, 1e-6)
    uy = np.array([-ux[1], ux[0]])
    if uy[1] < 0:
        uy = -uy  # y local hacia abajo, como la imagen
    center = (left + right) * 0.5

    def place(local: np.ndarray) -> np.ndarray:
        return center + (local[:, :1] * ux + local[:, 1:2] * uy) * unit

    lenses = [np.array([-0.5, 0.0]), np.array([0.5, 0.0])]
    theta = np.linspace(0, TAU, 28)
    if shape == "dots":
        return [place(np.stack([c[0] + np.cos(theta) * 0.06, c[1] + np.sin(theta) * 0.06], axis=1)) for c in lenses]
    if shape == "x_eyes":
        size = 0.3  # grandes: en video_52 cubren el ojo entero
        return [place(np.array([c + [-size, -size], c + [size, size]])) for c in lenses] + [place(np.array([c + [size, -size], c + [-size, size]])) for c in lenses]
    if shape == "plus_eyes":
        size = 0.3
        return [place(np.array([c + [-size, 0.0], c + [size, 0.0]])) for c in lenses] + [place(np.array([c + [0.0, -size], c + [0.0, size]])) for c in lenses]
    if shape == "band":
        t = np.linspace(-1.6, 1.5, 24)
        band = np.stack([t, 0.05 * t**2 - 0.05], axis=1)
        hook = np.array([[-1.6, 0.08], [-1.85, 0.35], [-1.7, 0.65]])
        return [place(np.vstack([hook[::-1], band]))]
    if shape == "visor":
        bar = np.array([[-1.0, -0.22], [1.0, -0.22], [1.05, 0.0], [1.0, 0.22], [-1.0, 0.22], [-1.05, 0.0], [-1.0, -0.22]])
        scan_x = -0.9 + 1.8 * ((frame_index % 24) / 24)
        return [place(bar), place(np.array([[scan_x, -0.18], [scan_x, 0.18]]))]
    if shape == "mask":
        # Media máscara derecha (x >= 0) en sentido horario y su reflejo: alas hacia arriba
        # en las sienes, borde superior que baja al centro y muesca de la nariz abajo.
        half = np.array([
            [0.0, -0.2], [0.3, -0.34], [0.65, -0.36], [0.95, -0.42], [1.3, -0.62],
            [1.2, -0.2], [1.05, 0.12], [0.75, 0.32], [0.4, 0.3], [0.16, 0.2], [0.0, 0.08],
        ])
        mirror = half[::-1] * np.array([-1.0, 1.0])
        outline = np.vstack([half, mirror[1:], half[:1]])
        holes = [np.stack([c[0] + np.cos(theta) * 0.24, c[1] + np.sin(theta) * 0.14], axis=1) for c in lenses]
        return [place(outline), *(place(hole) for hole in holes)]
    lines: list[np.ndarray] = []
    for c in lenses:
        if shape == "stars":
            angles = np.arange(11) * np.pi / 5 - np.pi / 2
            radii = np.where(np.arange(11) % 2 == 0, 0.38, 0.16)
            lens = c + np.stack([np.cos(angles), np.sin(angles)], axis=1) * radii[:, None]
        elif shape == "hearts":
            t = np.linspace(0, TAU, 40)
            hx = 16 * np.sin(t) ** 3
            hy = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
            lens = c + np.stack([hx, hy], axis=1) * 0.021
        elif shape == "rings":
            spin = frame_index * 0.25
            for k, r in enumerate((0.16, 0.28, 0.4)):
                arc = np.linspace(spin * (1 if k % 2 else -1), spin * (1 if k % 2 else -1) + TAU * 0.8, 20)
                lines.append(c + np.stack([np.cos(arc), np.sin(arc)], axis=1) * r)
            continue
        else:
            lens = c + np.stack([np.cos(theta) * 0.36, np.sin(theta) * 0.27], axis=1)
        lines.append(lens)
        if shape == "glint":
            lines.append(c + np.array([[-0.18, 0.1], [0.05, -0.15]]))
            lines.append(c + np.array([[-0.02, 0.14], [0.14, -0.02]]))
    if shape in {"frames", "glint", "stars", "hearts"}:
        lines.append(np.array([[-0.14, -0.06], [0.0, -0.12], [0.14, -0.06]]))  # puente
        lines.append(np.array([[-0.86, -0.06], [-1.25, -0.02]]))  # patilla
        lines.append(np.array([[0.86, -0.06], [1.25, -0.02]]))
    return [place(np.asarray(line, dtype=np.float64)) for line in lines]
