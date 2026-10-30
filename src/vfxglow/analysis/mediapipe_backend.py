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


# Altura mínima de la segunda persona respecto a la primera para aceptarla.
SECOND_MIN_SCALE = 0.5
# Peso de la firma nueva en la media de cada casilla.
SIGNATURE_RATE = 0.05


def torso_signature(frame_bgr: np.ndarray, pose: list[Landmark]) -> np.ndarray | None:
    """Histograma tono-saturación del torso (hombros a caderas), normalizado."""
    pts = {lm.name: (lm.x, lm.y) for lm in pose if lm.c > 0.3}
    need = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
    if not all(name in pts for name in need):
        return None
    height, width = frame_bgr.shape[:2]
    xs = [pts[name][0] * width for name in need]
    ys = [pts[name][1] * height for name in need]
    x0, x1 = int(max(0, min(xs))), int(min(width, max(xs)))
    y0, y1 = int(max(0, min(ys))), int(min(height, max(ys)))
    # Recorte interior: el borde del torso se mezcla con el fondo.
    dx, dy = (x1 - x0) // 5, (y1 - y0) // 6
    patch = frame_bgr[y0 + dy : y1 - dy, x0 + dx : x1 - dx]
    if patch.size < 300:
        return None
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 1.0, 0.0, cv2.NORM_L1)
    return hist


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
        # Por casilla (person_0, person_1): firma de color del torso y última caja vista.
        # La firma decide la identidad; la caja solo desempata. Así una persona que se tapa o
        # sale un momento recupera su nombre (y su color) al volver.
        self._signature: dict[int, np.ndarray] = {}
        self._last_box: dict[int, tuple[float, float, float, float]] = {}
        self._second = None
        if int(cfg.num_poses) >= 2 and cfg.second_pass_confidence > 0:
            self._second = PoseLandmarker.create_from_options(
                PoseLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(pose_path), delegate=BaseOptions.Delegate.CPU),
                    running_mode=RunningMode.IMAGE,
                    num_poses=1,
                    min_pose_detection_confidence=cfg.second_pass_confidence,
                    min_pose_presence_confidence=cfg.second_pass_confidence,
                )
            )
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
                    output_face_blendshapes=True,
                    output_facial_transformation_matrixes=True,
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
                    output_face_blendshapes=True,
                    output_facial_transformation_matrixes=True,
                    min_face_detection_confidence=0.05,
                    min_face_presence_confidence=0.05,
                )
            )
        self._crop_extras: tuple[dict[str, float], tuple[float, float, float] | None] = ({}, None)
        self._last_face_box: tuple[float, float, float, float] | None = None
        self._last_face_frame = -(10**9)
        self._last_ts = -1
        self.models = {
            "pose": pose_path.name,
            "hands": hand_path.name,
            "face": "face_landmarker.task" if store_face else "off",
        }

    def close(self) -> None:
        for landmarker in (self._pose, self._hands, self._hands_still, self._face, self._face_still, self._second):
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
        if len(poses) == 1 and self._second is not None:
            poses += self._find_second(frame_bgr, poses[0])
        hands = self._read_hands(self._hands.detect_for_video(image, ts))
        people = self._track_people(poses, frame_bgr)
        claimed: set[int] = set()
        for person in people:
            torso = _torso_px(person.pose, width, height)
            assigned, claimed = _assign_hands(hands, person.pose, claimed, torso / max(min(width, height), 1))
            for side, wrist_name in (("left", "left_wrist"), ("right", "right_wrist")):
                # Sin mano, o con una tan chica que sus dedos no son fiables: se busca otra vez en un
                # recorte ampliado alrededor de la muñeca.
                if assigned[side] is not None and _hand_px(assigned[side], width, height) >= SMALL_HAND_PX:
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
        expressions: dict[str, float] = {}
        head_pose: tuple[float, float, float] | None = None
        if self._face is not None:
            face_result = self._face.detect_for_video(image, ts)
            face = self._read_face(face_result)
            expressions, head_pose = _face_extras(face_result)
            if face is None:
                face = self._face_in_crop(rgb, index, people[0].pose if people else [])
                expressions, head_pose = self._crop_extras
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
            expressions=expressions,
            head_pose=head_pose,
            box=primary.box,
            people=people,
        )

    def _find_second(self, frame_bgr: np.ndarray, first: list[Landmark]) -> list[list[Landmark]]:
        """Tapa a la persona encontrada y busca otra en el resto del cuadro."""
        import mediapipe as mp

        box = _pose_box(first)
        if box is None:
            return []
        height, width = frame_bgr.shape[:2]
        pad = 0.04
        masked = frame_bgr.copy()
        masked[
            max(0, int((box[1] - pad) * height)) : int((box[3] + pad) * height),
            max(0, int((box[0] - pad) * width)) : int((box[2] + pad) * width),
        ] = 127
        rgb = np.ascontiguousarray(cv2.cvtColor(masked, cv2.COLOR_BGR2RGB))
        found = self._read_poses(self._second.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)))
        other = _pose_box(found[0]) if found else None
        # Un peatón al fondo también es una persona: solo vale alguien de escala parecida.
        if other is None or (other[3] - other[1]) < SECOND_MIN_SCALE * (box[3] - box[1]):
            return []
        return found[:1]

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

    def _track_people(self, poses: list[list[Landmark]], frame_bgr: np.ndarray) -> list[PersonPose]:
        """Como máximo dos personas en casillas estables, por apariencia del torso."""
        found: list[tuple[list[Landmark], tuple[float, float, float, float], np.ndarray | None]] = []
        for pose in poses:
            box = _pose_box(pose)
            if box is None or any(_iou(box, other) > 0.25 for _pose, other, _sig in found):
                continue
            found.append((pose, box, torso_signature(frame_bgr, pose)))
        found = found[:2]
        if not found:
            return []
        assignment = self._assign_slots(found)
        people = []
        for (pose, box, signature), slot in zip(found, assignment, strict=True):
            if signature is not None:
                previous = self._signature.get(slot)
                self._signature[slot] = signature if previous is None else previous * (1 - SIGNATURE_RATE) + signature * SIGNATURE_RATE
            self._last_box[slot] = box
            people.append(PersonPose(person_id=f"person_{slot}", pose=pose, box=box))
        return sorted(people, key=lambda person: person.person_id)

    def _assign_slots(self, found) -> list[int]:
        """Casilla de cada pose: la de firma más parecida; sin firmas, la de caja más cercana."""
        def cost(item, slot: int) -> float:
            _pose, box, signature = item
            reference = self._signature.get(slot)
            if signature is not None and reference is not None:
                return 1.0 - float(cv2.compareHist(signature, reference, cv2.HISTCMP_CORREL))
            last = self._last_box.get(slot)
            if last is not None:
                return 1.0 - _iou(box, last) + 0.5
            # Casilla nunca vista: por orden de izquierda a derecha.
            return 2.0 + (box[0] if slot == 0 else 1.0 - box[0])

        if len(found) == 1:
            return [min((0, 1), key=lambda slot: cost(found[0], slot))]
        straight = cost(found[0], 0) + cost(found[1], 1)
        crossed = cost(found[0], 1) + cost(found[1], 0)
        return [0, 1] if straight <= crossed else [1, 0]

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

        self._crop_extras: tuple[dict[str, float], tuple[float, float, float] | None] = ({}, None)
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
        result = self._face_still.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
        found = self._read_face(result)
        if found is None:
            return None
        self._crop_extras = _face_extras(result)
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
        zoom = HAND_ZOOM_PX / max(x1 - x0, y1 - y0)
        if zoom > 1.0:  # una mano de 15-20 px se agranda antes de buscar sus dedos
            crop = np.ascontiguousarray(cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC))
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


# Manos chicas (video_52: 15-20 px): la palma por debajo de esto se vuelve a buscar en un recorte
# ampliado a HAND_ZOOM_PX (el detector trabaja a 224 px). Una mano cuya muñeca queda a más de
# HAND_WRIST_MAX torsos de la muñeca de la pose no es de esa persona.
SMALL_HAND_PX = 18.0
HAND_ZOOM_PX = 320
HAND_WRIST_MAX = 0.35


# Expresiones de la cara que usan los efectos (analysis/expressions.py): de las 52 de MediaPipe.
EXPRESSIONS = (
    "jawOpen", "eyeBlinkLeft", "eyeBlinkRight", "eyeWideLeft", "eyeWideRight", "mouthSmileLeft",
    "mouthSmileRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "cheekPuff", "mouthPucker",
    "mouthFunnel", "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft", "eyeLookOutRight", "eyeLookUpLeft",
    "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight", "browDownLeft", "browDownRight", "mouthFrownLeft",
    "mouthFrownRight", "eyeSquintLeft", "eyeSquintRight",
)


def _face_extras(result: object) -> tuple[dict[str, float], tuple[float, float, float] | None]:
    """(expresiones, orientación de la cabeza en grados: giro, cabeceo, inclinación) de una cara."""
    expressions: dict[str, float] = {}
    shapes = getattr(result, "face_blendshapes", None) or []
    if shapes:
        expressions = {c.category_name: round(float(c.score), 3) for c in shapes[0] if c.category_name in EXPRESSIONS}
    head = None
    matrices = getattr(result, "facial_transformation_matrixes", None)
    if matrices is not None and len(matrices):
        r = np.asarray(matrices[0], dtype=np.float64)[:3, :3]
        yaw = float(np.degrees(np.arctan2(r[0, 2], r[2, 2])))
        pitch = float(np.degrees(np.arcsin(np.clip(-r[1, 2], -1.0, 1.0))))
        roll = float(np.degrees(np.arctan2(r[1, 0], r[1, 1])))
        head = (round(yaw, 2), round(pitch, 2), round(roll, 2))
    return expressions, head


def _hand_px(hand: HandFrame, width: int, height: int) -> float:
    """Largo de la palma (muñeca al nudillo del medio) en píxeles."""
    if len(hand.landmarks) < 10:
        return 0.0
    wrist, knuckle = hand.landmarks[0], hand.landmarks[9]
    return float(np.hypot((wrist.x - knuckle.x) * width, (wrist.y - knuckle.y) * height))


def _assign_hands(
    hands: list[HandFrame],
    pose: list[Landmark],
    claimed: set[int],
    torso: float = 1.0,
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
        if min(dl, dr) > HAND_WRIST_MAX * torso:
            continue  # su muñeca no es la de esta persona: es otra mano (del público) o un error
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
