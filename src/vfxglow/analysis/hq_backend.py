"""Análisis de mayor precisión: cuerpo completo con RTMW.

Los objetos ya no se detectan aquí. El analizador usa `analysis/objects.py`
tanto en `fast` como en `hq`, para que el tracker de identidad sea el mismo.
"""

from __future__ import annotations

from vfxglow.analysis.names import HAND_PARTS, hand_landmark_name
from vfxglow.analysis.schema import FrameRecord, HandFrame, Landmark

# COCO-WholeBody: 17 cuerpo, 6 pies, 68 cara, 21 mano izquierda, 21 mano derecha.
_BODY = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)
_FEET = (
    "left_foot_index",
    "left_foot_index",
    "left_heel",
    "right_foot_index",
    "right_foot_index",
    "right_heel",
)


class HQDetector:
    def __init__(self, pose_mode: str, device: str) -> None:
        try:
            from rtmlib import Wholebody
        except ImportError as exc:
            raise RuntimeError(
                "El nivel hq necesita los extras de análisis: pip install 'vfxglow[hq]'."
            ) from exc
        onnx_device = "cuda" if device == "cuda" else "cpu"
        self._pose = Wholebody(to_openpose=False, mode=pose_mode, backend="onnxruntime", device=onnx_device)
        self.models = {"pose": f"rtmw-{pose_mode}", "face": "wholebody68"}

    def detect(self, index: int, frame_bgr, fps: float, store_face: bool) -> FrameRecord:
        height, width = frame_bgr.shape[:2]
        keypoints, scores = self._pose(frame_bgr)
        pose: list[Landmark] = []
        left = HandFrame(landmarks=[], score=0.0)
        right = HandFrame(landmarks=[], score=0.0)
        face: list[Landmark] | None = None
        chosen = _largest_person(keypoints, scores)
        if chosen is not None:
            pts, sc = chosen
            pose = _body_landmarks(pts, sc, width, height)
            left = _hand(pts, sc, 91, "left", width, height)
            right = _hand(pts, sc, 112, "right", width, height)
            if store_face:
                face = _face68(pts, sc, width, height)
        return FrameRecord(
            frame=index,
            time_s=index / max(fps, 1e-3),
            pose=pose,
            left_hand=left if left.landmarks else None,
            right_hand=right if right.landmarks else None,
            face=face,
        )

    def close(self) -> None:
        return None


def _largest_person(keypoints, scores):
    if keypoints is None or len(keypoints) == 0:
        return None
    best = None
    best_area = -1.0
    for pts, sc in zip(keypoints, scores, strict=False):
        valid = pts[sc > 0.2]
        if len(valid) < 4:
            continue
        width = float(valid[:, 0].max() - valid[:, 0].min())
        height = float(valid[:, 1].max() - valid[:, 1].min())
        area = width * height
        if area > best_area:
            best_area = area
            best = (pts, sc)
    return best


def _norm_lm(name: str, x: float, y: float, c: float, width: int, height: int) -> Landmark:
    return Landmark(
        name=name,
        x=round(float(x) / max(width, 1), 5),
        y=round(float(y) / max(height, 1), 5),
        z=0.0,
        c=round(float(c), 4),
    )


def _body_landmarks(pts, scores, width: int, height: int) -> list[Landmark]:
    out: list[Landmark] = []
    for i, name in enumerate(_BODY):
        out.append(_norm_lm(name, pts[i, 0], pts[i, 1], scores[i], width, height))
    for i, name in enumerate(_FEET):
        idx = 17 + i
        if name in {lm.name for lm in out}:
            continue
        out.append(_norm_lm(name, pts[idx, 0], pts[idx, 1], scores[idx], width, height))
    return out


def _hand(pts, scores, start: int, side: str, width: int, height: int) -> HandFrame:
    landmarks = []
    confs = []
    for i, part in enumerate(HAND_PARTS):
        idx = start + i
        confs.append(float(scores[idx]))
        landmarks.append(_norm_lm(hand_landmark_name(side, i), pts[idx, 0], pts[idx, 1], scores[idx], width, height))
    return HandFrame(landmarks=landmarks, score=float(sum(confs) / max(len(confs), 1)))


def _face68(pts, scores, width: int, height: int) -> list[Landmark]:
    return [
        _norm_lm(f"face68_{i}", pts[23 + i, 0], pts[23 + i, 1], scores[23 + i], width, height)
        for i in range(68)
    ]
