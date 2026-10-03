"""Análisis rápido: pose, manos y cara con MediaPipe Tasks."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.names import FACE_KEEP, POSE_NAMES, hand_landmark_name
from vfxglow.analysis.schema import FrameRecord, HandFrame, Landmark, PersonPose
from vfxglow.config import MediaPipeConfig


def _confidence(landmark: object, fallback: float) -> float:
    visibility = getattr(landmark, "visibility", None)
    presence = getattr(landmark, "presence", None)
    values = [float(v) for v in (visibility, presence) if v is not None]
    if not values:
        return fallback
    best = max(values)
    return fallback if best <= 0 else best


def _lm(name: str, x: float, y: float, z: float, c: float) -> Landmark:
    return Landmark(name=name, x=round(float(x), 5), y=round(float(y), 5), z=round(float(z), 5), c=round(float(c), 4))


def _pose_point(pose: list[Landmark], name: str) -> tuple[float, float] | None:
    for lm in pose:
        if lm.name == name and lm.c > 0.05:
            return lm.x, lm.y
    return None


class MediaPipeDetector:
    """Tres landmarkers. Las manos que el video no sigue se buscan en un recorte de la muñeca."""

    def __init__(self, models_dir: Path, cfg: MediaPipeConfig, store_face: bool) -> None:
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision import (
            FaceLandmarker,
            FaceLandmarkerOptions,
            HandLandmarker,
            HandLandmarkerOptions,
            PoseLandmarker,
            PoseLandmarkerOptions,
            RunningMode,
        )

        from vfxglow.analysis.models_store import ensure_model, pose_filename

        pose_path = ensure_model(models_dir, pose_filename(cfg.pose_variant))
        hand_path = ensure_model(models_dir, "hand_landmarker.task")
        self._store_face = store_face
        # CPU: MediaPipe 1.x intenta Metal en macOS y aborta el proceso.
        cpu = BaseOptions(model_asset_path=str(pose_path), delegate=BaseOptions.Delegate.CPU)
        self._next_person = 0
        self._tracks: list[tuple[int, tuple[float, float, float, float]]] = []
        self._pose = PoseLandmarker.create_from_options(
            PoseLandmarkerOptions(
                base_options=cpu,
                running_mode=RunningMode.VIDEO,
                num_poses=max(1, min(int(cfg.num_poses), 2)),
                min_pose_detection_confidence=cfg.detection_confidence,
                min_pose_presence_confidence=cfg.detection_confidence,
                min_tracking_confidence=cfg.tracking_confidence,
            )
        )
        self._hands = HandLandmarker.create_from_options(
            HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(hand_path), delegate=BaseOptions.Delegate.CPU),
                running_mode=RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=cfg.detection_confidence,
                min_hand_presence_confidence=cfg.detection_confidence,
                min_tracking_confidence=cfg.tracking_confidence,
            )
        )
        self._hands_still = HandLandmarker.create_from_options(
            HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(hand_path), delegate=BaseOptions.Delegate.CPU),
                running_mode=RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=cfg.detection_confidence,
                min_hand_presence_confidence=cfg.detection_confidence,
                min_tracking_confidence=cfg.tracking_confidence,
            )
        )
        self._face = None
        self._face_still = None
        if store_face:
            face_path = ensure_model(models_dir, "face_landmarker.task")
            self._face = FaceLandmarker.create_from_options(
                FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(face_path), delegate=BaseOptions.Delegate.CPU),
                    running_mode=RunningMode.VIDEO,
                    num_faces=1,
                    min_face_detection_confidence=cfg.detection_confidence,
                    min_face_presence_confidence=cfg.detection_confidence,
                    min_tracking_confidence=cfg.tracking_confidence,
                )
            )
            # Segundo intento en un recorte de la cabeza: maquillaje y máscaras engañan al detector.
            self._face_still = FaceLandmarker.create_from_options(
                FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(face_path), delegate=BaseOptions.Delegate.CPU),
                    running_mode=RunningMode.IMAGE,
                    num_faces=1,
                    min_face_detection_confidence=0.05,
                    min_face_presence_confidence=0.05,
                )
            )
        self._last_face_box: tuple[float, float, float, float] | None = None
        self._last_face_frame = -(10**9)
        self._last_ts = -1
        self.models = {
            "pose": pose_path.name,
            "hands": hand_path.name,
            "face": "face_landmarker.task" if store_face else "off",
        }

    def close(self) -> None:
        for landmarker in (self._pose, self._hands, self._hands_still, self._face, self._face_still):
            if landmarker is not None:
                landmarker.close()

    def __enter__(self) -> MediaPipeDetector:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def detect(self, index: int, frame_bgr: np.ndarray, fps: float) -> FrameRecord:
        import mediapipe as mp

        rgb = np.ascontiguousarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        ts = int(round(index * 1000.0 / max(fps, 1e-3)))
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts
        height, width = frame_bgr.shape[:2]
        poses = self._read_poses(self._pose.detect_for_video(image, ts))
        hands = self._read_hands(self._hands.detect_for_video(image, ts))
        people = self._track_people(poses)
        claimed: set[int] = set()
        for person in people:
            assigned, claimed = _assign_hands(hands, person.pose, claimed)
            torso = _torso_px(person.pose, width, height)
            for side, wrist_name in (("left", "left_wrist"), ("right", "right_wrist")):
                if assigned[side] is not None:
                    continue
                wrist = _pose_point(person.pose, wrist_name)
                if wrist is None:
                    continue
                cropped = self._detect_hand_crop(rgb, wrist, width, height, torso, side)
                if cropped is not None:
                    assigned[side] = cropped
            person.left_hand = assigned["left"]
            person.right_hand = assigned["right"]
        face = None
        if self._face is not None:
            face = self._read_face(self._face.detect_for_video(image, ts))
            if face is None:
                face = self._face_in_crop(rgb, index, people[0].pose if people else [])
            if face is not None:
                xs = [lm.x for lm in face]
                ys = [lm.y for lm in face]
                self._last_face_box = (min(xs), min(ys), max(xs), max(ys))
                self._last_face_frame = index
        primary = people[0] if people else PersonPose(person_id="person_0")
        return FrameRecord(
            frame=index,
            time_s=index / max(fps, 1e-3),
            person_id=primary.person_id,
            pose=primary.pose,
            left_hand=primary.left_hand,
            right_hand=primary.right_hand,
            face=face,
            box=primary.box,
            people=people,
        )

    def _read_poses(self, result: object) -> list[list[Landmark]]:
        groups = getattr(result, "pose_landmarks", None) or []
        poses: list[list[Landmark]] = []
        for group in groups:
            pose: list[Landmark] = []
            for index, lm in enumerate(group):
                if index >= len(POSE_NAMES):
                    break
                pose.append(_lm(POSE_NAMES[index], lm.x, lm.y, getattr(lm, "z", 0.0), _confidence(lm, 0.0)))
            if pose:
                poses.append(pose)
        return poses

    def _track_people(self, poses: list[list[Landmark]]) -> list[PersonPose]:
        """IDs estables por solapamiento de la caja. Como máximo dos personas."""
        fresh: list[tuple[int, list[Landmark], tuple[float, float, float, float]]] = []
        used: set[int] = set()
        for pose in poses:
            box = _pose_box(pose)
            if box is None:
                continue
            best_i = -1
            best_iou = 0.15
            for index, (pid, previous) in enumerate(self._tracks):
                if index in used:
                    continue
                overlap = _iou(box, previous)
                if overlap > best_iou:
                    best_iou = overlap
                    best_i = index
            if best_i >= 0:
                pid = self._tracks[best_i][0]
                used.add(best_i)
            else:
                pid = self._next_person
                self._next_person += 1
            fresh.append((pid, pose, box))
        fresh.sort(key=lambda item: item[0])
        kept: list[tuple[int, list[Landmark], tuple[float, float, float, float]]] = []
        for pid, pose, box in fresh:
            if any(_iou(box, other) > 0.25 for _pid, _pose, other in kept):
                continue
            kept.append((pid, pose, box))
        fresh = kept[:2]
        self._tracks = [(pid, box) for pid, _pose, box in fresh]
        return [
            PersonPose(person_id=f"person_{slot}", pose=pose, box=box)
            for slot, (_pid, pose, box) in enumerate(fresh)
        ]

    def _read_hands(self, result: object) -> list[HandFrame]:
        groups = getattr(result, "hand_landmarks", None) or []
        hands: list[HandFrame] = []
        for group in groups:
            score = 1.0
            landmarks = [
                _lm(hand_landmark_name("hand", i), lm.x, lm.y, getattr(lm, "z", 0.0), _confidence(lm, score))
                for i, lm in enumerate(group)
            ]
            hands.append(HandFrame(landmarks=landmarks, score=score))
        return hands

    def _face_in_crop(self, rgb: np.ndarray, index: int, pose: list[Landmark]) -> list[Landmark] | None:
        import mediapipe as mp

        if self._face_still is None:
            return None
        height, width = rgb.shape[:2]
        box = None
        if self._last_face_box is not None and index - self._last_face_frame <= 45:
            x0, y0, x1, y1 = self._last_face_box
            cx, cy, side = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, (y1 - y0) * height / width) * 1.8
            box = (cx - side / 2, cy - side * width / height / 2, cx + side / 2, cy + side * width / height / 2)
        else:
            head = [lm for lm in pose if lm.name in {"nose", "left_ear", "right_ear", "left_eye", "right_eye"} and lm.c > 0.3]
            if len(head) >= 2:
                xs = [lm.x for lm in head]
                ys = [lm.y for lm in head]
                cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
                side = max(max(xs) - min(xs), 0.12) * 3.0
                box = (cx - side / 2, cy - side * width / height / 2, cx + side / 2, cy + side * width / height / 2)
        if box is None:
            # Retrato: la cabeza suele estar en el cuadrado superior central.
            side = 0.84
            box = (0.08, 0.1, 0.92, 0.1 + side * width / height)
        x0 = int(max(0, box[0] * width))
        y0 = int(max(0, box[1] * height))
        x1 = int(min(width, box[2] * width))
        y1 = int(min(height, box[3] * height))
        if x1 - x0 < 48 or y1 - y0 < 48:
            return None
        crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
        found = self._read_face(self._face_still.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)))
        if found is None:
            return None
        cw, ch = (x1 - x0) / width, (y1 - y0) / height
        placed = [lm.model_copy(update={"x": x0 / width + lm.x * cw, "y": y0 / height + lm.y * ch, "c": min(lm.c, 0.6)}) for lm in found]
        xs = [lm.x for lm in placed]
        if max(xs) - min(xs) < 0.06:
            return None
        return placed

    def _read_face(self, result: object) -> list[Landmark] | None:
        groups = getattr(result, "face_landmarks", None) or []
        if not groups:
            return None
        return [
            _lm(f"face_{i}", lm.x, lm.y, 0.0, _confidence(lm, 0.8))
            for i, lm in enumerate(groups[0])
            if i in FACE_KEEP
        ]

    def _detect_hand_crop(
        self,
        rgb: np.ndarray,
        wrist: tuple[float, float],
        width: int,
        height: int,
        torso: float,
        side: str,
    ) -> HandFrame | None:
        import mediapipe as mp

        side_px = max(torso * 0.95, min(width, height) * 0.18)
        cx, cy = wrist[0] * width, wrist[1] * height
        x0 = int(max(0, cx - side_px))
        y0 = int(max(0, cy - side_px))
        x1 = int(min(width, cx + side_px))
        y1 = int(min(height, cy + side_px))
        if x1 - x0 < 16 or y1 - y0 < 16:
            return None
        crop = np.ascontiguousarray(rgb[y0:y1, x0:x1])
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)
        result = self._hands_still.detect(image)
        groups = getattr(result, "hand_landmarks", None) or []
        if not groups:
            return None
        crop_w = max(x1 - x0, 1)
        crop_h = max(y1 - y0, 1)
        landmarks = []
        for i, lm in enumerate(groups[0]):
            landmarks.append(
                _lm(
                    hand_landmark_name(side, i),
                    (x0 + lm.x * crop_w) / width,
                    (y0 + lm.y * crop_h) / height,
                    getattr(lm, "z", 0.0),
                    _confidence(lm, 0.6),
                )
            )
        return HandFrame(landmarks=landmarks, score=0.6)


def _assign_hands(
    hands: list[HandFrame],
    pose: list[Landmark],
    claimed: set[int],
) -> tuple[dict[str, HandFrame | None], set[int]]:
    assigned: dict[str, HandFrame | None] = {"left": None, "right": None}
    owners: dict[str, int] = {}
    left = _pose_point(pose, "left_wrist")
    right = _pose_point(pose, "right_wrist")
    for index, hand in enumerate(hands):
        if index in claimed or not hand.landmarks:
            continue
        wrist = hand.landmarks[0]
        dl = _dist((wrist.x, wrist.y), left)
        dr = _dist((wrist.x, wrist.y), right)
        side = "left" if dl <= dr else "right"
        renamed = HandFrame(
            landmarks=[
                _lm(hand_landmark_name(side, i), lm.x, lm.y, lm.z, lm.c) for i, lm in enumerate(hand.landmarks)
            ],
            score=hand.score,
        )
        current = assigned[side]
        if current is None or renamed.score >= current.score:
            assigned[side] = renamed
            owners[side] = index
    claimed = set(claimed)
    claimed.update(owners.values())
    return assigned, claimed


def _pose_box(pose: list[Landmark]) -> tuple[float, float, float, float] | None:
    xs = [lm.x for lm in pose if lm.c > 0.1]
    ys = [lm.y for lm in pose if lm.c > 0.1]
    if len(xs) < 4:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    if union <= 1e-8:
        return 0.0
    return inter / union


def _dist(a: tuple[float, float], b: tuple[float, float] | None) -> float:
    if b is None:
        return 1e9
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def _torso_px(pose: list[Landmark], width: int, height: int) -> float:
    left_s = _pose_point(pose, "left_shoulder")
    right_s = _pose_point(pose, "right_shoulder")
    left_h = _pose_point(pose, "left_hip")
    right_h = _pose_point(pose, "right_hip")
    if not all((left_s, right_s, left_h, right_h)):
        return float(min(width, height) * 0.25)
    sx = (left_s[0] + right_s[0]) * 0.5 * width
    sy = (left_s[1] + right_s[1]) * 0.5 * height
    hx = (left_h[0] + right_h[0]) * 0.5 * width
    hy = (left_h[1] + right_h[1]) * 0.5 * height
    return float(max(np.hypot(sx - hx, sy - hy), 1.0))
