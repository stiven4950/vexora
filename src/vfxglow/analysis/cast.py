"""Quién baila: deja en el análisis solo a los protagonistas y saca al público.

El detector de pose ve hasta dos personas. En un video con público (video_35: un bailarín y gente
sentada al fondo mirándolo) la segunda suele ser alguien del público, y además las casillas se
cruzan: el bailarín es a ratos person_0 y a ratos person_1. Los efectos no deben ir al público
(docs/criterio_de_analisis.md, P1: la atención manda).

- Protagonista: una detección con la altura de la más alta del cuadro (PERFORMER_SIZE); el
  público está más lejos o sentado y mide menos de la mitad (video_35: 0,46; la pareja de
  video_34: 0,90).
- Y además al menos VIDEO_SIZE de la altura típica del protagonista en todo el video: si en un
  cuadro el detector no ve al bailarín (cortado por el borde, muy cerca de la cámara), el más alto
  que queda es alguien del público y no debe tomar su lugar (video_35, seg. 25,7-26,3).
- Solista o pareja: si en PAIR_SHARE (20%) de los cuadros hay dos protagonistas, es una pareja y cada
  una conserva su casilla; si no, es un solista: en cada cuadro queda uno solo, siempre
  person_0, elegido por tamaño y continuidad (el que se solapa con el del cuadro anterior).
"""

from __future__ import annotations

import logging

from vfxglow.analysis.schema import FrameRecord, PersonPose

log = logging.getLogger(__name__)

PERFORMER_SIZE = 0.6
VIDEO_SIZE = 0.55
# Fracción de los cuadros con protagonista en que debe haber dos para tratarlo como pareja. En una
# pelea cuerpo a cuerpo la pose pierde a uno de los dos a menudo (ufc_fight: 26%, swordman-fight:
# 39%), mientras que en un solista con público casi nunca hay un segundo del tamaño del bailarín
# (video_35: 2,5%). Con 0,5 las peleas quedaban como solista y perdían al segundo peleador.
PAIR_SHARE = 0.2
# En el solista, cuánto puede ganar en tamaño otra detección antes de dejar de seguir al anterior.
SWITCH_SIZE = 1.35
# Solista: alguien mucho más pequeño que el bailarín de hace poco y lejos de él no toma su lugar
# (el público de pie cuando el bailarín sale del cuadro, video_35 seg. 25).
SHRINK = 0.6
MEMORY_S = 0.5


def _height(person: PersonPose) -> float:
    box = person.box
    return (box[3] - box[1]) if box else 0.0


def _iou(a, b) -> float:
    if a is None or b is None:
        return 0.0
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def performers(record: FrameRecord, typical: float = 0.0) -> list[PersonPose]:
    people = [p for p in record.people if p.box is not None]
    if not people:
        return []
    tallest = max(_height(p) for p in people)
    return [p for p in people if _height(p) >= PERFORMER_SIZE * tallest and _height(p) >= VIDEO_SIZE * typical]


def _set_main(record: FrameRecord, person: PersonPose | None) -> None:
    """Los campos planos del registro son los de person_0."""
    record.person_id = "person_0"
    record.pose = person.pose if person else []
    record.left_hand = person.left_hand if person else None
    record.right_hand = person.right_hand if person else None
    record.face = person.face if person else None
    record.box = person.box if person else None


def keep_performers(frames: list[FrameRecord], fps: float = 30.0) -> str:
    """Filtra `frames` en su lugar. Devuelve "solo" o "pareja"."""
    tallest = sorted(max((_height(p) for p in record.people if p.box is not None), default=0.0) for record in frames)
    tallest = [h for h in tallest if h > 0]
    typical = tallest[len(tallest) // 2] if tallest else 0.0
    found = [performers(record, typical) for record in frames]
    seen = sum(1 for group in found if group)
    pair = seen > 0 and sum(1 for group in found if len(group) >= 2) >= PAIR_SHARE * seen
    dropped = 0
    previous = None
    since = 10**9
    for record, group in zip(frames, found, strict=True):
        since += 1
        if not pair and previous is not None and since <= MEMORY_S * fps:
            prev_h = previous[3] - previous[1]
            group = [p for p in group if _height(p) >= SHRINK * prev_h or _iou(p.box, previous) > 0.1]
        dropped += len(record.people) - (len(group) if pair else min(len(group), 1))
        if pair:
            record.people = sorted(group, key=lambda p: p.person_id)
            main = next((p for p in record.people if p.person_id == "person_0"), None)
            if main is not None:
                _set_main(record, main)
            continue
        if not group:
            record.people = []
            _set_main(record, None)
            continue
        biggest = max(group, key=_height)
        follow = max(group, key=lambda p: _iou(p.box, previous)) if previous is not None else None
        lead = follow if follow is not None and _iou(follow.box, previous) > 0.2 and _height(biggest) <= SWITCH_SIZE * _height(follow) else biggest
        lead = lead.model_copy(update={"person_id": "person_0"})
        record.people = [lead]
        _set_main(record, lead)
        previous = lead.box
        since = 0
    kind = "pareja" if pair else "solo"
    log.info("Protagonistas: %s; %d detecciones del público descartadas", kind, dropped)
    return kind


# ----- recuperar al solista donde la pose lo perdió -----

# Huecos más largos que esto (s) no se intentan: el bailarín salió de verdad.
RECOVER_MAX_S = 3.0
RECOVER_PAD = 0.1
# Lo recuperado debe coincidir con su trayectoria (solape con la caja prevista o su silueta) y
# medir al menos esto de su altura típica.
RECOVER_OVERLAP = 0.15
RECOVER_SIZE = 0.5


def _box_of(pose) -> tuple[float, float, float, float] | None:
    pts = [(l.x, l.y) for l in pose if l.c > 0.3]
    if len(pts) < 4:
        return None
    xs, ys = zip(*pts)
    return (min(xs), min(ys), max(xs), max(ys))


def _overlap(a, b) -> float:
    """Fracción de `a` que cae dentro de `b`."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    area = (a[2] - a[0]) * (a[3] - a[1])
    return inter / area if area > 0 else 0.0


def recover_lead(video_path, frames: list[FrameRecord], fps: float, model_path) -> int:
    """En un solista, los cuadros sin bailarín entre dos donde sí está (hueco corto) se vuelven a
    mirar: se predice su caja interpolando entre los vecinos, se elige su silueta del segmentador
    y se vuelve a detectar la pose en un recorte ampliado de esa zona (la pose suele fallar cuando
    la cámara se acerca o el cuerpo sale en parte del cuadro). Devuelve cuántos recuperó."""
    import cv2
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks.python.core.base_options import BaseOptions
    from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

    from vfxglow.analysis.names import POSE_NAMES
    from vfxglow.analysis.schema import Landmark

    known = [i for i, r in enumerate(frames) if r.people]
    # La pose del protagonista: la de su casilla o, en pistas ya guardadas, la de los campos planos.
    boxes = {i: _box_of(frames[i].people[0].pose or frames[i].pose) for i in known}
    known = [i for i in known if boxes[i] is not None]
    if len(known) < 2:
        return 0
    heights = sorted(b[3] - b[1] for b in boxes.values() if b)
    typical = heights[len(heights) // 2]
    longest = int(RECOVER_MAX_S * fps)
    todo: list[tuple[int, int, int]] = []
    for a, b in zip(known, known[1:]):
        if 1 < b - a <= longest:
            todo += [(i, a, b) for i in range(a + 1, b)]
    if not todo:
        return 0
    landmarker = PoseLandmarker.create_from_options(
        PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path), delegate=BaseOptions.Delegate.CPU),
            running_mode=RunningMode.IMAGE,
            num_poses=3,
            min_pose_detection_confidence=0.2,
            min_pose_presence_confidence=0.2,
        )
    )
    wanted = {i: (a, b) for i, a, b in todo}
    recovered = 0
    capture = cv2.VideoCapture(str(video_path))
    try:
        index = 0
        while index <= max(wanted):
            ok, image = capture.read()
            if not ok:
                break
            if index in wanted:
                a, b = wanted[index]
                u = (index - a) / (b - a)
                pred = tuple(boxes[a][k] * (1 - u) + boxes[b][k] * u for k in range(4))
                regions = []
                for outline in frames[index].body_contours or []:
                    arr = np.array(outline)
                    blob = (arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max())
                    if blob[2] - blob[0] < 0.9 and _overlap(pred, blob) > RECOVER_OVERLAP:
                        regions.append(blob)
                regions += [pred, (0.0, 0.0, 1.0, 1.0)]
                person = _detect_in(landmarker, image, regions, pred, typical, mp, cv2, np, POSE_NAMES, Landmark)
                if person is not None:
                    frames[index].people = [person]
                    _set_main(frames[index], person)
                    recovered += 1
            index += 1
    finally:
        capture.release()
        landmarker.close()
    log.info("Protagonista recuperado en %d de %d cuadros sin pose", recovered, len(todo))
    return recovered


def _detect_in(landmarker, image, regions, pred, typical, mp, cv2, np, names, landmark_cls) -> PersonPose | None:
    height, width = image.shape[:2]
    for x0, y0, x1, y1 in regions:
        X0, Y0 = int(max(x0 - RECOVER_PAD, 0) * width), int(max(y0 - RECOVER_PAD, 0) * height)
        X1, Y1 = int(min(x1 + RECOVER_PAD, 1) * width), int(min(y1 + RECOVER_PAD, 1) * height)
        if X1 - X0 < 32 or Y1 - Y0 < 32:
            continue
        crop = np.ascontiguousarray(cv2.cvtColor(image[Y0:Y1, X0:X1], cv2.COLOR_BGR2RGB))
        result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
        best = None
        for group in result.pose_landmarks or []:
            pose = [
                landmark_cls(name=names[k], x=(X0 + lm.x * (X1 - X0)) / width, y=(Y0 + lm.y * (Y1 - Y0)) / height, z=getattr(lm, "z", 0.0),
                             c=float(getattr(lm, "visibility", 0.9) or 0.9))
                for k, lm in enumerate(group) if k < len(names)
            ]
            box = _box_of(pose)
            # Del tamaño previsto para el bailarín (no alguien del público) y en su trayectoria.
            tall = box[3] - box[1]
            if box is None or tall < RECOVER_SIZE * typical or tall < RECOVER_SIZE * (pred[3] - pred[1]) or _overlap(box, pred) < RECOVER_OVERLAP:
                continue
            if best is None or box[3] - box[1] > best[1][3] - best[1][1]:
                best = (pose, box)
        if best is not None:
            return PersonPose(person_id="person_0", pose=best[0], box=best[1])
    return None
