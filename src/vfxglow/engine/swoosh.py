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
from vfxglow.engine.raster import fill_polygon, splat, stroke_batch
from vfxglow.geom import catmull_rom, normals

# Salto entre fotogramas (en torsos) que se trata como cambio de persona y corta la estela.
JUMP_TORSOS = 0.6
# Fotogramas sin la articulación tras los que la estela se descarta.
MAX_GAP = 2
# Caída por fotograma de la actividad cuando la extremidad frena.
RELEASE = 0.8
SEGMENTS = 8
WIND_MIN_WIDTH = 0.012  # ancho mínimo del viento (fracción del alto del cuadro), como el fuego (_unit)
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
    if event.target.startswith("person_"):
        # El evento nombra a una persona (un foco de la línea de atención): todas sus extremidades.
        return key.startswith(f"{event.target}:")
    return key == event.target or key.endswith(f":{event.target}")


def draw_swoosh(runtime, track: FrameRecord | None, points: dict[str, np.ndarray], frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    effect = runtime.effect
    style = effect.style
    if "wind" in style.shapes and envelope > 0:  # viento del modo Avatar: el capítulo es de aire
        from vfxglow.engine.firebend import note_wind

        note_wind(frame_index)
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
        if "wind" in style.shapes:  # el viento, visible aunque la persona ocupe poco del cuadro
            width = max(width, WIND_MIN_WIDTH * height)
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
        if style.trail_style == "dots":
            # Bolas de fuego a lo largo de la estela, más grandes cerca de la extremidad.
            for k, t in enumerate(np.linspace(0.15, 1.0, 6)):
                at = curve[int(t * (len(curve) - 1))]
                splat(layer, float(at[0]), float(at[1]), width * (2.5 + 4.0 * t), color * style.hdr_gain * envelope, active * (0.4 + 0.6 * t), runtime.kernels)
            continue
        if style.trail_style == "plain":
            # Viento: cintas rellenas del color, anchas en la extremidad y en punta en la cola, como
            # pinceladas de aire; sin halo ni resplandor (por debajo del umbral del brillo). Con
            # líneas finas no se notaba. `thickness` es el medio ancho máximo, en torsos. Solo los
            # recorridos que barren: los que se enroscan (la mano que tiembla o gira en el lugar)
            # hacían rulos.
            if chord < 0.65 * length or length < 0.6 * torso:
                continue
            # Con `glow` en shapes, la misma pincelada en neón: el color con su ganancia (el bloom le
            # pone el halo), como el viento azul; sin él, liso y sin resplandor (el blanco).
            glow = "glow" in style.shapes
            tint, gain = (color, style.hdr_gain) if glow else (np.minimum(color, 0.92), 1.0)
            for strand in strands(curve, max(style.strands, 1), width * 0.6):  # hebras pegadas (separadas, en las curvas se cruzaban)
                fill_polygon(layer, _sliver(strand[0], width * strand[1]), tint, active * strand[2] * envelope, gain, feather=1.5)
            continue
        for strand in ([] if style.cross else strands(curve, max(style.strands, 1), width)):
            strokes += _neon(strand[0], color, width * strand[1], active * strand[2])
        if style.trail_style == "flame":
            strokes += flame_tongues(curve, width, color, active, frame_index, style.boil_frames)
        if style.cross:
            # Las dos aspas enteras, sin fundido de cola: con fundido solo se ve una "V".
            for arc in crossed(curve):
                strokes += _neon(arc, color, width * 0.85, active * 0.9, taper=False)
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


# Grosor del núcleo blanco como fracción del ancho del cuadro: 0,5% = 3,6 px a 720 y 5,4 px a 1080,
# el rango de 3-5 px que hace leer la línea como filamento incandescente y no como pintura.
# Medido en la referencia video_33: 2,7-3,8 px a 720 de ancho.
CORE_FRACTION = 0.005
_core_px = 3.6


def set_resolution(frame_width: int) -> None:
    """El motor la llama por fotograma: el núcleo depende de la resolución, no del tamaño del cuerpo."""
    global _core_px
    _core_px = max(frame_width * CORE_FRACTION, 1.5)


# Halo de los neones que van sobre la cara (máscaras, toon, gafas, el león): con el halo entero,
# muchos trazos juntos sobre la cara la lavan de luz y la arruinan.
FACE_HALO = 0.3


def neon_layers(curve: np.ndarray, color: np.ndarray, width: float, alpha: float, core_scale: float = 1.0, halo: float = 1.0) -> list:
    """Un tubo de neón como el de las referencias de baile: filamento blanco y el color en el halo.

    - Núcleo blanco de grosor fijo por resolución (90% de opacidad: el blanco puro satura).
    - Borde de color nítido de 2x el núcleo.
    - Dos halos desenfocados del color (como las box-shadow de un neón en CSS), de 3,5x y 8x el
      núcleo como mínimo. `width` solo controla hasta dónde se extiende el halo.
    Trazos de menos de 1,5 px (chispas diminutas) conservan su grosor propio.
    `halo` (0-1) atenúa y acorta los dos halos (FACE_HALO para lo que va sobre la cara).
    """
    color = np.asarray(color, dtype=np.float32)
    white = np.array([1.0, 1.0, 1.0], dtype=np.float32)
    core = (_core_px if width >= 1.5 else width) * core_scale
    spread = max(width, core)
    reach = 0.5 + 0.5 * halo
    return [
        (curve, color, max(spread * 3.0, core * 8.0) * reach, alpha * 0.35 * halo, max(spread * 1.8, core * 5.0) * reach),
        (curve, color, max(spread * 1.4, core * 3.5) * reach, alpha * 0.5 * (0.4 + 0.6 * halo), core * 1.5),
        (curve, color, core * 2.0, alpha * 0.85, core * 0.4),
        (curve, white, core, alpha * 0.9),
    ]


def _sliver(curve: np.ndarray, half: float) -> np.ndarray:
    """Contorno de una cinta por `curve` (de la cola a la cabeza): en punta en la cola, ancha cerca
    de la cabeza y redondeada en ella."""
    nrm = normals(curve)
    t = np.linspace(0.0, 1.0, len(curve))
    w = half * np.sin(np.pi * np.clip(t * 0.85 + 0.05, 0, 1)) ** 0.8 * (0.25 + 0.75 * t)
    return np.vstack([curve + nrm * w[:, None], (curve - nrm * w[:, None])[::-1]])


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
        strokes += neon_layers(piece, color, w, a, core_scale=0.45 + 0.55 * t)
    return strokes


CROSS_ANGLE = np.radians(70.0)


def crossed(curve: np.ndarray, angle: float = CROSS_ANGLE) -> list[np.ndarray]:
    """Dos arcos que se cruzan en el centro de la estela, sobre su eje principal.

    Se usa el eje principal y no la estela tal cual: si el brazo fue y volvió, la estela es un
    bucle estrecho y girarla dibuja un triángulo en vez de una cruz.
    """
    middle = curve.mean(axis=0)
    centered = curve - middle
    _, _, axes = np.linalg.svd(centered, full_matrices=False)
    axis = axes[0]
    reach = float(np.abs(centered @ axis).max())
    normal = np.array([-axis[1], axis[0]])
    t = np.linspace(-1.0, 1.0, 24)
    arcs = []
    for turn in (angle / 2, -angle / 2):
        rot = np.array([[np.cos(turn), -np.sin(turn)], [np.sin(turn), np.cos(turn)]])
        along, across = rot @ axis, rot @ normal
        arcs.append(middle + t[:, None] * along * reach + (1 - t**2)[:, None] * across * reach * 0.18)
    return arcs


def flame_tongues(curve: np.ndarray, width: float, color: np.ndarray, alpha: float, frame_index: int, boil_frames: int) -> list:
    """Lenguas cortas que salen del lado exterior del arco: el tajo parece de fuego."""
    if len(curve) < 6:
        return []
    rng = np.random.default_rng(frame_index // max(boil_frames, 1) + 7)
    nrm = normals(curve)
    # Lado exterior: hacia donde se abre la curva respecto a su centro.
    side = 1.0 if float(((curve - curve.mean(axis=0)) * nrm).sum()) >= 0 else -1.0
    strokes = []
    for index in range(2, len(curve) - 1, 3):
        t = index / (len(curve) - 1)
        length = width * float(rng.uniform(2.0, 5.0)) * t
        tangent = curve[index] - curve[index - 1]
        tangent = tangent / max(float(np.linalg.norm(tangent)), 1e-6)
        base = curve[index]
        tongue = np.stack([base, base + (nrm[index] * side * 0.8 - tangent * 0.6) * length])
        strokes += neon_layers(tongue, color, width * 0.5 * t, alpha * t)
    return strokes
