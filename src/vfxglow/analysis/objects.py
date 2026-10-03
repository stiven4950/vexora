"""Detección y seguimiento de objetos. YOLO si está instalado; si no, vacío con aviso."""

from __future__ import annotations

import logging

import numpy as np

from vfxglow.analysis.schema import FrameRecord, ObjectDet
from vfxglow.config import ObjectsConfig

log = logging.getLogger("vfxglow.objects")


def yolo_available() -> bool:
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        return False
    return True


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    inter = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    area_a = max(a[2] - a[0], 0.0) * max(a[3] - a[1], 0.0)
    area_b = max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)
    union = area_a + area_b - inter
    return inter / union if union > 1e-9 else 0.0


class ObjectTracker:
    """Asocia detecciones entre fotogramas por IoU y centroide, y asigna ids estables."""

    def __init__(self, cfg: ObjectsConfig, device: str) -> None:
        self.cfg = cfg
        self.device = device
        self._model = None
        self._next_id = 0
        self._tracks: dict[int, ObjectDet] = {}
        self._missing: dict[int, int] = {}
        self.enabled = cfg.enabled and yolo_available()
        if cfg.enabled and not self.enabled:
            log.warning("objects.enabled está activo pero ultralytics no está instalado. Instala 'vfxglow[objects]'.")

    def _load(self):
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(self.cfg.model)
        return self._model

    def detect(self, frame_bgr: np.ndarray) -> list[ObjectDet]:
        if not self.enabled:
            return []
        model = self._load()
        height, width = frame_bgr.shape[:2]
        device = "cuda" if self.device == "cuda" else ("mps" if self.device == "mps" else "cpu")
        result = model.predict(frame_bgr, verbose=False, conf=self.cfg.confidence, device=device)[0]
        found: list[ObjectDet] = []
        if result.boxes is None:
            return found
        names = result.names
        wanted = {label.lower() for label in self.cfg.labels_of_interest}
        for box in result.boxes:
            cls = int(box.cls[0])
            label = str(names.get(cls, cls)).lower()
            if label == "person":
                continue
            if wanted and label not in wanted:
                continue
            x0, y0, x1, y1 = box.xyxy[0].tolist()
            found.append(
                ObjectDet(
                    label=label,
                    conf=float(box.conf[0]),
                    box=(x0 / width, y0 / height, x1 / width, y1 / height),
                )
            )
        return found

    def update(self, detections: list[ObjectDet]) -> list[ObjectDet]:
        """Empareja con los tracks vivos y devuelve detecciones con id y velocidad."""
        assigned: list[ObjectDet] = []
        used: set[int] = set()
        for det in sorted(detections, key=lambda d: -d.conf):
            best_id = -1
            best_score = 0.0
            for track_id, prev in self._tracks.items():
                if track_id in used or prev.label != det.label:
                    continue
                score = _iou(prev.box, det.box)
                if score < 0.15:
                    pc = prev.center
                    dc = det.center
                    dist = float(np.hypot(pc[0] - dc[0], pc[1] - dc[1]))
                    size = max(prev.box[2] - prev.box[0], prev.box[3] - prev.box[1], 0.02)
                    if dist < size * 0.9:
                        score = 0.15 + (1.0 - dist / (size * 0.9)) * 0.1
                if score > best_score:
                    best_score = score
                    best_id = track_id
            if best_id < 0:
                best_id = self._next_id
                self._next_id += 1
                velocity = (0.0, 0.0)
            else:
                pc = self._tracks[best_id].center
                dc = det.center
                velocity = (dc[0] - pc[0], dc[1] - pc[1])
            used.add(best_id)
            tracked = det.model_copy(update={"id": best_id, "velocity": velocity})
            self._tracks[best_id] = tracked
            self._missing[best_id] = 0
            assigned.append(tracked)
        for track_id in list(self._tracks):
            if track_id not in used:
                self._missing[track_id] = self._missing.get(track_id, 0) + 1
                if self._missing[track_id] > 12:
                    del self._tracks[track_id]
                    del self._missing[track_id]
        return assigned

    def carry(self) -> list[ObjectDet]:
        """Fotograma sin detección: propaga los tracks vivos con su velocidad."""
        out: list[ObjectDet] = []
        for track_id, prev in list(self._tracks.items()):
            if self._missing.get(track_id, 0) > 2:
                continue
            vx, vy = prev.velocity
            box = (prev.box[0] + vx, prev.box[1] + vy, prev.box[2] + vx, prev.box[3] + vy)
            moved = prev.model_copy(update={"box": box})
            self._tracks[track_id] = moved
            out.append(moved)
        return out


def attach_objects(tracker: ObjectTracker, frames: list[FrameRecord], plates: list[np.ndarray]) -> None:
    """Rellena `objects` de cada fotograma. Detecta cada `stride` y propaga entre medias."""
    if not tracker.enabled:
        return
    stride = max(tracker.cfg.stride, 1)
    for index, (frame, plate) in enumerate(zip(frames, plates, strict=False)):
        if index % stride == 0:
            frame.objects = tracker.update(tracker.detect(plate))
        else:
            frame.objects = tracker.carry()
