"""Partes del cuerpo encendidas y adornos dibujados (referencias de baile video_33 y video_34).

Dos pasadas, como lo haría un editor: una capa con `shapes: [no_outline]` y `blend: tint` tiñe
la parte; otra con `fill: 0` y `blend: add` traza el borde blanco con su halo encima.

body_glow: la parte del cuerpo que importa (brazo, piernas, torso, cabeza, pies, mano o el cuerpo
entero) se tiñe de color, su borde se traza con una línea casi blanca y un halo del mismo color
la rodea. La forma sale de la silueta real (Selfie Segmenter) recortada con cápsulas que siguen
los huesos de esa parte: el color queda pegado al borde, no es un óvalo genérico. Encima se
pueden dibujar abdominales y pectorales (torso) o el bíceps (brazo).

adornment: accesorios de neón anclados al cuerpo: collar, estrellas en el pecho, gorra, sombrero
vaquero, audífonos, aureola, corona, puntos en las rodillas y bandas en los tobillos.
"""

from __future__ import annotations

import zlib

import cv2
import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.duo_doodles import DOODLES, doodle
from vfxglow.engine.raster import fill_polygon, splat, stroke_batch
from vfxglow.engine.swoosh import neon_layers

TAU = 2.0 * np.pi
PARTS = ("left_arm", "right_arm", "arms", "legs", "torso", "head", "feet", "hands", "body", "jacket")
ADORNMENTS = DOODLES + ("necklace", "chain", "chest_stars", "belt", "metal_jacket", "cap", "cowboy_hat", "top_hat", "fedora", "party_hat", "witch_hat", "santa_hat", "flower_crown", "headphones", "halo", "crown", "knee_dots", "ankle_bands")

# Radio de cada cápsula en anchos de hombros.
_LIMB = {"arm": 0.22, "leg": 0.26, "foot": 0.18, "hand": 0.2}
# La silueta solo se usa si cubre al menos esta fracción de la cápsula (si no, es de otra persona).
_SILHOUETTE_MIN = 0.35


class Body:
    """Puntos de una persona en píxeles y su escala (ancho de hombros)."""

    def __init__(self, points: dict[str, np.ndarray], person: str | None) -> None:
        self.prefix = f"{person}:" if person else ""
        self.points = points

    def get(self, name: str) -> np.ndarray | None:
        return self.points.get(f"{self.prefix}{name}", self.points.get(name) if not self.prefix else None)

    def mid(self, a: str, b: str) -> np.ndarray | None:
        pa, pb = self.get(a), self.get(b)
        return (pa + pb) / 2 if pa is not None and pb is not None else None

    @property
    def scale(self) -> float | None:
        """Ancho de hombros, o 0,55 del largo del torso si es mayor: de perfil los hombros se
        juntan y todo lo dibujado se encogería (video_34, seg. 33)."""
        a, b = self.get("left_shoulder"), self.get("right_shoulder")
        if a is None or b is None:
            return None
        width = float(np.linalg.norm(a - b))
        hips = self.mid("left_hip", "right_hip")
        torso = float(np.linalg.norm((a + b) / 2 - hips)) if hips is not None else 0.0
        return max(width, 0.55 * torso, 12.0)

    def frame(self) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """(centro de hombros, eje derecha-imagen, eje hacia abajo del torso), ejes unitarios."""
        a, b = self.get("left_shoulder"), self.get("right_shoulder")
        if a is None or b is None:
            return None
        left, right = (a, b) if a[0] <= b[0] else (b, a)
        center = (left + right) / 2
        across = (right - left) / max(float(np.linalg.norm(right - left)), 1e-6)
        down = np.array([-across[1], across[0]])
        if down[1] < 0:
            down = -down
        hips = self.mid("left_hip", "right_hip")
        if hips is not None and np.linalg.norm(hips - center) > 1:
            down = (hips - center) / float(np.linalg.norm(hips - center))
        return center, across, down


def _people(track: FrameRecord | None, event: MotionEvent | None, style) -> list[str | None]:
    owner = None
    if event is not None:
        owner = event.attacker or (event.target.split(":", 1)[0] if event.target.startswith("person_") else None)
    if owner:
        people = [owner]
    elif track is not None and track.people:
        people = [p.person_id for p in track.people]
    else:
        people = [None]
    return [p for p in people if not style.people or p in style.people]


def _color(style, person: str | None) -> np.ndarray:
    index = int(person.rsplit("_", 1)[-1]) if person and person[-1].isdigit() else 0
    return np.asarray(style.colors[index % len(style.colors)], dtype=np.float32)


# ----- body_glow -----


def draw_body_glow(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    if envelope <= 0:
        return
    width = layer.shape[1]
    part = event.kind if event is not None and event.kind in PARTS else effect.target.id
    if effect.target.id == "jacket":
        # El saco es una prenda, no la parte que se movió: manda el objetivo del efecto.
        part = "jacket"
    if part not in PARTS:
        part = "body"
    silhouette = _silhouette(track, width, height)
    boil = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:bg:{frame_index // max(style.boil_frames, 1)}".encode()) & 0xFFFFFFFF)
    strokes = []
    for person in _people(track, event, style):
        body = Body(points, person)
        scale = body.scale
        if scale is None:
            continue
        region = part_mask(body, part, (height, width), scale)
        if region is None:
            continue
        if silhouette is not None:
            clipped = cv2.bitwise_and(region, silhouette)
            if clipped.sum() >= _SILHOUETTE_MIN * region.sum():
                region = clipped
        if "flap" in style.shapes:
            # Solo la solapa que se abre: el lado de la mano que la sostiene (video_34, seg. 10.3).
            region = flap_half(region, body, scale, event)
        contours = _outline(region)
        if not contours:
            continue
        color = _color(style, person)
        line = max(1.4, style.thickness * scale)
        for contour in contours:
            if "no_fill" not in style.shapes and style.fill > 0:
                # Ganancia < 1: en modo tint el color del relleno no debe leerse como "caliente".
                fill_polygon(layer, contour, color, style.fill * envelope, 0.9, feather=4.0)
            # lines_only: sin el contorno de la parte, solo las líneas interiores (abdominales...).
            if "no_outline" not in style.shapes and "lines_only" not in style.shapes:
                wobble = contour + boil.normal(0, scale * 0.004, contour.shape)
                if "hem" in style.shapes:
                    # Solo el faldón: el borde del saco por debajo de la cintura (video_34, seg. 18).
                    for piece in hem_pieces(wobble, body, scale):
                        strokes += neon_layers(piece, color, line, envelope)
                elif "wave" in style.shapes or "wave_down" in style.shapes:
                    # Solo tramos del contorno que recorren la parte como una onda (seg. 24).
                    for piece in wave_pieces(wobble, runtime.active_frames, style.trail_frames, "wave_down" in style.shapes):
                        strokes += neon_layers(piece, color, line, envelope)
                else:
                    strokes += neon_layers(np.vstack([wobble, wobble[:1]]), color, line, envelope)
        if "stitches" in style.shapes:
            # Costuras: guiones cortos verticales dentro de la prenda (video_34, seg. 10.3).
            key = event.start_frame if event is not None else 0
            strokes += [x for dash in stitch_dashes(region, scale, key) for x in neon_layers(dash, color, line * 0.7, envelope)]
        if "no_outline" in style.shapes:
            continue
        if "abs" in style.shapes and part in ("torso", "body"):
            # Por activación: qué dibujo de espalda y qué líneas sueltas (trazos parciales).
            key = event.start_frame if event is not None else frame_index // max(style.palette_every, 1)
            pick = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:torso:{key}".encode()) & 0xFFFFFFFF)
            drawing = reveal(torso_drawing(body, style.shapes, pick), body, event, runtime.active_frames)
            strokes += [s for line_ in drawing for s in neon_layers(line_, color, line * 0.8, envelope)]
        if "biceps" in style.shapes and part in ("left_arm", "right_arm", "arms"):
            sides = ("left", "right") if part == "arms" else (part.split("_")[0],)
            for side in sides:
                curve = biceps_line(body, side)
                if curve is not None:
                    strokes += neon_layers(curve, color, line * 0.8, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


def _silhouette(track: FrameRecord | None, width: int, height: int) -> np.ndarray | None:
    """Siluetas de todas las personas (o la más grande, en análisis anteriores)."""
    if track is None:
        return None
    outlines = track.body_contours or ([track.body_contour] if track.body_contour else [])
    if not outlines:
        return None
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [np.round(np.array(o) * [width, height]).astype(np.int32) for o in outlines], 1)
    return mask


def part_mask(body: Body, part: str, shape: tuple[int, int], scale: float) -> np.ndarray | None:
    """Máscara (0/1) de una parte del cuerpo hecha de cápsulas a lo largo de sus huesos."""
    mask = np.zeros(shape, np.uint8)
    drawn = False

    def capsule(names: tuple[str, ...], radius: float) -> None:
        nonlocal drawn
        pts = [body.get(n) for n in names]
        pts = [p for p in pts if p is not None]
        r = max(int(radius * scale), 2)
        for a, b in zip(pts, pts[1:]):
            cv2.line(mask, tuple(np.round(a).astype(int)), tuple(np.round(b).astype(int)), 1, thickness=2 * r, lineType=cv2.LINE_AA)
            drawn = True
        for p in pts:
            cv2.circle(mask, tuple(np.round(p).astype(int)), r, 1, -1, lineType=cv2.LINE_AA)
            drawn = True

    sides = ("left", "right")
    if part in ("left_arm", "right_arm", "arms", "body"):
        for side in sides if part in ("arms", "body") else (part.split("_")[0],):
            capsule((f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist", f"{side}_index"), _LIMB["arm"])
    if part in ("hands",):
        for side in sides:
            capsule((f"{side}_wrist", f"{side}_index", f"{side}_pinky", f"{side}_thumb"), _LIMB["hand"])
    if part in ("legs", "body"):
        for side in sides:
            capsule((f"{side}_hip", f"{side}_knee", f"{side}_ankle"), _LIMB["leg"])
    if part in ("feet", "body"):
        for side in sides:
            capsule((f"{side}_ankle", f"{side}_heel", f"{side}_foot_index"), _LIMB["foot"])
    if part == "jacket":
        # El saco: torso ancho (con el vuelo y la solapa abierta), hasta un poco bajo la cadera.
        # Recortado con la silueta sigue el borde real de la prenda (video_34, seg. 10 y 28).
        corners = [body.get(n) for n in ("left_shoulder", "right_shoulder", "right_hip", "left_hip")]
        if all(c is not None for c in corners):
            quad = np.array(corners, dtype=np.float64)
            center = quad.mean(axis=0)
            down = (quad[2] + quad[3]) / 2 - (quad[0] + quad[1]) / 2
            # Más ancho que el cuerpo: así el borde que queda es el de la silueta (el saco real).
            across = (quad[1] - quad[0]) / max(float(np.linalg.norm(quad[1] - quad[0])), 1e-6)
            quad = center + (quad - center) * np.array([1.0, 1.0])
            quad[[0, 3]] -= across * 0.9 * scale
            quad[[1, 2]] += across * 0.9 * scale
            quad[0] -= down * 0.08
            quad[1] -= down * 0.08
            quad[2] += down * 0.22
            quad[3] += down * 0.22
            cv2.fillPoly(mask, [np.round(quad).astype(np.int32)], 1, lineType=cv2.LINE_AA)
            drawn = True
    if part in ("torso", "body"):
        corners = [body.get(n) for n in ("left_shoulder", "right_shoulder", "right_hip", "left_hip")]
        if all(c is not None for c in corners):
            quad = np.array(corners)
            center = quad.mean(axis=0)
            quad = center + (quad - center) * 1.12
            cv2.fillPoly(mask, [np.round(quad).astype(np.int32)], 1, lineType=cv2.LINE_AA)
            drawn = True
    if part in ("head", "body"):
        nose = body.get("nose")
        ears = [body.get("left_ear"), body.get("right_ear")]
        if nose is not None:
            center = np.mean([p for p in ears if p is not None] + [nose], axis=0) - np.array([0.0, 0.12 * scale])
            cv2.ellipse(mask, tuple(np.round(center).astype(int)), (int(0.36 * scale), int(0.46 * scale)), 0, 0, 360, 1, -1, lineType=cv2.LINE_AA)
            drawn = True
    return mask if drawn else None


def flap_half(region: np.ndarray, body: Body, scale: float, event: MotionEvent | None) -> np.ndarray:
    frame = body.frame()
    if frame is None:
        return region
    center, across, _down = frame
    side = None
    if event is not None:
        side = next((s for s in ("left", "right") if s in event.target), None)
    if side is None:
        wrists = {s: body.get(f"{s}_wrist") for s in ("left", "right")}
        seen = {s: w for s, w in wrists.items() if w is not None}
        side = max(seen, key=lambda s: float(np.linalg.norm(seen[s] - center))) if seen else "left"
    shoulder = body.get(f"{side}_shoulder")
    sign = 1.0 if shoulder is None or float((shoulder - center) @ across) >= 0 else -1.0
    ys, xs = np.mgrid[0 : region.shape[0], 0 : region.shape[1]]
    along = (xs - center[0]) * across[0] * sign + (ys - center[1]) * across[1] * sign
    return (region & (along > 0.05 * scale)).astype(np.uint8)


def hem_pieces(contour: np.ndarray, body: Body, scale: float) -> list[np.ndarray]:
    """Tramos del contorno por debajo de la cintura (el faldón del saco)."""
    frame = body.frame()
    hips = body.mid("left_hip", "right_hip")
    if frame is None or hips is None:
        return [contour]
    down = frame[2]
    below = (contour - hips) @ down > -0.12 * scale
    pieces, start = [], None
    for k, flag in enumerate(np.append(below, False)):
        if flag and start is None:
            start = k
        elif not flag and start is not None:
            if k - start >= 4:
                pieces.append(contour[start:k])
            start = None
    return pieces


def stitch_dashes(region: np.ndarray, scale: float, key: int) -> list[np.ndarray]:
    """Guiones verticales cortos en una rejilla dentro de la región, la mitad al azar."""
    step = max(int(0.13 * scale), 4)
    length = 0.07 * scale
    inner = cv2.erode(region, np.ones((step, step), np.uint8))
    rng = np.random.default_rng(zlib.crc32(f"stitch:{key}".encode()) & 0xFFFFFFFF)
    dashes = []
    for y in range(step // 2, region.shape[0], step):
        for x in range((y // step % 2) * step // 2, region.shape[1], step):
            if inner[y, x] and rng.random() < 0.55:
                dashes.append(np.array([[x, y - length / 2], [x, y + length / 2]], dtype=np.float64))
    return dashes


def _outline(mask: np.ndarray) -> list[np.ndarray]:
    """Contornos exteriores suavizados (se descartan migas)."""
    smooth = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 3.0)
    solid = (smooth > 0.5).astype(np.uint8)
    contours, _ = cv2.findContours(solid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    total = float(solid.sum()) or 1.0
    out = []
    for contour in contours:
        if cv2.contourArea(contour) < 0.05 * total:
            continue
        pts = contour.reshape(-1, 2).astype(np.float64)
        out.append(pts[:: max(len(pts) // 160, 1)])
    return out


# Onda de contornos: bandas a la vez, alto de cada banda (fracción del alto de la parte).
WAVE_BANDS = 2
WAVE_HEIGHT = 0.14


def wave_pieces(contour: np.ndarray, frame: int, period: int, down: bool = False) -> list[np.ndarray]:
    """Tramos del contorno dentro de bandas horizontales que suben (o bajan) por la parte.

    Cada banda recorre la parte de punta a punta en `period` fotogramas; hay WAVE_BANDS a la
    vez, desfasadas. Lo que queda dentro de una banda se dibuja; el resto no (trazos parciales).
    """
    top, bottom = float(contour[:, 1].min()), float(contour[:, 1].max())
    extent = max(bottom - top, 1.0)
    half = extent * WAVE_HEIGHT / 2
    inside = np.zeros(len(contour), dtype=bool)
    for band in range(WAVE_BANDS):
        phase = ((frame / max(period, 1)) + band / WAVE_BANDS) % 1.0
        center = top + extent * phase if down else bottom - extent * phase
        inside |= np.abs(contour[:, 1] - center) <= half
    pieces, start = [], None
    for index, keep in enumerate(np.append(inside, False)):
        if keep and start is None:
            start = index
        elif not keep and start is not None:
            if index - start >= 3:
                pieces.append(contour[start:index])
            start = None
    return pieces


# Las líneas del torso aparecen de a poco en estos fotogramas (seg. 14: la energía pasa de la mano
# al pecho poco a poco).
REVEAL_FRAMES = 8


def reveal(lines: list[np.ndarray], body: Body, event: MotionEvent | None, frames_on: int) -> list[np.ndarray]:
    """Las primeras líneas en aparecer son las más cercanas a la mano que trae la energía (la del
    evento, si es un brazo); sin mano, de arriba hacia abajo."""
    if not lines or frames_on >= REVEAL_FRAMES:
        return lines
    source = None
    if event is not None and event.kind in ("left_arm", "right_arm"):
        source = body.get(f"{event.kind.split('_')[0]}_wrist")
    if source is not None:
        order = sorted(range(len(lines)), key=lambda i: float(np.min(np.linalg.norm(lines[i] - source, axis=1))))
    else:
        order = sorted(range(len(lines)), key=lambda i: float(lines[i][:, 1].min()))
    count = max(1, int(np.ceil(len(lines) * frames_on / REVEAL_FRAMES)))
    return [lines[i] for i in order[:count]]


FACING_FRONT = 0.2
FACING_BACK = -0.15
BADGES = ("radiation", "sun", "star", "heart", "spiral")


def facing(body: Body) -> str:
    """front, back o side. De frente, el hombro izquierdo de la persona queda a la derecha de la
    imagen; de espaldas, a la izquierda (video_33, seg. 18,8-20,2). Se mide en largos de torso."""
    left, right, hips = body.get("left_shoulder"), body.get("right_shoulder"), body.mid("left_hip", "right_hip")
    if left is None or right is None:
        return "front"
    center = (left + right) / 2
    torso = float(np.linalg.norm(hips - center)) if hips is not None else float(np.linalg.norm(left - right)) * 1.4
    dx = float(left[0] - right[0]) / max(torso, 1.0)
    if dx > FACING_FRONT:
        return "front"
    return "back" if dx < FACING_BACK else "side"


def torso_drawing(body: Body, shapes, rng: np.random.Generator) -> list[np.ndarray]:
    """El dibujo del torso según hacia dónde mira la persona (criterio P6).

    - De frente: pectorales y abdominales (`abs`).
    - De perfil: nada (los abdominales de lado no se leen).
    - De espaldas: músculos de la espalda (`back_lines`) o una figura de relleno en el centro
      de la espalda (`badge`: radiactivo, sol, estrella, corazón, espiral); se sortea entre los
      permitidos.
    Con `partial`, solo algunas líneas (40-70%), como hace la referencia en el seg. 14.
    """
    side = facing(body)
    if side == "side":
        return []
    if side == "back":
        allowed = [name for name in ("back_lines", "badge") if name in shapes] or ["back_lines", "badge"]
        choice = allowed[int(rng.integers(len(allowed)))]
        if choice == "badge":
            names = [name for name in BADGES if name in shapes] or list(BADGES)
            return badge_lines(body, names[int(rng.integers(len(names)))])
        lines = back_lines(body)
    else:
        lines = abs_lines(body)
    if "partial" in shapes and len(lines) > 3:
        keep = max(2, int(round(len(lines) * rng.uniform(0.4, 0.7))))
        lines = [lines[i] for i in sorted(rng.choice(len(lines), size=keep, replace=False))]
    return lines


def _torso_frame(body: Body):
    frame = body.frame()
    hips = body.mid("left_hip", "right_hip")
    if frame is None or hips is None:
        return None
    center, across, down = frame
    length = float(np.linalg.norm(hips - center))
    half = float(np.linalg.norm(body.get("left_shoulder") - body.get("right_shoulder"))) / 2

    def at(x: float, y: float) -> np.ndarray:
        return center + across * x * half + down * y * length

    return at, across, down, half, length


def back_lines(body: Body) -> list[np.ndarray]:
    """Columna, omóplatos y dorsales vistos desde atrás."""
    frame = _torso_frame(body)
    if frame is None:
        return []
    at = frame[0]
    t = np.linspace(0, 1, 10)
    lines = [np.array([at(0.02 * np.sin(6 * u), 0.08 + 0.8 * u) for u in t])]
    for side in (-1.0, 1.0):
        lines.append(np.array([at(side * (0.18 + 0.32 * np.sin(np.pi * u * 0.9)), 0.12 + 0.3 * u) for u in t]))
        lines.append(np.array([at(side * (0.62 - 0.3 * u), 0.42 + 0.45 * u) for u in t]))
    return lines


def badge_lines(body: Body, name: str) -> list[np.ndarray]:
    """Figura de relleno centrada en la espalda, en el plano del torso."""
    frame = _torso_frame(body)
    if frame is None:
        return []
    at, _, _, half, length = frame
    radius = 0.45  # en medios anchos de hombros
    cy = 0.42
    # x se mide en medios anchos de hombros e y en largos de torso: esto deja las figuras redondas.
    squash = half / max(length, 1.0)
    ring = np.linspace(0, 2 * np.pi, 49)

    def circle(r: float) -> np.ndarray:
        return np.array([at(r * np.cos(a), cy + r * np.sin(a) * squash) for a in ring])

    if name == "radiation":
        lines = [circle(radius), circle(radius * 0.18)]
        for k in range(3):
            a0 = -np.pi / 2 + k * 2 * np.pi / 3 - np.pi / 6
            arc = np.linspace(a0, a0 + np.pi / 3, 10)
            outer = [at(radius * 0.85 * np.cos(a), cy + radius * 0.85 * np.sin(a) * squash) for a in arc]
            inner = [at(radius * 0.28 * np.cos(a), cy + radius * 0.28 * np.sin(a) * squash) for a in arc[::-1]]
            lines.append(np.array(outer + inner + outer[:1]))
        return lines
    if name == "sun":
        lines = [circle(radius * 0.5)]
        for k in range(10):
            a = k * 2 * np.pi / 10
            lines.append(np.array([at(radius * 0.65 * np.cos(a), cy + radius * 0.65 * np.sin(a) * squash), at(radius * np.cos(a), cy + radius * np.sin(a) * squash)]))
        return lines
    if name == "star":
        angles = -np.pi / 2 + np.arange(11) * np.pi / 5
        radii = np.where(np.arange(11) % 2 == 0, radius, radius * 0.42)
        return [np.array([at(r * np.cos(a), cy + r * np.sin(a) * squash) for r, a in zip(radii, angles)])]
    if name == "heart":
        t = np.linspace(0, 2 * np.pi, 48)
        x = 16 * np.sin(t) ** 3 / 17
        y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)) / 17
        return [np.array([at(radius * xi, cy + radius * yi * squash) for xi, yi in zip(x, y)])]
    # espiral
    t = np.linspace(0, 3 * 2 * np.pi, 90)
    r = radius * t / t[-1]
    return [np.array([at(ri * np.cos(a), cy + ri * np.sin(a) * squash) for ri, a in zip(r, t)])]


def abs_lines(body: Body) -> list[np.ndarray]:
    """Pectorales, línea alba, tres pares de abdominales y oblicuos, en el marco del torso."""
    frame = body.frame()
    hips = body.mid("left_hip", "right_hip")
    if frame is None or hips is None:
        return []
    center, across, down = frame
    length = float(np.linalg.norm(hips - center))
    half = float(np.linalg.norm(body.get("left_shoulder") - body.get("right_shoulder"))) / 2

    def at(x: float, y: float) -> np.ndarray:
        return center + across * x * half + down * y * length

    lines = []
    for side in (-1.0, 1.0):
        t = np.linspace(0, 1, 12)
        pec = np.array([at(side * (0.05 + 0.65 * u), 0.14 + 0.2 * np.sin(np.pi * u) ** 0.8 + 0.05 * u) for u in t])
        lines.append(pec)
    lines.append(np.array([at(0, 0.38), at(0, 0.9)]))
    for y in (0.48, 0.63, 0.78):
        for side in (-1.0, 1.0):
            lines.append(np.array([at(side * 0.06, y), at(side * 0.22, y - 0.02), at(side * 0.34, y + 0.01)]))
    for side in (-1.0, 1.0):
        lines.append(np.array([at(side * 0.52, 0.4), at(side * 0.46, 0.65), at(side * 0.32, 0.92)]))
    return lines


def biceps_line(body: Body, side: str) -> np.ndarray | None:
    shoulder, elbow = body.get(f"{side}_shoulder"), body.get(f"{side}_elbow")
    if shoulder is None or elbow is None:
        return None
    d = elbow - shoulder
    n = np.array([-d[1], d[0]]) / max(float(np.linalg.norm(d)), 1e-6)
    t = np.linspace(0.2, 0.85, 12)[:, None]
    return shoulder + d * t + n * np.sin(np.pi * (t - 0.2) / 0.65) * float(np.linalg.norm(d)) * 0.16


# ----- adornos -----


def draw_adornment(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    if envelope <= 0:
        return
    names = [n for n in style.shapes if n in ADORNMENTS] or ["necklace"]
    key = event.start_frame if event is not None else frame_index // max(style.palette_every, 1)
    seed = zlib.crc32(f"{style.seed_offset}:adorn:{key}".encode()) & 0xFFFFFFFF
    shape = names[int(np.random.default_rng(seed).integers(0, len(names)))]
    grow = float(np.clip(runtime.active_frames / 5.0, 0.0, 1.0))
    strokes = []
    for person in _people(track, event, style):
        body = Body(points, person)
        scale = body.scale
        frame = body.frame()
        if scale is None or frame is None:
            continue
        color = _color(style, person)
        line = max(1.4, style.thickness * scale)
        for curve in adornment(shape, body, frame, scale, frame_index, seed, runtime, layer, color, envelope * grow, event):
            strokes += neon_layers(curve, color, line, envelope * grow)
    stroke_batch(layer, strokes, style.hdr_gain)


def _head(body: Body, scale: float, up: np.ndarray) -> np.ndarray | None:
    nose = body.get("nose")
    ears = [p for p in (body.get("left_ear"), body.get("right_ear")) if p is not None]
    if nose is None:
        return None
    return np.mean(ears + [nose], axis=0) + up * 0.1 * scale


def _ellipse(center: np.ndarray, rx: float, ry: float, across: np.ndarray, up: np.ndarray, a0: float = 0.0, a1: float = TAU, n: int = 40) -> np.ndarray:
    t = np.linspace(a0, a1, n)
    return center + np.cos(t)[:, None] * across * rx + np.sin(t)[:, None] * up * ry


def adornment(shape, body: Body, frame, scale, frame_index, seed, runtime, layer, color, alpha, event=None) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    head = _head(body, scale, up)
    if shape in DOODLES:
        return doodle(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event)
    if shape == "necklace":
        base = center + up * 0.06 * scale
        t = np.linspace(-1, 1, 24)
        chain = base + t[:, None] * across * 0.2 * scale + (1 - t**2)[:, None] * down * 0.32 * scale
        bottom = chain[len(chain) // 2]
        pendant = _ellipse(bottom + down * 0.07 * scale, 0.035 * scale, 0.05 * scale, across, up)
        return [chain, np.array([bottom, bottom + down * 0.025 * scale]), pendant]
    if shape == "chain":
        # Cadena de eslabones alternados (de frente y de canto) con un dije (seg. 10,9 y 14,9).
        base = center + up * 0.06 * scale
        t = np.linspace(-1, 1, 15)
        path = base + t[:, None] * across * 0.22 * scale + (1 - t**2)[:, None] * down * 0.34 * scale
        links = []
        for k, point in enumerate(path):
            nxt = path[min(k + 1, len(path) - 1)] - path[max(k - 1, 0)]
            along = nxt / max(float(np.linalg.norm(nxt)), 1e-6)
            normal = np.array([-along[1], along[0]])
            wide = 0.012 if k % 2 else 0.028
            links.append(_ellipse(point, 0.03 * scale, wide * scale, along, normal, n=14))
        bottom = path[len(path) // 2]
        pendant = np.array([bottom, bottom + down * 0.06 * scale - across * 0.04 * scale, bottom + down * 0.12 * scale, bottom + down * 0.06 * scale + across * 0.04 * scale, bottom])
        return [*links, pendant]
    if shape == "belt":
        # Cinturón de metal: banda en la cadera, hebilla y un destello que la recorre (seg. 28).
        hips = body.mid("left_hip", "right_hip")
        if hips is None:
            return []
        from vfxglow.engine.burst import sparkle

        waist = hips + up * 0.08 * scale
        top = _ellipse(waist, 0.62 * scale, 0.07 * scale, across, up, np.pi, TAU, 24)
        bottom = _ellipse(waist - up * 0.1 * scale, 0.62 * scale, 0.07 * scale, across, up, np.pi, TAU, 24)
        buckle = _ellipse(waist - up * 0.05 * scale + down * 0.07 * scale, 0.09 * scale, 0.06 * scale, across, up, n=5)
        # El brillo recorre la banda de un lado al otro (como el metal al girar).
        u = (frame_index % 30) / 30
        glint = top[int(u * (len(top) - 1))]
        return [top, bottom, np.vstack([buckle, buckle[:1]]), sparkle(glint, 0.09 * scale)]
    if shape == "metal_jacket":
        from vfxglow.engine.jacket import metal_jacket

        return metal_jacket(body, frame, scale, layer, alpha, facing(body) == "back")
    if shape == "chest_stars":
        from vfxglow.engine.burst import sparkle

        rng = np.random.default_rng(seed)
        stars = []
        for k in range(int(rng.integers(3, 6))):
            pos = center + across * rng.uniform(-0.5, 0.5) * scale + down * rng.uniform(0.15, 0.7) * scale
            twinkle = 0.6 + 0.4 * np.sin(frame_index * 0.5 + k * 1.7)
            stars.append(sparkle(pos, scale * float(rng.uniform(0.07, 0.13)) * twinkle))
        return stars
    if shape == "knee_dots":
        for side in ("left", "right"):
            knee = body.get(f"{side}_knee")
            if knee is not None:
                # Medido en video_34 (seg. 24,5): núcleo blanco de ~0,12 hombros y halo del color.
                splat(layer, float(knee[0]), float(knee[1]), scale * 0.12, np.array([1.0, 1.0, 1.0], np.float32) * 1.6, alpha, runtime.kernels)
                splat(layer, float(knee[0]), float(knee[1]), scale * 0.24, color * 1.4, alpha * 0.5, runtime.kernels)
        return []
    if shape == "ankle_bands":
        bands = []
        for side in ("left", "right"):
            knee, ankle = body.get(f"{side}_knee"), body.get(f"{side}_ankle")
            if knee is None or ankle is None:
                continue
            shin = (ankle - knee) / max(float(np.linalg.norm(ankle - knee)), 1e-6)
            normal = np.array([-shin[1], shin[0]])
            # Una banda ancha y gruesa en el tobillo, rellena de blanco (video_34, seg. 33,5).
            mid = ankle - shin * 0.08 * scale
            half_w, half_h = normal * 0.16 * scale, shin * 0.07 * scale
            quad = np.array([mid - half_w - half_h, mid + half_w - half_h, mid + half_w + half_h, mid - half_w + half_h])
            fill_polygon(layer, quad, np.ones(3, np.float32) * 1.3, alpha, 1.0, feather=2.0)
            bands.append(np.vstack([quad, quad[:1]]))
        return bands
    if head is None:
        return []
    if shape == "halo":
        return [_ellipse(head + up * 0.62 * scale, 0.28 * scale, 0.07 * scale, across, up)]
    if shape == "crown":
        base = head + up * 0.45 * scale
        xs = np.linspace(-0.26, 0.26, 9)
        ys = np.where(np.arange(9) % 2 == 0, 0.0, 0.22)
        ys[4] = 0.3
        crown = np.array([base + across * x * scale + up * y * scale for x, y in zip(xs, ys)])
        return [crown, np.array([crown[0], crown[-1]])]
    if shape == "headphones":
        arc = _ellipse(head + up * 0.05 * scale, 0.4 * scale, 0.5 * scale, across, up, 0.0, np.pi, 24)
        cups = [_ellipse(head + across * side * 0.4 * scale - up * 0.05 * scale, 0.07 * scale, 0.12 * scale, across, up) for side in (-1, 1)]
        return [arc, *cups]
    if shape == "cap":
        dome = _ellipse(head + up * 0.28 * scale, 0.36 * scale, 0.3 * scale, across, up, 0.0, np.pi, 24)
        brim_start = head + up * 0.28 * scale + across * 0.36 * scale
        brim = np.array([dome[-1], dome[0], brim_start + across * 0.28 * scale - up * 0.04 * scale])
        return [np.vstack([dome, dome[:1]]), brim]
    if shape == "witch_hat":
        band = head + up * 0.36 * scale
        brim = _ellipse(band, 0.6 * scale, 0.1 * scale, across, up)
        tip = band + up * 0.85 * scale + across * 0.25 * scale
        cone = np.array([band - across * 0.28 * scale, band - across * 0.1 * scale + up * 0.45 * scale, tip, band + across * 0.08 * scale + up * 0.4 * scale, band + across * 0.28 * scale])
        stripe = np.array([band - across * 0.26 * scale + up * 0.08 * scale, band + across * 0.26 * scale + up * 0.08 * scale])
        return [brim, cone, stripe]
    if shape == "santa_hat":
        band = head + up * 0.36 * scale
        trim = _ellipse(band, 0.36 * scale, 0.08 * scale, across, up)
        tip = band + up * 0.5 * scale + across * 0.45 * scale
        body = np.array([band - across * 0.32 * scale, band - across * 0.05 * scale + up * 0.5 * scale, tip, band + across * 0.32 * scale])
        pompom = _ellipse(tip, 0.08 * scale, 0.08 * scale, across, up)
        return [trim, body, pompom]
    if shape == "flower_crown":
        band = head + up * 0.4 * scale
        flowers = []
        for k, x in enumerate(np.linspace(-0.32, 0.32, 5)):
            center_f = band + across * x * scale + up * 0.04 * scale * np.cos(x * 4)
            r = (0.08 if k % 2 == 0 else 0.06) * scale
            flowers.append(_ellipse(center_f, r * 0.4, r * 0.4, across, up))
            for a in np.linspace(0, TAU, 6, endpoint=False):
                petal = center_f + (across * np.cos(a) + up * np.sin(a)) * r
                flowers.append(_ellipse(petal, r * 0.35, r * 0.35, across, up, n=10))
        return flowers
    if shape == "top_hat":
        band = head + up * 0.36 * scale
        brim = _ellipse(band, 0.42 * scale, 0.07 * scale, across, up)
        tube = np.array([band - across * 0.24 * scale, band - across * 0.24 * scale + up * 0.55 * scale, band + across * 0.24 * scale + up * 0.55 * scale, band + across * 0.24 * scale])
        stripe = np.array([band - across * 0.24 * scale + up * 0.1 * scale, band + across * 0.24 * scale + up * 0.1 * scale])
        return [brim, tube, stripe]
    if shape == "fedora":
        band = head + up * 0.36 * scale
        brim = _ellipse(band, 0.5 * scale, 0.09 * scale, across, up)
        crown = np.array([band - across * 0.3 * scale, band - across * 0.24 * scale + up * 0.3 * scale, band - across * 0.05 * scale + up * 0.24 * scale,
                          band + across * 0.05 * scale + up * 0.3 * scale, band + across * 0.24 * scale + up * 0.28 * scale, band + across * 0.3 * scale])
        return [brim, crown]
    if shape == "party_hat":
        from vfxglow.engine.burst import sparkle

        band = head + up * 0.36 * scale
        cone = np.array([band - across * 0.24 * scale, band + up * 0.62 * scale, band + across * 0.24 * scale, band - across * 0.24 * scale])
        stripes = [np.array([band - across * (0.24 - 0.08 * k) * scale + up * 0.21 * k * scale, band + across * (0.24 - 0.08 * k) * scale + up * 0.21 * k * scale]) for k in (1, 2)]
        return [cone, *stripes, sparkle(band + up * 0.66 * scale, 0.07 * scale)]
    if shape == "cowboy_hat":
        band = head + up * 0.38 * scale
        brim = _ellipse(band, 0.62 * scale, 0.1 * scale, across, up)
        crown = np.array([
            band - across * 0.28 * scale,
            band - across * 0.26 * scale + up * 0.36 * scale,
            band + up * 0.3 * scale,
            band + across * 0.26 * scale + up * 0.36 * scale,
            band + across * 0.28 * scale,
        ])
        return [brim, crown]
    return []
