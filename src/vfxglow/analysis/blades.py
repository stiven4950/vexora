"""Hojas en las manos: espadas, bastones, katanas.

Cada mano que sostiene algo largo y recto recibe un segmento empuñadura → punta por fotograma.
Tres fuentes, de más a menos fiable:

- line: la dirección desde la mano con la cresta (top-hat + black-hat) más larga y continua.
  Es la hoja real.
- yolo: caja de "sword"/"knife"/"stick" de YOLO-World (opcional, si ultralytics está instalado);
  se usa la diagonal que pasa por la mano.
- prior: sin línea, la hoja se estima con la dirección del agarre y el largo medio de la hoja en
  el video. Solo rellena huecos cortos entre detecciones reales.

Dirección del agarre: con la mano detectada, la hoja sale por la línea de los nudillos (del
meñique al índice); sin mano, prolonga el antebrazo. Una recta que va hacia el codo es el
antebrazo y se descarta; una que no pasa por la mano es el fondo (líneas del piso).

En modo `auto` el video solo "tiene hojas" si hay líneas reales en bastantes fotogramas; si
no, se descarta todo: un video de puños no debe recibir espadas inventadas.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from vfxglow.analysis.schema import Blade, FrameRecord, PersonPose
from vfxglow.config import BladesConfig

log = logging.getLogger("vfxglow.blades")

# Recta candidata: distancia de la mano a la recta y hueco hasta su extremo cercano (torsos).
MAX_PERP = 0.45
MAX_GAP = 0.7
MIN_LENGTH = 0.6
# Ángulo mínimo con el antebrazo (una recta hacia el codo es el brazo, no la hoja).
FOREARM_EXCLUDE = np.radians(35.0)
HAND_MAX_OFFSET = 0.5
# Fracción mínima del largo típico con la que se dibuja una hoja (escorzo hacia la cámara).
MIN_SHARE = 0.8
# Barrido de rayos: dónde empieza y acaba la búsqueda (torsos), ancho de la banda perpendicular,
# paso angular y fracción mínima de la racha con cresta.
RAY_START = 0.2
RAY_REACH = 2.4
RAY_BAND = 0.18
RAY_STEP_DEG = 3
RAY_COVER = 0.6
# Una recta del fondo (raya del piso) cruza la mano y sigue del otro lado; la hoja acaba en
# la empuñadura. Si más de BEYOND_MAX de los puntos tras la mano son cresta, se descarta.
BEYOND = 0.6
BEYOND_MAX = 0.5
# Coherencia temporal: una detección que cambia de largo más de JUMP_LENGTH (fracción) o gira
# más de JUMP_ANGLE respecto a la mediana de sus vecinas es ruido.
JUMP_LENGTH = 0.4
JUMP_ANGLE = np.radians(50.0)
NEIGHBORS = 6
_KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))


class BladeFinder:
    def __init__(self, cfg: BladesConfig) -> None:
        self.cfg = cfg
        self._yolo = None
        if cfg.detector == "yoloworld":
            try:
                from ultralytics import YOLOWorld  # type: ignore[import-not-found]

                self._yolo = YOLOWorld(cfg.yolo_model)
                self._yolo.set_classes(list(cfg.yolo_classes))
            except ImportError:
                log.warning("blades.detector=yoloworld pero ultralytics no está instalado; se usan solo líneas.")

    def detect(self, record: FrameRecord, frame_bgr: np.ndarray) -> list[Blade]:
        people = record.people or ([PersonPose(person_id=record.person_id, pose=record.pose, left_hand=record.left_hand, right_hand=record.right_hand)] if record.pose else [])
        if not people:
            return []
        height, width = frame_bgr.shape[:2]
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        ridge = np.maximum(cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, _KERNEL), cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, _KERNEL))
        boxes = self._yolo_boxes(frame_bgr) if self._yolo is not None else []
        found: list[Blade] = []
        for person in people:
            pts = {lm.name: np.array([lm.x * width, lm.y * height]) for lm in person.pose if lm.c > 0.3}
            torso = _torso(pts)
            if torso is None:
                continue
            for side in ("left", "right"):
                hand = _hand(person, side, width, height)
                wrist = pts.get(f"{side}_wrist")
                elbow = pts.get(f"{side}_elbow")
                if wrist is None:
                    continue
                # Una mano detectada lejos de la muñeca de la pose es otra cosa (una rodilla).
                if hand is not None and np.linalg.norm(hand["center"] - wrist) > HAND_MAX_OFFSET * torso:
                    hand = None
                grip = hand["center"] if hand else wrist
                prior = _grip_direction(hand, wrist, elbow)
                # Rayos primero (más precisos); rectas de Hough si no encuentran nada (más
                # cobertura: en video_38 los bastones negros sobre el mural escapan a los rayos).
                best = _best_line(ridge, grip, prior, elbow, torso)
                if best is None:
                    best = _best_hough(ridge, grip, prior, elbow, torso)
                if best is None and boxes:
                    best = _best_box(boxes, grip, prior, elbow, torso)
                if best is None:
                    continue
                hilt, tip, source, score = best
                found.append(
                    Blade(
                        person=person.person_id,
                        hand=side,
                        hilt=(float(hilt[0] / width), float(hilt[1] / height)),
                        tip=(float(tip[0] / width), float(tip[1] / height)),
                        confidence=float(np.clip(score, 0.0, 1.0)),
                        source=source,
                    )
                )
        return found

    def _yolo_boxes(self, frame_bgr: np.ndarray) -> list[tuple[float, float, float, float]]:
        results = self._yolo.predict(frame_bgr, conf=self.cfg.yolo_confidence, verbose=False)
        return [tuple(map(float, box)) for result in results for box in result.boxes.xyxy.tolist()]


def _torso(pts: dict[str, np.ndarray]) -> float | None:
    for side in ("left", "right"):
        if f"{side}_shoulder" in pts and f"{side}_hip" in pts:
            return float(max(np.linalg.norm(pts[f"{side}_shoulder"] - pts[f"{side}_hip"]), 20.0))
    return None


def _hand(person: PersonPose, side: str, width: int, height: int) -> dict | None:
    hand = person.left_hand if side == "left" else person.right_hand
    if hand is None or not hand.landmarks:
        return None
    pts = {lm.name.split("_", 1)[1]: np.array([lm.x * width, lm.y * height]) for lm in hand.landmarks}
    if "index_mcp" not in pts or "pinky_mcp" not in pts:
        return None
    knuckles = [pts[name] for name in ("index_mcp", "middle_mcp", "ring_mcp", "pinky_mcp") if name in pts]
    center = (np.mean(knuckles, axis=0) + pts.get("wrist", knuckles[0])) * 0.5
    return {"center": center, "index": pts["index_mcp"], "pinky": pts["pinky_mcp"]}


def _grip_direction(hand: dict | None, wrist: np.ndarray, elbow: np.ndarray | None) -> np.ndarray | None:
    """Dirección esperada de la hoja: de meñique a índice; sin mano, prolonga el antebrazo."""
    if hand is not None:
        d = hand["index"] - hand["pinky"]
    elif elbow is not None:
        d = wrist - elbow
    else:
        return None
    n = float(np.linalg.norm(d))
    return d / n if n > 1e-6 else None


def _beyond(ridge: np.ndarray | None, threshold: float, hilt: np.ndarray, out: np.ndarray, torso: float) -> float:
    """Fracción de puntos con cresta en la prolongación de la recta tras la empuñadura."""
    if ridge is None:
        return 0.0
    height, width = ridge.shape
    steps = np.linspace(torso * 0.25, torso * BEYOND, 12)
    pts = hilt - steps[:, None] * out
    inside = (pts[:, 0] >= 0) & (pts[:, 0] < width) & (pts[:, 1] >= 0) & (pts[:, 1] < height)
    if not inside.any():
        return 0.0
    values = ridge[pts[inside, 1].astype(int), pts[inside, 0].astype(int)]
    return float((values > threshold).mean())


def _score_segment(a: np.ndarray, b: np.ndarray, grip: np.ndarray, prior: np.ndarray | None, elbow: np.ndarray | None, torso: float, ridge: np.ndarray | None = None, threshold: float = 0.0):
    d = b - a
    length = float(np.linalg.norm(d))
    if length < MIN_LENGTH * torso:
        return None
    u = d / length
    perp = abs(float((grip - a) @ np.array([-u[1], u[0]])))
    near, far = (a, b) if np.linalg.norm(a - grip) < np.linalg.norm(b - grip) else (b, a)
    gap = float(np.linalg.norm(near - grip))
    if perp > MAX_PERP * torso or gap > MAX_GAP * torso:
        return None
    out = (far - near) / length
    if elbow is not None:
        arm = elbow - grip
        if np.linalg.norm(arm) > 1e-6 and out @ (arm / np.linalg.norm(arm)) > np.cos(FOREARM_EXCLUDE):
            return None
    # La hoja empieza en la mano: la empuñadura es el punto de la recta más cercano al agarre.
    hilt = near + out * float((grip - near) @ out)
    if _beyond(ridge, threshold, hilt, out, torso) > BEYOND_MAX:
        return None
    agree = abs(float(out @ prior)) if prior is not None else 0.5
    score = (length / torso) * (0.8 + 0.4 * agree) - gap / torso - perp / torso
    return hilt, far, score


def _best_line(ridge: np.ndarray, grip: np.ndarray, prior, elbow, torso: float):
    """Barre direcciones desde la mano y se queda con la que tiene una cresta larga y continua.

    Cada dirección se prueba en una banda de desplazamientos perpendiculares: el mango queda
    bajo el puño y la hoja no pasa justo por la muñeca. Medido contra lo pintado en la
    referencia de video_39, acierta 68% de las hojas frente a 54% de Hough sobre la zona.
    """
    height, width = ridge.shape
    threshold = max(float(np.percentile(ridge, 92)), 15.0)
    steps = np.arange(torso * RAY_START, torso * RAY_REACH, 3.0)
    offsets = np.linspace(-torso * RAY_BAND, torso * RAY_BAND, 7)
    arm = None
    if elbow is not None and np.linalg.norm(elbow - grip) > 1e-6:
        arm = (elbow - grip) / np.linalg.norm(elbow - grip)
    best = None
    for angle in np.radians(np.arange(0, 360, RAY_STEP_DEG)):
        direction = np.array([np.cos(angle), np.sin(angle)])
        if arm is not None and direction @ arm > np.cos(FOREARM_EXCLUDE):
            continue
        normal = np.array([-direction[1], direction[0]])
        lane = None
        for offset in offsets:
            pts = grip + normal * offset + steps[:, None] * direction
            inside = (pts[:, 0] >= 0) & (pts[:, 0] < width) & (pts[:, 1] >= 0) & (pts[:, 1] < height)
            values = np.zeros(len(steps))
            values[inside] = ridge[pts[inside, 1].astype(int), pts[inside, 0].astype(int)]
            end = _supported_end(values > threshold)
            if end < 0:
                continue
            cover = float((values[: end + 1] > threshold).mean())
            length = float(steps[end])
            if length < MIN_LENGTH * torso or cover < RAY_COVER:
                continue
            score = (length / torso) * cover
            if lane is None or score > lane[0]:
                lane = (score, offset, length)
        if lane is None:
            continue
        score, offset, length = lane
        hilt = grip + normal * offset + direction * steps[0]
        if _beyond(ridge, threshold, hilt, direction, torso) > BEYOND_MAX:
            continue
        agree = abs(float(direction @ prior)) if prior is not None else 0.5
        score *= 0.8 + 0.4 * agree
        if best is None or score > best[2]:
            best = (hilt, grip + normal * offset + direction * length, score)
    if best is None:
        return None
    hilt, tip, score = best
    return hilt, tip, "line", min(1.0, 0.4 + 0.2 * score)


def _supported_end(hits: np.ndarray, max_miss: int = 4) -> int:
    """Último índice de la racha que empieza en la mano, tolerando huecos cortos."""
    miss, end = 0, -1
    for index, hit in enumerate(hits):
        if hit:
            miss, end = 0, index
        else:
            miss += 1
            if miss > max_miss:
                break
    return end


def _best_hough(ridge: np.ndarray, grip: np.ndarray, prior, elbow, torso: float):
    height, width = ridge.shape
    reach = int(torso * 2.6)
    x0, y0 = int(max(0, grip[0] - reach)), int(max(0, grip[1] - reach))
    x1, y1 = int(min(width, grip[0] + reach)), int(min(height, grip[1] + reach))
    roi = ridge[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    threshold = max(float(np.percentile(roi, 93)), 18.0)
    mask = (roi > threshold).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(mask, 1, np.pi / 180, 50, minLineLength=int(torso * MIN_LENGTH), maxLineGap=int(torso * 0.15))
    best = None
    offset = np.array([x0, y0], dtype=np.float64)
    edge = 3
    for line in lines.reshape(-1, 4) if lines is not None else []:
        scored = _score_segment(line[:2] + offset, line[2:] + offset, grip, prior, elbow, torso, ridge, threshold)
        if scored is None:
            continue
        hilt, tip, score = scored
        # Una raya del fondo sale de la zona de búsqueda; la punta de una hoja acaba dentro.
        if tip[0] <= x0 + edge or tip[0] >= x1 - edge or tip[1] <= y0 + edge or tip[1] >= y1 - edge:
            if 0 < x0 and x1 < width and 0 < y0 and y1 < height:
                score -= 1.5
        if best is None or score > best[2]:
            best = (hilt, tip, score)
    if best is None:
        return None
    hilt, tip, score = best
    return hilt, tip, "line", min(1.0, 0.4 + 0.2 * score)


def _best_box(boxes, grip, prior, elbow, torso: float):
    best = None
    for x0, y0, x1, y1 in boxes:
        for a, b in ((np.array([x0, y0]), np.array([x1, y1])), (np.array([x0, y1]), np.array([x1, y0]))):
            scored = _score_segment(a, b, grip, prior, elbow, torso)
            if scored is not None and (best is None or scored[2] > best[2]):
                best = scored
    if best is None:
        return None
    hilt, tip, score = best
    return hilt, tip, "yolo", min(1.0, 0.4 + 0.2 * score)


def finalize_blades(frames: list[FrameRecord], cfg: BladesConfig, width: int, height: int) -> None:
    """Decide si el video tiene hojas, rellena huecos cortos y suaviza el ángulo.

    Se trabaja por (persona, mano). El largo de la hoja es la mediana de las detecciones
    reales en torsos; los huecos de hasta `fill_gap` fotogramas se rellenan con la dirección
    interpolada y ese largo (fuente `prior`).
    """
    detected = sum(1 for record in frames for blade in record.blades if blade.source != "prior")
    people = sum(max(len(record.people), 1 if record.pose else 0) for record in frames)
    ratio = detected / max(people * 2, 1)
    if cfg.mode == "auto" and ratio < cfg.min_presence:
        log.info("Hojas: %.0f%% de manos con línea; menos del %.0f%%, el video no tiene hojas", ratio * 100, cfg.min_presence * 100)
        for record in frames:
            record.blades = []
        return
    scale = np.array([width, height], dtype=np.float64)
    keys = sorted({(b.person, b.hand) for record in frames for b in record.blades})
    for person, hand in keys:
        series = {record.frame: next((b for b in record.blades if b.person == person and b.hand == hand), None) for record in frames}
        # En píxeles: con coordenadas normalizadas un giro deformaría la hoja (720x1280 no es cuadrado).
        hits = {frame: _to_px(blade, scale) for frame, blade in series.items() if blade is not None}
        # Una hoja aislada (un solo fotograma rodeado de nada) suele ser ruido del fondo.
        for frame in list(hits):
            if not any(f in hits for f in range(frame - 3, frame + 4) if f != frame):
                del hits[frame]
        _drop_jumps(hits)
        lengths = [np.hypot(b.tip[0] - b.hilt[0], b.tip[1] - b.hilt[1]) for b in hits.values()]
        if not lengths:
            continue
        # La hoja no cambia de largo; el desenfoque sí acorta lo que se ve. El percentil alto es
        # el largo real, y ninguna hoja se dibuja más corta que MIN_SHARE de él.
        typical = float(np.percentile(lengths, 80))
        ordered = sorted(hits)
        for a, b in zip(ordered, ordered[1:]):
            if 1 < b - a <= cfg.fill_gap:
                for frame in range(a + 1, b):
                    t = (frame - a) / (b - a)
                    ha, hb = np.array(hits[a].hilt), np.array(hits[b].hilt)
                    da = np.array(hits[a].tip) - ha
                    db = np.array(hits[b].tip) - hb
                    angle = _lerp_angle(np.arctan2(da[1], da[0]), np.arctan2(db[1], db[0]), t)
                    hilt = ha + (hb - ha) * t
                    tip = hilt + np.array([np.cos(angle), np.sin(angle)]) * typical
                    hits[frame] = Blade(person=person, hand=hand, hilt=tuple(hilt), tip=tuple(tip), confidence=0.3, source="prior")
        smoothed = {frame: _to_norm(_at_least(blade, typical * MIN_SHARE), scale) for frame, blade in _smooth_angles(hits, typical, cfg.smooth).items()}
        for record in frames:
            record.blades = [b for b in record.blades if not (b.person == person and b.hand == hand)]
            if record.frame in smoothed:
                record.blades.append(smoothed[record.frame])
    total = sum(len(record.blades) for record in frames)
    log.info("Hojas: %d segmentos (%.0f%% de manos con línea)", total, ratio * 100)


def _at_least(blade: Blade, length: float) -> Blade:
    hilt, tip = np.array(blade.hilt), np.array(blade.tip)
    current = float(np.linalg.norm(tip - hilt))
    if current >= length or current < 1e-6:
        return blade
    tip = hilt + (tip - hilt) * (length / current)
    return blade.model_copy(update={"tip": (float(tip[0]), float(tip[1]))})


def _to_px(blade: Blade, scale: np.ndarray) -> Blade:
    return blade.model_copy(update={"hilt": tuple(np.array(blade.hilt) * scale), "tip": tuple(np.array(blade.tip) * scale)})


def _to_norm(blade: Blade, scale: np.ndarray) -> Blade:
    return blade.model_copy(update={"hilt": tuple(map(float, np.array(blade.hilt) / scale)), "tip": tuple(map(float, np.array(blade.tip) / scale))})


def _drop_jumps(hits: dict[int, Blade]) -> None:
    """Quita detecciones cuyo largo o ángulo se apartan mucho de la mediana de sus vecinas."""
    vectors = {frame: np.array(b.tip) - np.array(b.hilt) for frame, b in hits.items()}
    bad = []
    for frame, vec in vectors.items():
        near = [vectors[f] for f in range(frame - NEIGHBORS, frame + NEIGHBORS + 1) if f != frame and f in vectors]
        if len(near) < 2:
            continue
        lengths = [float(np.linalg.norm(v)) for v in near]
        typical = float(np.median(lengths))
        angles = [float(np.arctan2(v[1], v[0])) for v in near]
        ref = float(np.arctan2(np.median(np.sin(angles)), np.median(np.cos(angles))))
        angle = float(np.arctan2(vec[1], vec[0]))
        turn = abs((angle - ref + np.pi) % (2 * np.pi) - np.pi)
        if abs(float(np.linalg.norm(vec)) - typical) > JUMP_LENGTH * typical or turn > JUMP_ANGLE:
            bad.append(frame)
    for frame in bad:
        del hits[frame]


def _lerp_angle(a: float, b: float, t: float) -> float:
    delta = (b - a + np.pi) % (2 * np.pi) - np.pi
    return a + delta * t


def _smooth_angles(hits: dict[int, Blade], typical: float, alpha: float) -> dict[int, Blade]:
    """Media exponencial del ángulo y del largo; se reinicia si hay un hueco."""
    out: dict[int, Blade] = {}
    prev_frame, angle, length = None, 0.0, typical
    for frame in sorted(hits):
        blade = hits[frame]
        hilt = np.array(blade.hilt)
        d = np.array(blade.tip) - hilt
        raw_angle, raw_length = float(np.arctan2(d[1], d[0])), float(np.linalg.norm(d))
        if prev_frame is None or frame - prev_frame > 1:
            angle, length = raw_angle, raw_length
        else:
            angle = _lerp_angle(angle, raw_angle, alpha)
            length = length + (raw_length - length) * alpha
        tip = hilt + np.array([np.cos(angle), np.sin(angle)]) * length
        out[frame] = blade.model_copy(update={"tip": (float(tip[0]), float(tip[1]))})
        prev_frame = frame
    return out
