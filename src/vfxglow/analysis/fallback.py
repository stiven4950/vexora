"""Respaldo para fotogramas sin malla facial.

Con la cara cubierta por completo (maquillaje, máscara) la malla y la pose fallan, pero la
silueta sigue: el Selfie Segmenter de MediaPipe (CPU) la recorta casi siempre. De ella sale
el contorno de la cabeza. Un lente o un ojo pintado de blanco es el punto más claro dentro
de esa cabeza en los tres canales a la vez; se publica como `eye_glint`.

No se infiere el otro ojo ni se sostiene nada entre fotogramas: lo que no se ve no se dibuja.
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.analysis.schema import FrameRecord, Landmark

# Fracción superior de la silueta que se toma como cabeza.
HEAD_BAND = 0.45
# Un lente claro tiene R, G y B altos; la piel o el naranja tienen al menos un canal bajo.
GLINT_MIN_CHANNEL = 140
GLINT_AREA = (10, 3000)
CONTOUR_POINTS = 48
# Peso del fotograma nuevo en la media del contorno, y salto medio (normalizado) que la reinicia.
SMOOTH_ALPHA = 0.45
SMOOTH_RESET = 0.06
# Un contorno con área fuera de este rango respecto a la mediana del tramo es un fallo del segmentador.
AREA_RANGE = (0.75, 1.3)
# Fotogramas que un contorno bueno puede sustituir a uno malo, desplazado con el ojo claro.
HOLD_FRAMES = 30


class FaceFallback:
    def __init__(self, model_path: str) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self._segmenter = vision.ImageSegmenter.create_from_options(
            vision.ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_path=model_path),
                output_confidence_masks=True,
            )
        )

    def mask(self, frame_bgr: np.ndarray) -> np.ndarray:
        import mediapipe as mp

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self._segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        return (np.squeeze(result.confidence_masks[0].numpy_view()) > 0.5).astype(np.uint8)

    def apply(self, record: FrameRecord, frame_bgr: np.ndarray, mask: np.ndarray | None = None) -> None:
        mask = self.mask(frame_bgr) if mask is None else mask
        contour, glint = locate_head(frame_bgr, mask)
        record.head_contour = contour
        record.fallback = [glint] if glint is not None else []

    def close(self) -> None:
        self._segmenter.close()


BODY_POINTS = 140


def body_outline(mask: np.ndarray) -> list[tuple[float, float]] | None:
    """Contorno cerrado de la silueta más grande, con huecos rellenos, normalizado."""
    height, width = mask.shape[:2]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count < 2:
        return None
    body = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[body, cv2.CC_STAT_AREA] < 0.01 * width * height:
        return None
    solid = _solid((labels == body).astype(np.uint8), width)
    contours, _ = cv2.findContours(solid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    outline = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    outline = resample(np.vstack([outline, outline[:1]]), BODY_POINTS)
    return [(float(x) / width, float(y) / height) for x, y in outline]


def body_outlines(mask: np.ndarray) -> list[list[tuple[float, float]]]:
    """Contornos de todas las siluetas de al menos el 1% del cuadro (cada persona separada)."""
    height, width = mask.shape[:2]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    out = []
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < 0.01 * width * height:
            continue
        solid = _solid((labels == label).astype(np.uint8), width)
        contours, _ = cv2.findContours(solid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        outline = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
        outline = resample(np.vstack([outline, outline[:1]]), BODY_POINTS)
        out.append([(float(x) / width, float(y) / height) for x, y in outline])
    return out


def locate_head(frame_bgr: np.ndarray, mask: np.ndarray) -> tuple[list[tuple[float, float]] | None, Landmark | None]:
    height, width = mask.shape[:2]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count < 2:
        return None, None
    body_id = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[body_id, cv2.CC_STAT_AREA] < 0.01 * width * height:
        return None, None
    body = _solid((labels == body_id).astype(np.uint8), width)
    rows = np.nonzero(body.any(axis=1))[0]
    top, span = int(rows[0]), int(rows[-1] - rows[0] + 1)
    bottom = _neck_row(body, top, span)
    head = np.zeros_like(body)
    head[top:bottom] = body[top:bottom]
    contours, _ = cv2.findContours(head, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None, None
    outline = _open_at_cut(max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64), bottom)
    if len(outline) < 4:
        return None, None
    outline = resample(outline, CONTOUR_POINTS)
    contour = [(float(x) / width, float(y) / height) for x, y in outline]
    return contour, _glint(frame_bgr, head, top, bottom, width, height)


def _solid(body: np.ndarray, width: int) -> np.ndarray:
    """Cierra las grietas y rellena los huecos: las franjas oscuras del maquillaje no son borde."""
    size = max(3, int(width * 0.03)) | 1
    body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    contours, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solid = np.zeros_like(body)
    cv2.drawContours(solid, contours, -1, 1, thickness=cv2.FILLED)
    return solid


def _neck_row(body: np.ndarray, top: int, span: int) -> int:
    """Fila más angosta entre la cabeza y los hombros. Si no hay estrechamiento claro, una banda fija."""
    widths = body[top : top + span].sum(axis=1).astype(np.float64)
    widths = np.convolve(widths, np.ones(9) / 9, mode="same")
    head_w = widths[: max(int(span * 0.5), 1)].max()
    start = int(np.argmax(widths >= 0.6 * head_w)) + int(span * 0.1)
    stop = int(span * 0.65)
    if stop - start < 5:
        return top + max(int(span * HEAD_BAND), 1)
    neck = start + int(np.argmin(widths[start:stop]))
    if widths[neck] > 0.85 * head_w:
        return top + max(int(span * HEAD_BAND), 1)
    return top + neck


def resample(curve: np.ndarray, count: int) -> np.ndarray:
    """`count` puntos equiespaciados por longitud de arco: el punto i es comparable entre fotogramas."""
    seg = np.linalg.norm(np.diff(curve, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    if acc[-1] <= 0:
        return np.repeat(curve[:1], count, axis=0)
    targets = np.linspace(0.0, acc[-1], count)
    return np.stack([np.interp(targets, acc, curve[:, 0]), np.interp(targets, acc, curve[:, 1])], axis=1)


def _open_at_cut(outline: np.ndarray, bottom: int) -> np.ndarray:
    """Quita el borde horizontal del recorte (el cuello) y deja la curva abierta de un lado al otro."""
    cut = outline[:, 1] >= bottom - 2
    if not cut.any() or cut.all():
        return outline
    start = int(np.nonzero(cut)[0][-1]) + 1
    rolled = np.roll(outline, -start, axis=0)
    return rolled[~(rolled[:, 1] >= bottom - 2)]


def _glint(frame_bgr: np.ndarray, head: np.ndarray, top: int, bottom: int, width: int, height: int) -> Landmark | None:
    brightest = frame_bgr[top:bottom].min(axis=2)
    spots = ((brightest >= GLINT_MIN_CHANNEL) & (head[top:bottom] > 0)).astype(np.uint8)
    count, _, stats, centers = cv2.connectedComponentsWithStats(spots)
    best = None
    for k in range(1, count):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if GLINT_AREA[0] <= area <= GLINT_AREA[1] and (best is None or area > best[0]):
            best = (area, centers[k])
    if best is None:
        return None
    area, (x, y) = best
    return Landmark(name="eye_glint", x=float(x) / width, y=float(y + top) / height, c=float(min(1.0, area / 60.0)))


def stabilize_heads(frames: list[FrameRecord], width: int, height: int) -> None:
    """Limpia los contornos de cabeza de cada tramo continuo de respaldo.

    El segmentador a veces recorta media cabeza o se lleva el humo. Esas formas se detectan
    por área contra la mediana del tramo y se sustituyen por el contorno bueno más cercano,
    desplazado lo que se movió `eye_glint`. Sin ojo claro que guíe el desplazamiento no se
    inventa nada: el fotograma queda sin contorno. Después se suaviza en el tiempo.
    """
    for run in _runs(frames):
        scale = np.array([width, height], dtype=np.float64)
        shapes = {r.frame: np.asarray(r.head_contour) for r in run}
        areas = {frame: _area(shape * scale) for frame, shape in shapes.items()}
        median = float(np.median(list(areas.values())))
        good = {f for f, a in areas.items() if AREA_RANGE[0] * median <= a <= AREA_RANGE[1] * median}
        glints = {r.frame: np.array([r.fallback[0].x, r.fallback[0].y]) for r in run if r.fallback}
        previous: np.ndarray | None = None
        for record in run:
            frame = record.frame
            if frame in good:
                current = shapes[frame]
            else:
                current = _borrow(frame, good, shapes, glints)
            if current is None:
                record.head_contour = None
                previous = None
                continue
            if previous is not None and float(np.abs(current - previous).mean()) < SMOOTH_RESET:
                current = previous * (1 - SMOOTH_ALPHA) + current * SMOOTH_ALPHA
            previous = current
            record.head_contour = [(float(x), float(y)) for x, y in current]


def _runs(frames: list[FrameRecord]) -> list[list[FrameRecord]]:
    runs: list[list[FrameRecord]] = []
    for record in frames:
        if not record.head_contour:
            continue
        if runs and runs[-1][-1].frame == record.frame - 1:
            runs[-1].append(record)
        else:
            runs.append([record])
    return runs


def _borrow(frame: int, good: set[int], shapes: dict[int, np.ndarray], glints: dict[int, np.ndarray]) -> np.ndarray | None:
    if frame not in glints:
        return None
    for distance in range(1, HOLD_FRAMES + 1):
        for source in (frame - distance, frame + distance):
            if source in good and source in glints:
                return shapes[source] + (glints[frame] - glints[source])
    return None


def _area(points: np.ndarray) -> float:
    x, y = points[:, 0], points[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))
