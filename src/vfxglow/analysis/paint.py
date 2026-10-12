"""Pintura sobre la cara y la obra terminada (referencia video_2, ver docs/referencias/video_2.md).

detect_paint: dónde aparece pintura nueva y cuándo.
- Se trabaja en "coordenadas de la cara": cada fotograma se alinea al primero con la malla facial
  (afín parcial), así que mover la cabeza no parece pintura.
- Un píxel de la cara es "no piel" si su color (a, b de Lab) se aleja de la piel de la zona aún sin
  pintar en ese fotograma, o si es muy oscuro (pintura negra). La mano detectada se excluye.
- Nace pintura en un píxel cuando es "no piel" al menos HOLD fotogramas seguidos y además lo sigue
  siendo en la mayor parte del segundo siguiente (LOOKAHEAD_S, STAY). Así la mano y el pincel, que
  pasan, no cuentan, y el mango del pincel quieto mientras se pintan detalles tampoco (además se
  descartan las manchas largas y rectas que salen del borde de la cara).
- Lo que ya estaba en los primeros fotogramas (cejas, labios, pintura previa) no es nuevo.

Por fotograma se guarda el contorno de la pintura reciente (nacida hace menos de RECENT
fotogramas) con la edad de cada punto, y la punta: donde nace pintura ahora.

detect_accents: en la escena de la obra terminada (sin cara humana: una máscara, la calabaza), las
líneas oscuras pintadas sobre el objeto de color, solo en la cabeza, clasificadas por zona (ojos,
estrías, nariz, boca) según su lugar en la caja de la cabeza.
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.tool import tool_tip
from vfxglow.analysis.names import CHEEKS, FACE_FEATURES, FACE_OVAL
from vfxglow.analysis.schema import FrameRecord
from vfxglow.analysis.shapes import fit_shape, shape_points

log = logging.getLogger("vfxglow.paint")

WORK = (360, 640)  # resolución de trabajo (ancho, alto) para un cuadro vertical
CHROMA = 6.0  # distancia de color a la piel, en desviaciones robustas
DARK_L = 60  # L (0-255) por debajo de esto es pintura negra
HOLD = 4
LOOKAHEAD_S = 1.0
STAY = 0.7
PREEXISTING = 2  # fotogramas iniciales cuyo "no piel" ya estaba
RECENT = 24
TIP_FRAMES = 6
TRAIL = 14
REFERENCE_FRAMES = 8
CONTACT = 4  # px alrededor de la punta en que tiene que haber pintura
MAX_JUMP = 0.08  # salto máximo de la punta entre fotogramas, en anchos del cuadro
REFERENCE_DELTA = 14.0  # distancia Lab (L a la mitad) a la piel limpia de ese píxel  # fotogramas de recorrido de la punta del pincel que forman la línea fina
MIN_BLOB = 25
MIN_DARK_BLOB = 8  # píxeles (a la resolución de trabajo) fuera del borde viejo para ser trazo nuevo  # fotogramas en que un trazo nuevo sigue contando como reciente
MIN_FRAMES = 15  # fotogramas con pintura nueva para considerar que el video es de pintura
FOREHEAD = 1.35  # cuánto se estira el óvalo de la malla hacia la frente


def _face_points(record: FrameRecord, width: int, height: int) -> dict[int, np.ndarray]:
    return {int(lm.name[5:]): np.array([lm.x * width, lm.y * height]) for lm in record.face or [] if lm.name[5:].isdigit()}


def _poly(points: dict[int, np.ndarray], indices) -> np.ndarray:
    return np.array([points[i] for i in indices if i in points], np.float32)


class _FaceSpace:
    """Zona de la cara del primer fotograma con malla y el modelo de piel inicial."""

    def __init__(self, frame: np.ndarray, points: dict[int, np.ndarray]) -> None:
        h, w = frame.shape[:2]
        self.ref = points
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
        cheeks = np.zeros((h, w), np.uint8)
        for chain in CHEEKS:
            pts = _poly(points, chain)
            if len(pts) >= 3:
                cv2.fillConvexPoly(cheeks, cv2.convexHull(pts).astype(np.int32), 1)
        sample = lab[cheeks > 0] if cheeks.any() else lab.reshape(-1, 3)
        self.skin = np.median(sample, axis=0)
        self.spread = np.median(np.abs(sample - self.skin), axis=0) + 1.5
        oval = _poly(points, FACE_OVAL)
        center = oval.mean(axis=0)
        tall = oval.copy()
        upper = tall[:, 1] < center[1]
        tall[upper, 1] = center[1] + (tall[upper, 1] - center[1]) * FOREHEAD
        region = np.zeros((h, w), np.uint8)
        cv2.fillPoly(region, [tall.astype(np.int32)], 1)
        region = cv2.erode(region, np.ones((13, 13), np.uint8))
        eyes = np.zeros((h, w), np.uint8)
        for name in ("left_eye", "right_eye"):
            pts = _poly(points, FACE_FEATURES[name])
            if len(pts) >= 3:
                cv2.fillPoly(eyes, [pts.astype(np.int32)], 1)
        self.region = (region > 0) & (cv2.dilate(eyes, np.ones((7, 7), np.uint8)) == 0)
        self.border = (cv2.dilate(region, np.ones((9, 9), np.uint8)) > 0) & ~(cv2.erode(region, np.ones((9, 9), np.uint8)) > 0)

    def align(self, points: dict[int, np.ndarray]) -> np.ndarray | None:
        common = [k for k in points if k in self.ref]
        if len(common) < 10:
            return None
        matrix, _ = cv2.estimateAffinePartial2D(np.array([points[k] for k in common], np.float32), np.array([self.ref[k] for k in common], np.float32))
        return matrix


def _hand_mask(record: FrameRecord, matrix: np.ndarray, shape, width: int, height: int) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    for hand in (record.left_hand, record.right_hand):
        if hand is None or not hand.landmarks:
            continue
        pts = np.array([[lm.x * width, lm.y * height] for lm in hand.landmarks], np.float32)
        pts = cv2.transform(pts[None], matrix)[0]
        cv2.fillConvexPoly(mask, cv2.convexHull(pts).astype(np.int32), 1)
    return cv2.dilate(mask, np.ones((25, 25), np.uint8)) > 0


def _drop_tools(new: np.ndarray, border: np.ndarray) -> np.ndarray:
    """Un trozo largo y recto que entra desde el borde de la cara es el mango del pincel."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(new.astype(np.uint8))
    for k in range(1, count):
        piece = labels == k
        if not (piece & border).any() or stats[k, 4] < 30:
            continue
        ys, xs = np.nonzero(piece)
        (_, _), (a, b), _ = cv2.minAreaRect(np.stack([xs, ys], axis=1).astype(np.float32))
        if max(a, b) > 6 * max(min(a, b), 1.0):
            new[piece] = False
    return new


def _real_strokes(new: np.ndarray, existing: np.ndarray, min_blob: int = 25) -> np.ndarray:
    """Lo nuevo que vale como trazo: manchas de al menos MIN_BLOB píxeles que no sean solo el
    borde de la pintura vieja corrido un píxel (la luz cambia y el borde "crece"). El resto se
    marca como pintura vieja para que no vuelva a contar."""
    ring = cv2.dilate(existing.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(new.astype(np.uint8))
    keep = np.zeros_like(new)
    for k in range(1, count):
        piece = labels == k
        beyond = int((piece & ~ring).sum())
        if beyond >= min_blob:
            keep |= piece
    return keep


def detect_paint(video_path: Path, frames: list[FrameRecord], fps: float, cuts: list[int] | None = None, tool: str = "model") -> dict[int, dict]:
    """{fotograma: {"strokes": [[(x, y, edad), ...], ...], "tip": (x, y) | None}} normalizado.

    Solo en la primera escena con cara: en un corte termina (la escena siguiente es otra cosa; en
    video_2 la malla "ve" una cara en la calabaza y la tomaría por pintura nueva)."""
    cuts = sorted(cuts or [])
    detector = None
    if tool == "model":
        try:
            from vfxglow.analysis.tool import ToolDetector

            detector = ToolDetector()
        except Exception as exc:  # sin transformers o sin red: se sigue con el movimiento
            log.warning("Detector de herramienta no disponible (%s); se usa el movimiento", exc)
    capture = cv2.VideoCapture(str(video_path))
    space: _FaceSpace | None = None
    look = max(int(LOOKAHEAD_S * fps), HOLD)
    buffer: deque = deque()  # (índice, máscara alineada, matriz)
    total: np.ndarray | None = None
    born: np.ndarray | None = None
    born_dark: np.ndarray | None = None
    painted: np.ndarray | None = None
    out: dict[int, dict] = {}
    births = 0
    first_face = 0
    brush: dict[int, tuple[float, float]] = {}
    previous: np.ndarray | None = None
    last_tip: tuple[int, np.ndarray] | None = None
    references: list[np.ndarray] = []
    reference: np.ndarray | None = None
    by_index = {record.frame: record for record in frames}

    def births_in(index: int, mask: np.ndarray, layer: int, ages: np.ndarray, min_blob: int) -> np.ndarray:
        """Nacimientos de una capa (0 = color, 1 = negro) decididos con los fotogramas siguientes."""
        future = [mask] + [m[layer] for _, m, _ in list(buffer)[:look] if m is not None]
        hold = np.logical_and.reduce(future[:HOLD]) if len(future) >= HOLD else np.zeros_like(mask)
        stay = np.mean(np.stack(future), axis=0)
        new = mask & hold & (stay >= STAY) & (ages > 10**8)
        new = _drop_tools(new, space.border)
        candidates = new
        new = _real_strokes(new, ages < 10**8, min_blob)
        ages[candidates & ~new] = -1000
        ages[new] = index
        return new

    def settle(entry) -> None:
        nonlocal births
        index, masks, matrix = entry
        if masks is None:
            return
        # La pintura negra va en su propia capa: se pinta encima del naranja ya "nacido" y en
        # líneas finas que el filtro del color descartaría.
        new = births_in(index, masks[0], 0, born, MIN_BLOB) | births_in(index, masks[1], 1, born_dark, MIN_DARK_BLOB)
        births += int(new.any())
        youngest = np.maximum(np.where(born < 10**8, born, -(10**6)), np.where(born_dark < 10**8, born_dark, -(10**6)))
        youngest[(born > 10**8) & (born_dark > 10**8)] = 10**9
        out[index] = _strokes(index, youngest, matrix, masks[0].shape)

    try:
        width_px = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 720
        height_px = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1280
        size = WORK if height_px >= width_px else (WORK[1], WORK[0])
        index = -1
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            index += 1
            if space is not None and any(first_face < cut <= index for cut in cuts):
                break
            record = by_index.get(index)
            mask, matrix = None, None
            if record is None or not record.face:
                previous = None
            if record is not None and record.face:
                small = cv2.resize(frame, size)
                points = _face_points(record, size[0], size[1])
                if space is None and len(points) > 60:
                    space = _FaceSpace(small, points)
                    first_face = index
                    shape = small.shape[:2]
                    born = np.full(shape, 10**9, np.int32)
                    born_dark = np.full(shape, 10**9, np.int32)
                    painted = np.zeros(shape, bool)
                if space is not None:
                    matrix = space.align(points)
            if matrix is not None:
                aligned = cv2.warpAffine(small, matrix, size)
                # La herramienta: lo que se mueve sobre la cara alineada (sin suponer su color).
                tip = None
                if detector is not None:
                    scale = np.array([frame.shape[1] / size[0], frame.shape[0] / size[1]])
                    found = detector.tip(frame, np.mean(list(points.values()), axis=0) * scale)
                    if found is not None:
                        tip = cv2.transform(np.array([[found / scale]], np.float32), matrix)[0, 0]
                elif previous is not None:
                    tip = tool_tip(previous, aligned, space.region)
                previous = aligned
                lab = cv2.cvtColor(aligned, cv2.COLOR_BGR2LAB).astype(np.float32)
                # Piel limpia de referencia por píxel: mediana de los primeros fotogramas (la mano
                # pasa y no queda en la mediana).
                if len(references) < REFERENCE_FRAMES:
                    references.append(lab)
                    reference = np.median(np.stack(references), axis=0)
                shift = np.median((lab - reference)[space.region & ~painted], axis=0) if (space.region & ~painted).sum() > 500 else np.zeros(3)
                changed = np.sqrt((((lab - shift) - reference) * [0.5, 1.0, 1.0]) ** 2).sum(axis=2) > REFERENCE_DELTA
                clean = space.region & ~painted
                skin = np.median(lab[clean], axis=0) if clean.sum() > 500 else space.skin
                chroma = np.sqrt(((lab[..., 1] - skin[1]) / space.spread[1]) ** 2 + ((lab[..., 2] - skin[2]) / space.spread[2]) ** 2)
                hand = _hand_mask(record, matrix, chroma.shape, size[0], size[1])
                # Pintura = distinto de la piel limpia de ese mismo punto Y con color que no es piel.
                color = changed & (chroma > CHROMA) & (lab[..., 0] >= DARK_L) & space.region & ~hand
                color = cv2.morphologyEx(color.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
                # El negro del borde de la cara es pelo o sombra, no pintura.
                dark = changed & (lab[..., 0] < DARK_L) & (reference[..., 0] > DARK_L + 20) & space.region & ~space.border & ~hand
                dark = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
                mask = (color, dark)
                # Contacto: la punta solo cuenta sobre pintura (la mano que pasa no pinta) y sin
                # saltar lejos de la punta anterior.
                if tip is not None:
                    x, y = int(tip[0]), int(tip[1])
                    near = (color | dark)[max(y - CONTACT, 0) : y + CONTACT + 1, max(x - CONTACT, 0) : x + CONTACT + 1]
                    last = last_tip if last_tip is not None and index - last_tip[0] <= 2 else None
                    steady = last is None or np.linalg.norm(tip - last[1]) < MAX_JUMP * size[0]
                    if near.any() and steady:
                        back = cv2.transform(np.array([[tip]], np.float32), cv2.invertAffineTransform(matrix))[0, 0]
                        brush[index] = (float(back[0] / size[0]), float(back[1] / size[1]))
                        last_tip = (index, tip)
                painted |= color | dark
                if index - first_face < PREEXISTING:
                    born[color] = -1000
                    born_dark[dark] = -1000
            buffer.append((index, mask, matrix))
            if len(buffer) > look:
                settle(buffer.popleft())
        while buffer:
            settle(buffer.popleft())
    finally:
        capture.release()
    if births < MIN_FRAMES:
        return {}
    _add_brush(out, brush)
    log.info("Pintura nueva en %d fotogramas; pincel sobre la cara en %d", births, len(brush))
    return {k: v for k, v in out.items() if v["strokes"] or v["tip"] or v.get("trail")}


def _add_brush(out: dict[int, dict], brush: dict[int, tuple[float, float]]) -> None:
    """Con el pincel a la vista, la punta es la suya; y el recorrido de la punta en los últimos
    TRAIL fotogramas seguidos es la línea fina que se está trazando (con su edad)."""
    for index, tip in brush.items():
        entry = out.setdefault(index, {"strokes": [], "tip": None})
        entry["tip"] = tip
        trail = []
        for back in range(TRAIL):
            point = brush.get(index - back)
            if point is None or (trail and np.hypot(point[0] - trail[-1][0], point[1] - trail[-1][1]) > MAX_JUMP):
                break
            trail.append((point[0], point[1], float(back)))
        entry["trail"] = trail[::-1] if len(trail) >= 3 else []


def _strokes(index: int, born: np.ndarray, matrix: np.ndarray, shape) -> dict:
    """Contornos de la pintura reciente en el fotograma, con la edad de cada punto."""
    h, w = shape
    age = (index - born).astype(np.float32)
    recent = (age >= 0) & (age < RECENT)
    inverse = cv2.invertAffineTransform(matrix)
    tip = None
    # La punta: la mancha más reciente (la mayor de las nacidas en los últimos TIP_FRAMES).
    newest = ((age >= 0) & (age < TIP_FRAMES)).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(newest)
    if count > 1:
        k = 1 + int(np.argmax(stats[1:, 4]))
        point = cv2.transform(np.array([[centroids[k]]], np.float32), inverse)[0, 0]
        tip = (float(point[0] / w), float(point[1] / h))
    if not recent.any():
        return {"strokes": [], "tip": tip}
    # La edad de cada píxel del borde: la menor del vecindario (el borde nuevo manda).
    young = np.where(recent, age, RECENT).astype(np.float32)
    young = cv2.erode(young, np.ones((5, 5), np.uint8))
    mask = cv2.warpAffine(recent.astype(np.uint8) * 255, inverse, (w, h)) > 127
    young = cv2.warpAffine(young, inverse, (w, h), borderValue=RECENT)
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    strokes = []
    for contour in contours:
        if cv2.contourArea(contour) < 20:
            continue
        pts = contour[:, 0, :][:: max(len(contour) // 120, 1)]
        ages = young[np.clip(pts[:, 1], 0, h - 1), np.clip(pts[:, 0], 0, w - 1)]
        strokes.append([(float(x / w), float(y / h), float(a)) for (x, y), a in zip(pts, ages)])
    return {"strokes": strokes, "tip": tip}


# ----- escena de la obra terminada -----

ZONES = ("eyes", "ribs", "nose", "mouth")


def detect_accents(video_path: Path, frames: list[FrameRecord], start: int) -> dict[int, dict]:
    """{fotograma: {"head": (x0, y0, x1, y1), "lines": [{"zone", "points"}]}} desde `start`, en
    los fotogramas sin malla facial (la obra terminada no es una cara humana)."""
    capture = cv2.VideoCapture(str(video_path))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start)
    by_index = {record.frame: record for record in frames}
    out: dict[int, dict] = {}
    index = start - 1
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            index += 1
            record = by_index.get(index)
            if record is not None and record.face:
                continue
            found = _accent_lines(frame, record)
            if found is not None:
                found["eyes"] = _lens_pair(frame)
                out[index] = found
    finally:
        capture.release()
    _steady_eyes(out)
    _add_sockets(video_path, out)
    log.info("Acentos de la obra en %d fotogramas", len(out))
    return out


def _accent_lines(frame: np.ndarray, record: FrameRecord | None) -> dict | None:
    h0, w0 = frame.shape[:2]
    size = WORK if h0 >= w0 else (WORK[1], WORK[0])
    small = cv2.resize(frame, size)
    w, h = size
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    colored = ((hsv[..., 1] > 110) & (hsv[..., 2] > 70)).astype(np.uint8)
    closed = cv2.morphologyEx(colored, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(closed)
    if count < 2 or stats[1:, 4].max() < 0.05 * w * h:
        return None
    biggest = 1 + int(np.argmax(stats[1:, 4]))
    outline, _ = cv2.findContours((labels == biggest).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    region = np.zeros((h, w), np.uint8)
    cv2.drawContours(region, outline, -1, 1, -1)
    region = cv2.erode(region, np.ones((9, 9), np.uint8))
    ys, xs = np.nonzero(region)
    if not len(ys):
        return None
    # La cabeza: por encima de los hombros de la pose, o el 45% de arriba del objeto.
    top = int(ys.min())
    shoulders = [lm.y * h for lm in (record.pose if record else []) if lm.name in ("left_shoulder", "right_shoulder") and lm.c > 0.4]
    neck = int(top + 0.45 * (ys.max() - top))
    if shoulders and 0.3 < (min(shoulders) - top) / max(ys.max() - top, 1) < 0.6:
        neck = int(min(shoulders))
    region[neck:] = 0
    ys, xs = np.nonzero(region)
    if len(ys) < 200:
        return None
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    dark = ((hsv[..., 2] < 70) & (region > 0)).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lines = []
    for contour in contours:
        if cv2.contourArea(contour) < 15:
            continue
        cx, cy = contour[:, 0, :].mean(axis=0)
        u, v = (cx - x0) / max(x1 - x0, 1), (cy - y0) / max(y1 - y0, 1)
        bx, by, bw, bh = cv2.boundingRect(contour)
        tall = bh > 2.5 * bw
        if v > 0.62:
            zone = "mouth"
        elif 0.3 < u < 0.7 and 0.45 < v <= 0.62:
            zone = "nose"
        elif tall and v < 0.5:
            zone = "ribs"
        elif v <= 0.62:
            zone = "eyes"
        else:
            continue
        pts = contour[:, 0, :]
        lines.append({"zone": zone, "points": [(float(x / w), float(y / h)) for x, y in pts]})
    return {"head": (x0 / w, y0 / h, x1 / w, y1 / h), "lines": lines}


# ----- ojos de la obra: los lentes brillantes dentro de las cuencas oscuras -----

EYE_WINDOW = 9
EYE_JUMP = 0.06  # salto máximo frente a la mediana de los vecinos, en anchos del cuadro


def _lens_pair(frame: np.ndarray) -> list[list[float]] | None:
    """Los dos lentes: manchas claras (no del color del objeto) pequeñas y redondas, rodeadas de
    oscuro (la cuenca), a la misma altura y a una distancia de ojos. Normalizados, izquierda a
    derecha de la imagen."""
    import itertools

    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    body = (hsv[..., 0] >= 5) & (hsv[..., 0] <= 25) & (hsv[..., 1] > 120)
    bright = ((hsv[..., 2] > 110) & ~body).astype(np.uint8)
    dark = hsv[..., 2] < 60
    count, labels, stats, centers = cv2.connectedComponentsWithStats(bright)
    area = w * h
    candidates = []
    for k in range(1, count):
        if not 60 / (720 * 1280) * area < stats[k, 4] < 4000 / (720 * 1280) * area:
            continue
        bw, bh = stats[k, 2], stats[k, 3]
        if max(bw, bh) > 3 * min(bw, bh):
            continue
        piece = labels == k
        ring = cv2.dilate(piece.astype(np.uint8), np.ones((31, 31), np.uint8)).astype(bool) & ~piece
        darkness = float(dark[ring].mean())
        if darkness >= 0.3:
            candidates.append((centers[k], darkness))
    best = None
    for (c1, d1), (c2, d2) in itertools.combinations(candidates, 2):
        dx, dy = abs(c1[0] - c2[0]), abs(c1[1] - c2[1])
        if not 0.08 * w < dx < 0.45 * w or dy > 0.35 * dx:
            continue
        score = d1 + d2 - dy / dx
        if best is None or score > best[0]:
            best = (score, sorted([c1, c2], key=lambda c: c[0]))
    if best is None:
        return None
    return [[float(c[0] / w), float(c[1] / h)] for c in best[1]]


def _steady_eyes(accents: dict[int, dict]) -> None:
    """Los ojos casi no se mueven: una pareja que salta lejos de la mediana de sus vecinos es un
    error (dientes, humo) y se reemplaza por esa mediana."""
    frames = sorted(accents)
    for index, frame in enumerate(frames):
        near = [accents[f]["eyes"] for f in frames[max(index - EYE_WINDOW // 2, 0) : index + EYE_WINDOW // 2 + 1] if accents[f].get("eyes")]
        if len(near) < 3:
            continue
        median = np.median(np.array(near), axis=0)
        current = accents[frame].get("eyes")
        if current is None or np.abs(np.array(current) - median).max() > EYE_JUMP:
            accents[frame]["eyes"] = median.tolist()


SOCKET_REACH = 0.75
MIN_FIT = 0.6  # parecido mínimo de la figura con el hueco para usarla  # radio de búsqueda de la cuenca, en distancias entre ojos


def _add_sockets(video_path: Path, accents: dict[int, dict]) -> None:
    """Contorno de cada cuenca: la zona oscura que rodea el lente (tras corregir los ojos)."""
    capture = cv2.VideoCapture(str(video_path))
    try:
        for frame_index in sorted(accents):
            eyes = accents[frame_index].get("eyes")
            if not eyes:
                continue
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            sockets = _sockets(frame, eyes)
            accents[frame_index]["sockets"] = sockets
            h, w = frame.shape[:2]
            nose = _nose(frame, eyes)
            accents[frame_index]["nose"] = nose
            # La figura geométrica de cada hueco (sobre ella se anima).
            figures = {}
            for name, contour in (("left_socket", sockets[0]), ("right_socket", sockets[1]), ("nose", nose)):
                if contour:
                    figure = fit_shape(np.array(contour) * [w, h])
                    if figure is not None and figure["fit"] >= MIN_FIT:
                        figures[name] = {"kind": figure["kind"], "fit": figure["fit"], "points": (shape_points(figure, 64) / [w, h]).tolist()}
            accents[frame_index]["figures"] = figures
    finally:
        capture.release()


def _nose(frame: np.ndarray, eyes) -> list[list[float]]:
    """El hueco de la nariz: la mancha oscura (sin estrías finas) entre los ojos y por debajo."""
    h, w = frame.shape[:2]
    pts = np.array(eyes) * [w, h]
    gap = float(np.linalg.norm(pts[1] - pts[0]))
    mid = pts.mean(axis=0)
    x0, x1 = int(max(mid[0] - gap * 0.35, 0)), int(min(mid[0] + gap * 0.35, w))
    y0, y1 = int(max(mid[1] + gap * 0.12, 0)), int(min(mid[1] + gap * 0.85, h))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return []
    value = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 2]
    dark = (value[y0:y1, x0:x1] < 60).astype(np.uint8)
    size = max(int(gap * 0.1) | 1, 5)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(dark)
    best, best_score = None, 0.0
    for k in range(1, count):
        area = stats[k, 4]
        # Entre los ojos (centro cerca del medio) y de tamaño de nariz.
        off = abs(centers[k][0] - (mid[0] - x0)) / gap
        if off > 0.18 or not (gap * gap * 0.01 < area < gap * gap * 0.25):
            continue
        score = area * (1.0 - off)
        if score > best_score:
            best, best_score = k, score
    if best is None:
        return []
    contours, _ = cv2.findContours((labels == best).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contour = max(contours, key=cv2.contourArea)[:, 0, :] + [x0, y0]
    return [[float(px / w), float(py / h)] for px, py in cv2.approxPolyDP(contour.astype(np.int32), 2.0, True)[:, 0, :]]


def _sockets(frame: np.ndarray, eyes) -> list[list[list[float]]]:
    h, w = frame.shape[:2]
    pts = np.array(eyes) * [w, h]
    gap = float(np.linalg.norm(pts[1] - pts[0]))
    value = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 2]
    out = []
    for eye in pts:
        reach = int(gap * SOCKET_REACH)
        x, y = int(eye[0]), int(eye[1])
        x0, y0, x1, y1 = max(x - reach, 0), max(y - reach, 0), min(x + reach, w), min(y + reach, h)
        window = value[y0:y1, x0:x1]
        dark = (window < 60).astype(np.uint8)
        # El lente (claro) cae dentro de la cuenca: se rellena para que la cuenca sea una pieza.
        cv2.circle(dark, (x - x0, y - y0), max(int(gap * 0.08), 3), 1, -1)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        # Las estrías oscuras tocan la cuenca pero son finas: una apertura las corta.
        size = max(int(gap * 0.14) | 1, 5)
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
        cv2.circle(dark, (x - x0, y - y0), max(int(gap * 0.08), 3), 1, -1)
        count, labels = cv2.connectedComponents(dark)
        label = labels[y - y0, x - x0]
        if label == 0:
            out.append([])
            continue
        piece = (labels == label).astype(np.uint8)
        contours, _ = cv2.findContours(piece, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        biggest = max(contours, key=cv2.contourArea)
        # Una cuenca que se escapa al fondo (cara girada, humo) es demasiado grande: se descarta.
        if cv2.contourArea(biggest) > (gap * 0.75) ** 2:
            out.append([])
            continue
        contour = biggest[:, 0, :] + [x0, y0]
        hull = cv2.approxPolyDP(contour.astype(np.int32), 2.0, True)[:, 0, :]
        out.append([[float(px / w), float(py / h)] for px, py in hull])
    return out
