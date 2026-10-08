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
from vfxglow.engine.raster import fill_polygon, splat, stroke_batch
from vfxglow.engine.swoosh import neon_layers

TAU = 2.0 * np.pi
PARTS = ("left_arm", "right_arm", "arms", "legs", "torso", "head", "feet", "hands", "body")
ADORNMENTS = ("necklace", "chest_stars", "cap", "cowboy_hat", "headphones", "halo", "crown", "knee_dots", "ankle_bands")

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
        a, b = self.get("left_shoulder"), self.get("right_shoulder")
        if a is None or b is None:
            return None
        return max(float(np.linalg.norm(a - b)), 12.0)

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
    if event is not None and event.attacker:
        people = [event.attacker]
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
        contours = _outline(region)
        if not contours:
            continue
        color = _color(style, person)
        line = max(1.4, style.thickness * scale)
        for contour in contours:
            if "no_fill" not in style.shapes and style.fill > 0:
                # Ganancia < 1: en modo tint el color del relleno no debe leerse como "caliente".
                fill_polygon(layer, contour, color, style.fill * envelope, 0.9, feather=4.0)
            if "no_outline" not in style.shapes:
                wobble = contour + boil.normal(0, scale * 0.004, contour.shape)
                strokes += neon_layers(np.vstack([wobble, wobble[:1]]), color, line, envelope)
        if "no_outline" in style.shapes:
            continue
        if "abs" in style.shapes and part in ("torso", "body"):
            strokes += [s for line_ in abs_lines(body) for s in neon_layers(line_, color, line * 0.8, envelope)]
        if "biceps" in style.shapes and part in ("left_arm", "right_arm", "arms"):
            sides = ("left", "right") if part == "arms" else (part.split("_")[0],)
            for side in sides:
                curve = biceps_line(body, side)
                if curve is not None:
                    strokes += neon_layers(curve, color, line * 0.8, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


def _silhouette(track: FrameRecord | None, width: int, height: int) -> np.ndarray | None:
    if track is None or not track.body_contour:
        return None
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [np.round(np.array(track.body_contour) * [width, height]).astype(np.int32)], 1)
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
        for curve in adornment(shape, body, frame, scale, frame_index, seed, runtime, layer, color, envelope * grow):
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


def adornment(shape, body: Body, frame, scale, frame_index, seed, runtime, layer, color, alpha) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    head = _head(body, scale, up)
    if shape == "necklace":
        base = center + up * 0.06 * scale
        t = np.linspace(-1, 1, 24)
        chain = base + t[:, None] * across * 0.2 * scale + (1 - t**2)[:, None] * down * 0.32 * scale
        bottom = chain[len(chain) // 2]
        pendant = _ellipse(bottom + down * 0.07 * scale, 0.035 * scale, 0.05 * scale, across, up)
        return [chain, np.array([bottom, bottom + down * 0.025 * scale]), pendant]
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
                splat(layer, float(knee[0]), float(knee[1]), scale * 0.07, np.array([1.0, 1.0, 1.0], np.float32) * 1.6, alpha, runtime.kernels)
                splat(layer, float(knee[0]), float(knee[1]), scale * 0.16, color * 1.4, alpha * 0.5, runtime.kernels)
        return []
    if shape == "ankle_bands":
        bands = []
        for side in ("left", "right"):
            knee, ankle = body.get(f"{side}_knee"), body.get(f"{side}_ankle")
            if knee is None or ankle is None:
                continue
            shin = (ankle - knee) / max(float(np.linalg.norm(ankle - knee)), 1e-6)
            normal = np.array([-shin[1], shin[0]])
            for offset in (0.04, 0.12):
                mid = ankle - shin * offset * scale
                bands.append(np.array([mid - normal * 0.11 * scale, mid + normal * 0.11 * scale]))
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
