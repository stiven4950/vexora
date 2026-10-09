"""Objeto protagonista: dónde está, su contorno exacto y quién lo tiene.

Medido en video_33 (la gorra que pasa de mano en mano y acaba en la cabeza):

- Grounding DINO ("a baseball cap.") encuentra la gorra en los fotogramas difíciles (boca
  arriba, tapada por la mano), pero tarda ~1,6 s y solo da una caja.
- SAM 2 en modo video, sembrado con esa caja, recorta el contorno exacto y lo sigue solo de un
  fotograma al siguiente (~1,2 s por fotograma en MPS con el modelo tiny).

Grounding DINO busca el objeto mientras no lo hay y, una vez encontrado, comprueba cada
`check_every` fotogramas que SAM 2 sigue sobre él; si se fue a otra cosa, lo vuelve a sembrar.

Después, cada fotograma recibe un estado según las manos y la cabeza de la pose (ver `Prop`), y
los cambios de estado dan los eventos `prop_transfer` (de una mano a la otra) y `prop_worn`
(llega a la cabeza).
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent, PersonPose, Prop
from vfxglow.config import PropsConfig

log = logging.getLogger("vfxglow.props")

# SAM 2 usa como memoria los últimos 7 fotogramas; la sesión guarda todos, así que se podan.
KEEP_FRAMES = 16
# Una caja de Grounding DINO que se solapa menos que esto con la máscara indica que SAM 2 se fue.
RESEED_IOU = 0.2
# Color del objeto: fotogramas de los que se aprende y distancia de Bhattacharyya máxima de
# un candidato. Medido en video_33: gorra 0,36-0,47; zapato 0,73-0,75; pelo 0,89-0,92.
APPEARANCE_FRAMES = 60
APPEARANCE_MAX = 0.6
# Comprobaciones seguidas (cada `search_every`) sin ver el objeto antes de darlo por perdido.
MAX_MISSES = 3
# Mano que "toca" el objeto: distancia al contorno, en tamaños del objeto (raíz del área de la caja).
HAND_REACH = 1.0
WRIST_REACH = 1.4
# Ventana (fotogramas) del filtro de mayoría que quita parpadeos del estado.
STATE_WINDOW = 5
# Tramos de menos de esto entre dos tramos "en la cabeza" (o fuera) se funden con sus vecinos.
MIN_RUN = 10
# prop_worn solo cuenta si el objeto estuvo fuera de la cabeza al menos este tiempo.
WORN_AWAY_S = 1.0
# Un traspaso puede pasar por "both" o "air" hasta este tiempo entre una mano y la otra.
TRANSFER_GAP_S = 1.0
# Giro en las manos: ventana de la media, puntuación mínima y duración mínima.
SPIN_WINDOW = 9
SPIN_SCORE = 10.0
SPIN_MIN_S = 0.4
HANDS = ("left", "right")
HEAD_STATES = ("worn", "fitting")


class PropTracker:
    def __init__(self, cfg: PropsConfig) -> None:
        import torch
        from transformers import Sam2VideoModel, Sam2VideoProcessor

        from vfxglow.analysis.gdino import GroundingDino, torch_device, trust_certifi

        trust_certifi()
        self.cfg = cfg
        self.device = torch_device()
        self.dino = GroundingDino(cfg.detector_model, cfg.query, cfg.threshold)
        self.processor = Sam2VideoProcessor.from_pretrained(cfg.sam_model)
        self.model = Sam2VideoModel.from_pretrained(cfg.sam_model).to(self.device)
        self.session = self.processor.init_video_session(inference_device=self.device, dtype=torch.float32)
        self.appearance: np.ndarray | None = None
        self.learned = 0
        self.label = cfg.query.strip().rstrip(".").removeprefix("a ").removeprefix("an ")

    def track(self, video_path: Path, records: list[FrameRecord]) -> int:
        """Rellena `record.prop` (sin estado aún). Devuelve en cuántos fotogramas se vio."""
        import torch

        from vfxglow.io.video import VideoReader

        by_frame = {record.frame: record for record in records}
        seeded = False
        last_box = None
        seen = 0
        # Fotogramas guardados desde que Grounding DINO dejó de ver el objeto: si no vuelve a
        # verlo en MAX_MISSES comprobaciones, SAM 2 se quedó con otra cosa y se borran.
        doubtful: list[FrameRecord] = []
        misses = 0
        with VideoReader(video_path) as reader:
            height, width = reader.meta.height, reader.meta.width
            for index, frame in reader:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                inputs = self.processor(images=rgb, device=self.device, return_tensors="pt")
                # Grounding DINO decide antes de que SAM 2 vea el fotograma (una pasada por
                # fotograma), comparando con la máscara del anterior.
                lost = last_box is None
                every = self.cfg.search_every if lost or misses else self.cfg.check_every
                if index % max(every, 1) == 0:
                    found = self.dino.detect(frame)
                    # Sigue ahí: alguna caja (aunque sea de confianza baja) coincide con la máscara.
                    confirmed = not lost and any(_iou(last_box, box) >= RESEED_IOU for box, _ in found)
                    # Sembrar exige confianza y el color del objeto: Grounding DINO llama "hat"
                    # al pelo (0,48) y a un zapato (0,35) cuando la gorra sale de cuadro.
                    candidates = [box for box, score in found if score >= self.cfg.seed_threshold and self._looks_like(frame, box)]
                    if confirmed:
                        misses = 0
                        doubtful.clear()
                    elif candidates:
                        self._seed(index, candidates[0], inputs)
                        seeded = True
                        misses = 0
                        doubtful.clear()
                    elif seeded and not lost:
                        misses += 1
                        if misses >= MAX_MISSES:
                            for record in doubtful:
                                record.prop = None
                            seen -= len(doubtful)
                            doubtful.clear()
                            misses = 0
                            seeded = False
                            self.session.reset_tracking_data()
                mask = None
                if seeded:
                    with torch.no_grad():
                        out = self.model(inference_session=self.session, frame=inputs.pixel_values[0], frame_idx=index)
                    mask = self._mask(out, inputs)
                    self._prune(index)
                last_box = _bbox(mask)
                if last_box is not None and not misses:
                    self._learn(frame, mask)
                record = by_frame.get(index)
                if record is not None and mask is not None and mask.any():
                    prop = _to_prop(mask, self.label, width, height, self.cfg.contour_points)
                    if prop is not None:
                        record.prop = prop
                        seen += 1
                        if misses:
                            doubtful.append(record)
                if (index + 1) % 50 == 0:
                    log.info("Objeto: %d/%d fotogramas (visto en %d)", index + 1, reader.meta.frame_count, seen)
        return seen

    def _learn(self, frame: np.ndarray, mask: np.ndarray) -> None:
        """Color del objeto (H-S) aprendido de los primeros fotogramas seguidos con seguridad."""
        if self.learned >= APPEARANCE_FRAMES:
            return
        inner = cv2.erode(mask.astype(np.uint8) * 255, np.ones((9, 9), np.uint8))
        if inner.any():
            hist = _hs_hist(frame, inner)
            self.appearance = hist if self.appearance is None else self.appearance + hist
            self.learned += 1

    def _looks_like(self, frame: np.ndarray, box) -> bool:
        """El centro de la caja (60%, para no medir el fondo) tiene el color aprendido."""
        if self.appearance is None:
            return True
        x0, y0, x1, y1 = box
        cx, cy, hw, hh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 0.3, (y1 - y0) * 0.3
        inner = np.zeros(frame.shape[:2], np.uint8)
        inner[max(int(cy - hh), 0) : int(cy + hh) + 1, max(int(cx - hw), 0) : int(cx + hw) + 1] = 255
        reference = cv2.normalize(self.appearance, None).flatten()
        return cv2.compareHist(reference, _hs_hist(frame, inner), cv2.HISTCMP_BHATTACHARYYA) <= APPEARANCE_MAX

    def _seed(self, index: int, box, inputs) -> None:
        self.processor.add_inputs_to_inference_session(
            inference_session=self.session,
            frame_idx=index,
            obj_ids=1,
            input_boxes=[[list(box)]],
            original_size=inputs.original_sizes[0],
        )

    def _mask(self, out, inputs) -> np.ndarray:
        masks = self.processor.post_process_masks([out.pred_masks], original_sizes=inputs.original_sizes, binarize=True)
        return masks[0][0, 0].cpu().numpy().astype(bool)

    def _prune(self, index: int) -> None:
        """La sesión guarda cada fotograma (~12 MB) y cada salida: sin podar, 900 fotogramas
        llenan la memoria y el sistema entra en swap."""
        oldest = index - KEEP_FRAMES
        frames = self.session.processed_frames or {}
        for old in [f for f in frames if f < oldest]:
            del frames[old]
        for outputs in self.session.output_dict_per_obj.values():
            kept = outputs["non_cond_frame_outputs"]
            for old in [f for f in kept if f < oldest]:
                del kept[old]
        for tracked in self.session.frames_tracked_per_obj.values():
            for old in [f for f in tracked if f < oldest]:
                del tracked[old]


def _hs_hist(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], mask, [18, 8], [0, 180, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def _bbox(mask: np.ndarray | None):
    if mask is None or not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    return (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))


def _iou(a, b) -> float:
    if a is None or b is None:
        return 0.0
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _to_prop(mask: np.ndarray, label: str, width: int, height: int, max_points: int) -> Prop | None:
    """La pieza más grande de la máscara, simplificada hasta `max_points` puntos."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 30:
        return None
    epsilon = 0.5
    simple = contour
    while len(simple) > max_points:
        simple = cv2.approxPolyDP(contour, epsilon, True)
        epsilon *= 1.5
    pts = simple[:, 0, :].astype(np.float64)
    x, y, w, h = cv2.boundingRect(contour)
    return Prop(
        label=label,
        contour=[(float(px / width), float(py / height)) for px, py in pts],
        box=(x / width, y / height, (x + w) / width, (y + h) / height),
    )


# ----- estado: quién lo tiene -----


def _people(record: FrameRecord) -> list[PersonPose]:
    if record.people:
        return record.people
    if record.pose:
        return [PersonPose(person_id=record.person_id, pose=record.pose, left_hand=record.left_hand, right_hand=record.right_hand)]
    return []


def _hand_point(person: PersonPose, side: str, width: int, height: int) -> tuple[np.ndarray | None, float]:
    """Centro de la mano (o la muñeca de la pose, con más tolerancia) y su alcance."""
    hand = person.left_hand if side == "left" else person.right_hand
    if hand is not None and hand.landmarks:
        pts = np.array([[lm.x * width, lm.y * height] for lm in hand.landmarks])
        return pts.mean(axis=0), HAND_REACH
    for lm in person.pose:
        if lm.name == f"{side}_wrist" and lm.c > 0.3:
            return np.array([lm.x * width, lm.y * height]), WRIST_REACH
    return None, 0.0


def _head(person: PersonPose, width: int, height: int) -> tuple[np.ndarray, float] | None:
    """Centro de la coronilla y tamaño de la cabeza, en píxeles.

    Sin nariz (de espaldas, cara tapada) se usan ojos u orejas; sin cara, los hombros."""
    pts = {lm.name: np.array([lm.x * width, lm.y * height]) for lm in person.pose if lm.c > 0.3}
    shoulders = pts.get("left_shoulder"), pts.get("right_shoulder")
    if "left_ear" in pts and "right_ear" in pts:
        size = float(np.linalg.norm(pts["left_ear"] - pts["right_ear"]))
    elif "left_eye" in pts and "right_eye" in pts:
        size = float(np.linalg.norm(pts["left_eye"] - pts["right_eye"])) * 2.2
    elif shoulders[0] is not None and shoulders[1] is not None:
        size = float(np.linalg.norm(shoulders[0] - shoulders[1])) * 0.45
    else:
        return None
    size = max(size, 10.0)
    face = [pts[name] for name in ("nose", "left_eye", "right_eye", "left_ear", "right_ear") if name in pts]
    if face:
        anchor = pts["nose"] if "nose" in pts else np.mean(face, axis=0)
        return anchor - np.array([0.0, size * 0.8]), size
    if shoulders[0] is None or shoulders[1] is None:
        return None
    return (shoulders[0] + shoulders[1]) * 0.5 - np.array([0.0, size * 2.2]), size


def frame_state(record: FrameRecord, width: int, height: int) -> tuple[str, str]:
    """(estado, persona) del objeto en este fotograma."""
    prop = record.prop
    assert prop is not None
    polygon = (np.array(prop.contour) * [width, height]).astype(np.float32).reshape(-1, 1, 2)
    size = float(np.sqrt(max((prop.box[2] - prop.box[0]) * width * (prop.box[3] - prop.box[1]) * height, 1.0)))
    center = polygon[:, 0, :].mean(axis=0)
    best: tuple[str, str] | None = None
    for person in _people(record):
        touching = []
        for side in HANDS:
            point, reach = _hand_point(person, side, width, height)
            if point is None:
                continue
            # Positivo dentro del contorno; negativo = distancia al borde.
            inside = cv2.pointPolygonTest(polygon, (float(point[0]), float(point[1])), True)
            if inside > -reach * size:
                touching.append(side)
        head = _head(person, width, height)
        on_head = head is not None and np.linalg.norm(center - head[0]) < head[1] * 1.1 and center[1] < head[0][1] + head[1] * 0.8
        if on_head:
            return ("fitting" if touching else "worn"), person.person_id
        if len(touching) == 2:
            best = ("both", person.person_id)
        elif touching and best is None:
            best = (touching[0], person.person_id)
    return best or ("air", record.person_id)


def assign_states(records: list[FrameRecord], width: int, height: int) -> None:
    raw = [(index, frame_state(record, width, height)) for index, record in enumerate(records) if record.prop is not None]
    half = STATE_WINDOW // 2
    states = []
    for k, (index, (state, person)) in enumerate(raw):
        window = [item[1][0] for item in raw[max(k - half, 0) : k + half + 1]]
        values, counts = np.unique(window, return_counts=True)
        majority = str(values[int(np.argmax(counts))])
        states.append(majority if counts.max() > len(window) // 2 else state)
        records[index].prop.person = person
    for (index, _), state in zip(raw, _merge_head_runs(states)):
        records[index].prop.state = state


def _merge_head_runs(states: list[str]) -> list[str]:
    """Un tramo corto fuera de la cabeza entre dos en la cabeza es la pose que falló (y al revés).

    Se funde primero el tramo más corto y se recalculan los tramos: así dos tramos cortos
    seguidos no se intercambian entre sí.
    """
    out = list(states)
    while True:
        runs = []
        start = 0
        for end in range(1, len(out) + 1):
            if end == len(out) or (out[end] in HEAD_STATES) != (out[start] in HEAD_STATES):
                runs.append((start, end))
                start = end
        short = [run for run in runs[1:-1] if run[1] - run[0] < MIN_RUN]
        if not short:
            return out
        first, last = min(short, key=lambda run: run[1] - run[0])
        out[first:last] = [out[first - 1]] * (last - first)


# ----- eventos -----


def prop_events(frames: list[FrameRecord], fps: float, width: int = 1, height: int = 1) -> list[MotionEvent]:
    """prop_transfer: pasa de una mano a la otra (kind left_to_right / right_to_left).
    prop_worn: llega a la cabeza (kind fit si una mano lo acompaña, drop si cae solo).
    prop_spin: gira en las manos (ver `spin_events`)."""
    events: list[MotionEvent] = []
    gap = int(round(TRANSFER_GAP_S * fps))
    holder: tuple[str, int] | None = None  # (mano, último fotograma con ella)
    away: int | None = None  # desde cuándo está fuera de la cabeza
    for record in frames:
        prop = record.prop
        if prop is None:
            continue
        state = prop.state
        center = tuple(np.mean(np.array(prop.contour), axis=0).tolist())
        if state in HANDS:
            if holder is not None and holder[0] != state and record.frame - holder[1] <= gap:
                events.append(
                    MotionEvent(
                        name="prop_transfer",
                        target=f"{prop.person}:prop",
                        start_frame=holder[1],
                        end_frame=record.frame,
                        confidence=0.9,
                        detail=f"El objeto ({prop.label}) pasa de la mano {_es(holder[0])} a la {_es(state)}.",
                        position=center,
                        kind=f"{holder[0]}_to_{state}",
                    )
                )
            holder = (state, record.frame)
        if state in HEAD_STATES:
            if away is not None and record.frame - away >= int(WORN_AWAY_S * fps):
                events.append(
                    MotionEvent(
                        name="prop_worn",
                        target=f"{prop.person}:prop",
                        start_frame=record.frame,
                        end_frame=record.frame + int(fps * 0.5),
                        confidence=0.9,
                        detail=f"El objeto ({prop.label}) llega a la cabeza.",
                        position=center,
                        kind="fit" if state == "fitting" else "drop",
                    )
                )
            away = None
        elif away is None:
            away = record.frame
    events.extend(spin_events(frames, fps, [e for e in events if e.name == "prop_transfer"], width, height))
    events.sort(key=lambda e: e.start_frame)
    return events


def shape_signature(polygon: np.ndarray) -> tuple[float, float, float]:
    """(orientación del eje largo en grados, excentricidad menor/mayor, área) por momentos."""
    m = cv2.moments(polygon.astype(np.float32))
    if m["m00"] <= 0:
        return 0.0, 1.0, 0.0
    mu20, mu02, mu11 = m["mu20"] / m["m00"], m["mu02"] / m["m00"], m["mu11"] / m["m00"]
    spread = np.sqrt(((mu20 - mu02) / 2) ** 2 + mu11**2)
    major, minor = (mu20 + mu02) / 2 + spread, (mu20 + mu02) / 2 - spread
    return float(0.5 * np.degrees(np.arctan2(2 * mu11, mu20 - mu02))), float(np.sqrt(max(minor, 0.0) / max(major, 1e-6))), float(m["m00"])


def spin_events(frames: list[FrameRecord], fps: float, transfers: list[MotionEvent], width: int = 1, height: int = 1) -> list[MotionEvent]:
    """El objeto gira en las manos: su contorno cambia de orientación, de forma o de tamaño
    aparente de un fotograma al siguiente, de forma sostenida.

    Puntuación por fotograma: grados de giro del eje + 100 x cambio de excentricidad + 100 x
    |log| del cambio de área, media en SPIN_WINDOW fotogramas. En video_33 los tramos con anillos
    de la referencia (fotogramas 70-103) superan SPIN_SCORE; el vuelo de un traspaso también,
    por eso sus fotogramas no cuentan.
    """
    score = np.zeros(len(frames))
    held = np.zeros(len(frames), dtype=bool)
    previous = None
    for index, record in enumerate(frames):
        prop = record.prop
        if prop is None:
            previous = None
            continue
        held[index] = prop.state in ("left", "right", "both")
        current = shape_signature(np.array(prop.contour) * [width, height])
        if previous is not None and previous[2] > 0 and current[2] > 0:
            turn = abs((current[0] - previous[0] + 90.0) % 180.0 - 90.0)
            score[index] = turn + 100.0 * abs(current[1] - previous[1]) + 100.0 * abs(np.log(current[2] / previous[2]))
        previous = current
    smooth = np.convolve(score, np.ones(SPIN_WINDOW) / SPIN_WINDOW, mode="same")
    active = (smooth > SPIN_SCORE) & held
    # Los fotogramas de un traspaso (con su anticipación) no cuentan como giro.
    lead = int(round(0.35 * fps))
    for event in transfers:
        for index, record in enumerate(frames):
            if event.start_frame - lead <= record.frame <= event.end_frame:
                active[index] = False
    events: list[MotionEvent] = []
    index = 0
    while index < len(frames):
        if not active[index]:
            index += 1
            continue
        end = index
        while end < len(frames) and active[end]:
            end += 1
        first, last = frames[index].frame, frames[end - 1].frame
        if end - index >= int(SPIN_MIN_S * fps):
            for record in frames[index:end]:
                record.prop.spinning = True
            prop = frames[index].prop
            events.append(
                MotionEvent(
                    name="prop_spin",
                    target=f"{prop.person}:prop",
                    start_frame=first,
                    end_frame=last,
                    confidence=float(min(smooth[index:end].mean() / (2 * SPIN_SCORE), 1.0)),
                    detail=f"El objeto ({prop.label}) gira en las manos.",
                    position=tuple(np.mean(np.array(prop.contour), axis=0).tolist()),
                )
            )
        index = end
    return events


def _es(side: str) -> str:
    return "izquierda" if side == "left" else "derecha"
