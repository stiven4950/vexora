"""Nombres de anclas compartidos por el análisis, el director y el motor."""

from __future__ import annotations

POSE_NAMES: tuple[str, ...] = (
    "nose",
    "left_eye_inner",
    "left_eye",
    "left_eye_outer",
    "right_eye_inner",
    "right_eye",
    "right_eye_outer",
    "left_ear",
    "right_ear",
    "mouth_left",
    "mouth_right",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_pinky",
    "right_pinky",
    "left_index",
    "right_index",
    "left_thumb",
    "right_thumb",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_heel",
    "right_heel",
    "left_foot_index",
    "right_foot_index",
)

HAND_PARTS: tuple[str, ...] = (
    "wrist",
    "thumb_cmc",
    "thumb_mcp",
    "thumb_ip",
    "thumb_tip",
    "index_mcp",
    "index_pip",
    "index_dip",
    "index_tip",
    "middle_mcp",
    "middle_pip",
    "middle_dip",
    "middle_tip",
    "ring_mcp",
    "ring_pip",
    "ring_dip",
    "ring_tip",
    "pinky_mcp",
    "pinky_pip",
    "pinky_dip",
    "pinky_tip",
)

BONES: tuple[tuple[str, str], ...] = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
    ("nose", "left_shoulder"),
    ("nose", "right_shoulder"),
)

CHAINS: dict[str, tuple[str, ...]] = {
    "left_arm": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_arm": ("right_shoulder", "right_elbow", "right_wrist"),
    "left_leg": ("left_hip", "left_knee", "left_ankle"),
    "right_leg": ("right_hip", "right_knee", "right_ankle"),
    "spine": ("mid_shoulder", "mid_hip"),
    "torso": ("left_shoulder", "right_shoulder", "right_hip", "left_hip", "left_shoulder"),
}

LIMB_JOINTS: dict[str, str] = {
    "right_hand": "right_wrist",
    "left_hand": "left_wrist",
    "right_arm": "right_elbow",
    "left_arm": "left_elbow",
    "right_leg": "right_ankle",
    "left_leg": "left_ankle",
    "head": "nose",
}

FACE_REGIONS: tuple[str, ...] = ("face_oval", "forehead", "cheeks")

# Contorno facial de MediaPipe Face Landmarker (478 puntos).
FACE_OVAL: tuple[int, ...] = (
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109,
)
FOREHEAD: tuple[int, ...] = (10, 67, 109, 338, 297, 332)
CHEEKS: tuple[tuple[int, ...], ...] = (
    (234, 93, 132, 58, 172),
    (454, 323, 361, 288, 397),
)

# Rasgos de la malla. "right" y "left" son de la persona, como en la pose.
# Las cerradas terminan donde empiezan.
FACE_FEATURES: dict[str, tuple[int, ...]] = {
    "right_eye": (33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7, 33),
    "left_eye": (362, 398, 384, 385, 386, 387, 388, 466, 263, 249, 390, 373, 374, 380, 381, 382, 362),
    "right_brow": (46, 53, 52, 65, 55, 107, 66, 105, 63, 70),
    "left_brow": (276, 283, 282, 295, 285, 336, 296, 334, 293, 300),
    "lips_outer": (61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146, 61),
    "lips_inner": (78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78),
    "nose_bridge": (168, 6, 197, 195, 5, 4),
    "nose_base": (98, 97, 2, 326, 327),
    "face_oval": FACE_OVAL + (FACE_OVAL[0],),
}
FACE_FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "eyes": ("right_eye", "left_eye"),
    "brows": ("right_brow", "left_brow"),
    "lips": ("lips_outer", "lips_inner"),
    "nose": ("nose_bridge", "nose_base"),
    "oval": ("face_oval",),
}
# Iris: centro y cuatro bordes.
RIGHT_IRIS: tuple[int, ...] = (468, 469, 470, 471, 472)
LEFT_IRIS: tuple[int, ...] = (473, 474, 475, 476, 477)
# Puntos sueltos que el motor expone como anclas con nombre.
FACE_NAMED: dict[str, int] = {
    "right_iris": 468,
    "left_iris": 473,
    "nose_tip": 4,
    "chin": 152,
    "forehead_top": 10,
    "upper_lip": 13,
    "lower_lip": 14,
}
FACE_ANCHORS: tuple[str, ...] = (*FACE_NAMED, "face_center", "mouth_center")
# Solo se guardan estos índices: la malla entera son 478 puntos por fotograma.
FACE_KEEP: frozenset[int] = frozenset(
    {i for chain in FACE_FEATURES.values() for i in chain}
    | set(RIGHT_IRIS)
    | set(LEFT_IRIS)
    | set(FACE_NAMED.values())
    | set(FOREHEAD)
    | {i for cheek in CHEEKS for i in cheek}
)

# Contorno de 68 puntos (whole-body): mandíbula 0-16.
FACE68_JAW: tuple[int, ...] = tuple(range(17))
FACE68_BROWS: tuple[int, ...] = tuple(range(17, 27))

VIRTUAL_JOINTS: tuple[str, ...] = ("mid_shoulder", "mid_hip", "neck")

MOTION_JOINTS: tuple[str, ...] = (
    "nose",
    "left_wrist",
    "right_wrist",
    "left_elbow",
    "right_elbow",
    "left_ankle",
    "right_ankle",
)


def hand_landmark_name(side: str, index: int) -> str:
    return f"{side}_{HAND_PARTS[index]}"


def known_joint_names() -> set[str]:
    names = set(POSE_NAMES) | set(VIRTUAL_JOINTS)
    for side in ("left", "right"):
        for part in HAND_PARTS:
            names.add(f"{side}_{part}")
    return names
