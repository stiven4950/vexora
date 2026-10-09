"""Tono de piel de cada persona, para elegir colores que contrasten (ver director/palette.py).

Se muestrean unos fotogramas repartidos en el video: mejillas (entre ojo y comisura) y centro del
pecho. Solo cuentan los píxeles en el rango de piel en YCrCb (sin los casi negros ni los rojos muy
saturados), y las mejillas mandan: el pecho solo se usa si la cara no da muestras suficientes
(en video_34 el pecho de uno es una camisa negra bajo un saco rojo). La mediana se guarda en RGB
lineal con su luminancia.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import FrameRecord, PersonPose, SkinTone

SAMPLES = 24
# Rango amplio de piel en YCrCb (de muy clara a muy oscura).
CR_RANGE = (133, 170)
CB_RANGE = (77, 135)
# Luma mínima (0-255): por debajo es ropa negra o sombra, no piel (la piel muy oscura pasa de 40).
Y_MIN = 35
MIN_PIXELS = 400


def _people(record: FrameRecord) -> list[PersonPose]:
    if record.people:
        return record.people
    if record.pose:
        return [PersonPose(person_id=record.person_id, pose=record.pose)]
    return []


def _patches(person: PersonPose, width: int, height: int) -> list[tuple[np.ndarray, int, str]]:
    """(centro, radio, zona) de las zonas donde suele verse piel: "face" o "chest"."""
    pts = {lm.name: np.array([lm.x * width, lm.y * height]) for lm in person.pose if lm.c > 0.5}
    out = []
    if "left_ear" in pts and "right_ear" in pts:
        face = float(np.linalg.norm(pts["left_ear"] - pts["right_ear"]))
        radius = max(int(face * 0.12), 2)
        for side in ("left", "right"):
            if f"{side}_eye" in pts and f"mouth_{side}" in pts:
                out.append(((pts[f"{side}_eye"] + pts[f"mouth_{side}"]) * 0.5, radius, "face"))
    if all(name in pts for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")):
        top = (pts["left_shoulder"] + pts["right_shoulder"]) * 0.5
        bottom = (pts["left_hip"] + pts["right_hip"]) * 0.5
        radius = max(int(np.linalg.norm(pts["left_shoulder"] - pts["right_shoulder"]) * 0.12), 2)
        out.append((top + (bottom - top) * 0.35, radius, "chest"))
    return out


def estimate_skin(video_path: Path, frames: list[FrameRecord]) -> dict[str, SkinTone]:
    usable = [record for record in frames if _people(record)]
    if not usable:
        return {}
    picks = {usable[int(i)].frame for i in np.linspace(0, len(usable) - 1, min(SAMPLES, len(usable)))}
    by_frame = {record.frame: record for record in usable}
    pixels: dict[tuple[str, str], list[np.ndarray]] = {}
    capture = cv2.VideoCapture(str(video_path))
    try:
        for frame_index in sorted(picks):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
            for person in _people(by_frame[frame_index]):
                for center, radius, zone in _patches(person, width, height):
                    x, y = int(center[0]), int(center[1])
                    x0, x1, y0, y1 = max(x - radius, 0), min(x + radius + 1, width), max(y - radius, 0), min(y + radius + 1, height)
                    if x1 <= x0 or y1 <= y0:
                        continue
                    patch, tone = frame[y0:y1, x0:x1].reshape(-1, 3), ycrcb[y0:y1, x0:x1].reshape(-1, 3)
                    skin = (tone[:, 0] >= Y_MIN) & (tone[:, 1] >= CR_RANGE[0]) & (tone[:, 1] <= CR_RANGE[1]) & (tone[:, 2] >= CB_RANGE[0]) & (tone[:, 2] <= CB_RANGE[1])
                    if skin.any():
                        pixels.setdefault((person.person_id, zone), []).append(patch[skin])
    finally:
        capture.release()
    tones = {}
    for person in {key[0] for key in pixels}:
        face = np.concatenate(pixels[(person, "face")]) if (person, "face") in pixels else np.empty((0, 3))
        stacked = face if len(face) >= MIN_PIXELS else np.concatenate([face] + pixels.get((person, "chest"), []))
        if len(stacked) < MIN_PIXELS:
            continue
        srgb = np.median(stacked[:, ::-1], axis=0) / 255.0
        linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
        luma = float(linear @ np.array([0.2126, 0.7152, 0.0722]))
        tones[person] = SkinTone(rgb=tuple(float(v) for v in linear), luma=luma, samples=int(len(stacked)))
    return tones
