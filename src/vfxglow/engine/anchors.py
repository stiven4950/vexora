"""Anclas en píxeles a partir de un fotograma analizado."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.names import CHAINS, FACE_FEATURES, FACE_NAMED
from vfxglow.analysis.schema import FrameRecord, Landmark


class PointSet(dict):
    """Anclas en píxeles, con la confianza y el detector de origen de cada una.

    Se comporta como un dict de nombre -> punto, así que los efectos no cambian. La capa de
    restricciones lee `confidence()` y `origin()` para degradar un efecto en vez de dibujarlo a ciegas.
    Un punto sin dato registrado (derivado, o añadido por un efecto) cuenta como confianza 1.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.conf: dict[str, float] = {}
        self.source: dict[str, str] = {}

    def put(self, name: str, value: np.ndarray, conf: float = 1.0, source: str = "derived") -> None:
        self[name] = value
        self.conf[name] = conf
        self.source[name] = source

    def confidence(self, name: str) -> float:
        return self.conf.get(name, 1.0)

    def origin(self, name: str) -> str:
        return self.source.get(name, "derived")


def _put(points: PointSet, lm: Landmark, width: int, height: int, source: str) -> None:
    if lm.c <= 0:
        return
    points.put(lm.name, np.array([lm.x * width, lm.y * height], dtype=np.float64), float(lm.c), source)


def collect_points(track: FrameRecord | None, width: int, height: int) -> PointSet:
    points = PointSet()
    if track is None:
        return points
    for lm in track.pose:
        _put(points, lm, width, height, "pose")
    for hand in (track.left_hand, track.right_hand):
        if hand is None:
            continue
        for lm in hand.landmarks:
            _put(points, lm, width, height, "hand")
    if track.face:
        for lm in track.face:
            _put(points, lm, width, height, "face_mesh")
    for lm in track.fallback:
        _put(points, lm, width, height, "fallback")
    if "left_shoulder" in points and "right_shoulder" in points:
        points["mid_shoulder"] = (points["left_shoulder"] + points["right_shoulder"]) * 0.5
    if "left_hip" in points and "right_hip" in points:
        points["mid_hip"] = (points["left_hip"] + points["right_hip"]) * 0.5
    if "mouth_left" in points and "mouth_right" in points:
        points["mouth"] = (points["mouth_left"] + points["mouth_right"]) * 0.5
    if "nose" in points:
        points["head_top"] = points["nose"] - np.array([0.0, height * 0.08])
    if "mid_shoulder" in points and "nose" in points:
        points["neck"] = (points["mid_shoulder"] + points["nose"]) * 0.5
    elif "mid_shoulder" in points:
        points["neck"] = points["mid_shoulder"].copy()
    for person in track.people:
        for lm in person.pose:
            if lm.c <= 0:
                continue
            points[f"{person.person_id}:{lm.name}"] = np.array([lm.x * width, lm.y * height], dtype=np.float64)
        if f"{person.person_id}:left_shoulder" in points and f"{person.person_id}:right_shoulder" in points:
            points[f"{person.person_id}:mid_shoulder"] = (
                points[f"{person.person_id}:left_shoulder"] + points[f"{person.person_id}:right_shoulder"]
            ) * 0.5
    for blade in track.blades:
        # person_N:blade_<mano>_tip / _hilt; la persona principal también sin prefijo.
        for part, value in (("tip", blade.tip), ("hilt", blade.hilt)):
            point = np.array([value[0] * width, value[1] * height], dtype=np.float64)
            points.put(f"{blade.person}:blade_{blade.hand}_{part}", point, blade.confidence, f"blade_{blade.source}")
            if blade.person == track.person_id:
                points.put(f"blade_{blade.hand}_{part}", point, blade.confidence, f"blade_{blade.source}")
    for obj in track.objects:
        center = np.array(
            [((obj.box[0] + obj.box[2]) * 0.5) * width, ((obj.box[1] + obj.box[3]) * 0.5) * height],
            dtype=np.float64,
        )
        points[f"object:{obj.id}"] = center
        points[f"object:{obj.label}"] = center
        if "object:any" not in points:
            points["object:any"] = center
    add_face_points(points)
    return points


def add_face_points(points: dict[str, np.ndarray]) -> None:
    for name, index in FACE_NAMED.items():
        key = f"face_{index}"
        if key in points:
            points[name] = points[key]
            if isinstance(points, PointSet) and key in points.source:
                points.conf[name] = points.conf[key]
                points.source[name] = points.source[key]
    for side in ("right", "left"):
        iris = f"{side}_iris"
        if iris not in points:
            ring = [points[f"face_{i}"] for i in FACE_FEATURES[f"{side}_eye"][:-1] if f"face_{i}" in points]
            if len(ring) >= 4:
                points[iris] = np.mean(ring, axis=0)
    if "right_iris" in points and "left_iris" in points:
        points["face_center"] = (points["right_iris"] + points["left_iris"]) * 0.5
    elif "right_eye" in points and "left_eye" in points:
        points["face_center"] = (points["right_eye"] + points["left_eye"]) * 0.5
    if "upper_lip" in points and "lower_lip" in points:
        points["mouth_center"] = (points["upper_lip"] + points["lower_lip"]) * 0.5


def feature_polyline(points: dict[str, np.ndarray], feature: str) -> np.ndarray | None:
    chain = FACE_FEATURES.get(feature)
    if chain is None:
        return None
    found = [points[f"face_{i}"] for i in chain if f"face_{i}" in points]
    if len(found) < max(3, len(chain) // 2):
        return None
    return np.stack(found)


def local_frame(points: dict[str, np.ndarray], space: str) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Origen y ejes (ya escalados) del espacio de dibujo.

    face: (0,0) entre los ojos, ojos en x=±0.5, barbilla cerca de y=1.5.
    body: (0,0) entre los hombros, hombros en x=±0.5, caderas cerca de y=1.3.
    hand: (0,0) en la muñeca, unidad = ancho de hombros.
    """
    if space == "face":
        a = points.get("right_iris", points.get("right_eye"))
        b = points.get("left_iris", points.get("left_eye"))
    else:
        a = points.get("right_shoulder")
        b = points.get("left_shoulder")
    if a is None or b is None:
        return None
    if a[0] > b[0]:
        a, b = b, a
    ux = b - a
    if float(np.linalg.norm(ux)) < 4.0:
        return None
    uy = np.array([-ux[1], ux[0]])
    if space == "face":
        origin = (a + b) * 0.5
    elif space in {"left_hand", "right_hand"}:
        origin = points.get(space.replace("hand", "wrist"))
        if origin is None:
            return None
    else:
        origin = (a + b) * 0.5
    return origin, ux, uy


def to_image(local: np.ndarray, frame: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    origin, ux, uy = frame
    return origin + local[:, :1] * ux + local[:, 1:2] * uy


def chain_points(points: dict[str, np.ndarray], name: str) -> np.ndarray | None:
    names = CHAINS.get(name)
    if names is None:
        return None
    if any(item not in points for item in names):
        return None
    return np.stack([points[item] for item in names])


def torso_pixels(points: dict[str, np.ndarray], height: int) -> float:
    if "mid_shoulder" in points and "mid_hip" in points:
        return float(max(np.linalg.norm(points["mid_shoulder"] - points["mid_hip"]), 8.0))
    return float(max(height * 0.22, 8.0))


def joint_speed(track: FrameRecord | None, name: str) -> float:
    owner, joint = _owner(track, name)
    if owner is None:
        return 0.0
    for item in owner.motion:
        if item.name == joint:
            return float(item.speed)
    return 0.0


def _owner(track: FrameRecord | None, name: str):
    if track is None:
        return None, name
    if name.startswith("person_") and ":" in name:
        person_id, joint = name.split(":", 1)
        for person in track.people:
            if person.person_id == person_id:
                return person, joint
    return track, name


def joint_velocity(track: FrameRecord | None, name: str) -> tuple[float, float]:
    """Velocidad normalizada (fracción de ancho/alto por fotograma)."""
    owner, joint = _owner(track, name)
    if owner is None:
        return 0.0, 0.0
    for item in owner.motion:
        if item.name == joint:
            return float(item.vx), float(item.vy)
    return 0.0, 0.0


def resolve_anchor(
    points: dict[str, np.ndarray],
    kind: str,
    name: str,
    event_point: np.ndarray | None = None,
) -> np.ndarray | None:
    if kind == "event_point":
        if event_point is not None:
            return event_point
        return points.get("event_point")
    if kind == "object":
        for key in (f"object:{name}", name, "object:any"):
            if key in points:
                return points[key]
        return None
    return points.get(name)
