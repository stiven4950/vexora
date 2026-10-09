"""La mano toca la cara (video_33, seg. 8,2-9: cara de caricatura con labios, y al soltar, el beso
que viaja hasta los dedos).

Se mide con la pose y no con la malla facial: con la gorra puesta y la mano encima, Face Mesh se
pierde justo en esos fotogramas (205-260 en video_33), mientras los ojos, orejas, nariz y
comisuras de la pose siguen ahí.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent, PersonPose

# Distancia de la punta de un dedo al centro de la cara, en tamaños de cara (orejas). En
# video_33 el toque de la referencia (254-271) baja de 0,6; acercar la mano sin tocar, no.
TOUCH_REACH = 0.6
TOUCH_MIN_S = 0.25
# Con la gorra puesta, una mano cuyos dedos quedan a menos de esto de su contorno (en tamaños de
# cara) se la está acomodando.
GRIP_REACH = 0.2
FACE_POINTS = ("nose", "left_eye", "right_eye", "mouth_left", "mouth_right")


def face_frame(person: PersonPose, width: int, height: int) -> tuple[np.ndarray, float] | None:
    """Centro y tamaño de la cara (distancia entre orejas, o 0,35 hombros si una oreja falta)."""
    pts = {lm.name: np.array([lm.x * width, lm.y * height]) for lm in person.pose if lm.c > 0.3}
    face = [pts[name] for name in FACE_POINTS if name in pts]
    if len(face) < 3:
        return None
    sizes = []
    if "left_ear" in pts and "right_ear" in pts:
        sizes.append(float(np.linalg.norm(pts["left_ear"] - pts["right_ear"])))
    if "left_shoulder" in pts and "right_shoulder" in pts:
        sizes.append(float(np.linalg.norm(pts["left_shoulder"] - pts["right_shoulder"])) * 0.35)
    if not sizes:
        return None
    return np.mean(face, axis=0), max(max(sizes), 8.0)


def fingertips(person: PersonPose, side: str, width: int, height: int) -> list[np.ndarray]:
    hand = person.left_hand if side == "left" else person.right_hand
    if hand is not None and hand.landmarks:
        tips = [np.array([lm.x * width, lm.y * height]) for lm in hand.landmarks if lm.name.endswith("_tip")]
        if tips:
            return tips
    wrist = next((lm for lm in person.pose if lm.name == f"{side}_wrist" and lm.c > 0.3), None)
    return [np.array([wrist.x * width, wrist.y * height])] if wrist is not None else []


def _people(record: FrameRecord) -> list[PersonPose]:
    if record.people:
        return record.people
    if record.pose:
        return [PersonPose(person_id=record.person_id, pose=record.pose, left_hand=record.left_hand, right_hand=record.right_hand)]
    return []


def _busy(record: FrameRecord, person: str, side: str, tips: list[np.ndarray], size: float, width: int, height: int) -> bool:
    """La mano está con el objeto protagonista (lo sostiene, o se acomoda la gorra puesta: los
    dedos tocan su contorno): no es un toque de la cara."""
    prop = record.prop
    if prop is None or prop.person != person:
        return False
    if prop.state in (side, "both"):
        return True
    if prop.state != "fitting":
        return False
    polygon = np.array(prop.contour) * [width, height]
    to_prop = min(float(np.min(np.linalg.norm(polygon - tip, axis=1))) for tip in tips)
    return to_prop < GRIP_REACH * size


def face_touch_events(frames: list[FrameRecord], fps: float, width: int, height: int) -> list[MotionEvent]:
    """face_touch (kind = mano): las puntas de los dedos quedan junto a la cara al menos
    TOUCH_MIN_S. `position` es el centro de la cara al empezar."""
    runs: dict[tuple[str, str], list[int]] = {}
    events: list[MotionEvent] = []

    def close(key: tuple[str, str]) -> None:
        span = runs.pop(key, [])
        if len(span) >= max(int(TOUCH_MIN_S * fps), 1):
            first = frames[span[0]]
            center = next((face_frame(p, width, height) for p in _people(first) if p.person_id == key[0]), None)
            events.append(
                MotionEvent(
                    name="face_touch",
                    target=f"{key[0]}:face",
                    start_frame=first.frame,
                    end_frame=frames[span[-1]].frame,
                    confidence=0.9,
                    detail="La mano toca la cara.",
                    position=(float(center[0][0] / width), float(center[0][1] / height)) if center else None,
                    kind=key[1],
                )
            )

    for index, record in enumerate(frames):
        touching: set[tuple[str, str]] = set()
        for person in _people(record):
            face = face_frame(person, width, height)
            if face is None:
                continue
            center, size = face
            for side in ("left", "right"):
                tips = fingertips(person, side, width, height)
                if not tips or _busy(record, person.person_id, side, tips, size, width, height):
                    continue
                if min(float(np.linalg.norm(tip - center)) for tip in tips) < TOUCH_REACH * size:
                    touching.add((person.person_id, side))
        for key in list(runs):
            if key not in touching:
                close(key)
        for key in touching:
            runs.setdefault(key, []).append(index)
    for key in list(runs):
        close(key)
    return sorted(events, key=lambda e: e.start_frame)
