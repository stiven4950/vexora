"""Gestos con significado (docs/criterio_de_analisis.md, P4): lo que un creador convierte en imagen.

- throw (kind = mano): amago de lanzamiento. El brazo carga (muñeca por encima del hombro un
  rato), la muñeca acelera de golpe y el brazo se extiende al soltar. `start_frame` = inicio de
  la carga, `end_frame` = suelta; `position` y `direction_deg` = dónde y hacia dónde sale lo
  lanzado. video_33: carga 10,0-10,5 s, suelta ~11,1 s.
- stomp (kind = pie): pisotón. El pie estaba levantado, baja rápido y se frena en seco cerca del
  piso. `end_frame` = el golpe; `position` = dónde pisa. video_33: 28,2 s (el globo que revienta).
- neck_slash (kind = mano): corte de cuello ("ya valió"). Las puntas de los dedos pasan junto al
  cuello y lo recorren de lado. video_33: 11,7 s.

Ambos con los puntos de la pose y de la mano, en torsos o tamaños de cara.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.analysis.touch import _busy, _people, face_frame, fingertips

# Lanzamiento: velocidad pico de la muñeca (torsos por fotograma), carga mínima con la muñeca
# arriba antes del pico y alcance (hombro-muñeca, en torsos) al soltar.
THROW_SPEED = 0.12
WINDUP_S = 0.25
WINDUP_LOOKBACK_S = 0.8
RELEASE_WITHIN_S = 0.6
RELEASE_REACH = 0.75
EXTENSION = 0.45
THROW_COOLDOWN_S = 1.0
# Corte de cuello: dedos a menos de esto del cuello (tamaños de cara) y recorrido lateral mínimo.
NECK_REACH = 0.55
NECK_SWEEP = 0.45
NECK_MIN_FRAMES = 3
NECK_MAX_S = 0.6


def _pose(record: FrameRecord, person: str, width: int, height: int):
    owner = next((p for p in _people(record) if p.person_id == person), None)
    if owner is None:
        return None, None
    return owner, {lm.name: np.array([lm.x * width, lm.y * height]) for lm in owner.pose if lm.c > 0.3}


def throw_events(frames: list[FrameRecord], fps: float, width: int, height: int) -> list[MotionEvent]:
    events: list[MotionEvent] = []
    people = sorted({p.person_id for record in frames for p in _people(record)})
    for person in people:
        for side in ("left", "right"):
            wrist, speed, raised, reach, torso_len = [], [], [], [], []
            for record in frames:
                _, pts = _pose(record, person, width, height)
                need = (f"{side}_wrist", f"{side}_shoulder", "left_shoulder", "left_hip")
                if pts is None or any(name not in pts for name in need):
                    wrist.append(None)
                    speed.append(0.0)
                    raised.append(False)
                    reach.append(0.0)
                    torso_len.append(1.0)
                    continue
                torso = max(float(np.linalg.norm(pts["left_shoulder"] - pts["left_hip"])), 1.0)
                w = pts[f"{side}_wrist"]
                previous = wrist[-1] if wrist else None
                speed.append(float(np.linalg.norm(w - previous)) / torso if previous is not None else 0.0)
                wrist.append(w)
                raised.append(bool(w[1] < pts[f"{side}_shoulder"][1]))
                reach.append(float(np.linalg.norm(w - pts[f"{side}_shoulder"])) / torso)
                torso_len.append(torso)
            speed_arr = np.array(speed)
            last = -10_000
            for index in range(1, len(frames) - 1):
                if speed_arr[index] < THROW_SPEED or speed_arr[index] < speed_arr[index - 1] or speed_arr[index] < speed_arr[index + 1]:
                    continue
                if index - last < THROW_COOLDOWN_S * fps:
                    continue
                look = max(index - int(WINDUP_LOOKBACK_S * fps), 0)
                if sum(raised[look:index]) < WINDUP_S * fps:
                    continue
                stop = min(index + int(RELEASE_WITHIN_S * fps), len(frames) - 1)
                after = range(index, stop + 1)
                release = max(after, key=lambda k: reach[k])
                if reach[release] < RELEASE_REACH or wrist[release] is None:
                    continue
                # Lanzar es extender el brazo hacia afuera, no solo bajarlo.
                if reach[release] - min(reach[index : release + 1]) < EXTENSION:
                    continue
                windup = next(k for k in range(look, index) if raised[k])
                move = wrist[release] - wrist[max(release - 3, 0)] if wrist[max(release - 3, 0)] is not None else np.zeros(2)
                events.append(
                    MotionEvent(
                        name="throw",
                        target=f"{person}:{side}_wrist",
                        start_frame=frames[windup].frame,
                        end_frame=frames[release].frame,
                        confidence=float(min(speed_arr[index] / (2 * THROW_SPEED), 1.0)),
                        detail="Amago de lanzamiento: carga con el brazo arriba y suelta de golpe.",
                        position=(float(wrist[release][0] / width), float(wrist[release][1] / height)),
                        peak_speed=float(speed_arr[index]),
                        direction_deg=float(np.degrees(np.arctan2(move[1], move[0]))),
                        kind=side,
                    )
                )
                last = index
    return sorted(events, key=lambda e: e.start_frame)


def neck_slash_events(frames: list[FrameRecord], fps: float, width: int, height: int) -> list[MotionEvent]:
    events: list[MotionEvent] = []
    people = sorted({p.person_id for record in frames for p in _people(record)})
    for person in people:
        for side in ("left", "right"):
            run: list[tuple[int, float, float]] = []  # (índice, x del dedo más cercano, tamaño de cara)

            def close() -> None:
                if NECK_MIN_FRAMES <= len(run) <= NECK_MAX_S * fps:
                    xs = [x for _, x, _ in run]
                    face = float(np.median([f for _, _, f in run]))
                    if max(xs) - min(xs) >= NECK_SWEEP * face:
                        first, last_ = frames[run[0][0]], frames[run[-1][0]]
                        events.append(
                            MotionEvent(
                                name="neck_slash",
                                target=f"{person}:face",
                                start_frame=first.frame,
                                end_frame=last_.frame,
                                confidence=0.8,
                                detail="Corte de cuello: la mano cruza el cuello de lado.",
                                kind=side,
                            )
                        )
                run.clear()

            for index, record in enumerate(frames):
                owner, pts = _pose(record, person, width, height)
                frame = face_frame(owner, width, height) if owner is not None else None
                if pts is None or frame is None or "mouth_left" not in pts or "left_shoulder" not in pts or "right_shoulder" not in pts:
                    close()
                    continue
                mouth = (pts["mouth_left"] + pts["mouth_right"]) * 0.5 if "mouth_right" in pts else pts["mouth_left"]
                neck = mouth * 0.4 + (pts["left_shoulder"] + pts["right_shoulder"]) * 0.5 * 0.6
                size = frame[1]
                tips = fingertips(owner, side, width, height)
                if not tips:
                    close()
                    continue
                # La mano con el objeto protagonista (sostenerlo, ponérselo) no hace un corte.
                if _busy(record, person, side, tips, size, width, height):
                    close()
                    continue
                nearest = min(tips, key=lambda t: float(np.linalg.norm(t - neck)))
                if float(np.linalg.norm(nearest - neck)) < NECK_REACH * size:
                    run.append((index, float(nearest[0]), size))
                else:
                    close()
            close()
    return sorted(events, key=lambda e: e.start_frame)


# Pisotón: alto mínimo previo (torsos sobre el piso), velocidad de bajada y frenada.
STOMP_LIFT = 0.12
STOMP_SPEED = 0.03
STOMP_STOP = 0.35
STOMP_STOP_FRAMES = 8
STOMP_LOOKBACK_S = 0.5
STOMP_COOLDOWN_S = 0.6


def stomp_events(frames: list[FrameRecord], fps: float, width: int, height: int, lift: float = STOMP_LIFT, speed: float = STOMP_SPEED, name: str = "stomp") -> list[MotionEvent]:
    events: list[MotionEvent] = []
    people = sorted({p.person_id for record in frames for p in _people(record)})
    lookback = max(int(STOMP_LOOKBACK_S * fps), 2)
    for person in people:
        for side in ("left", "right"):
            ys: list[float | None] = []
            xs: list[float | None] = []
            torsos: list[float] = []
            for record in frames:
                _, pts = _pose(record, person, width, height)
                foot = [pts.get(f"{side}_{n}") for n in ("heel", "foot_index", "ankle")] if pts else []
                foot = [p for p in foot if p is not None]
                if not foot or "left_shoulder" not in pts or "left_hip" not in pts:
                    ys.append(None)
                    xs.append(None)
                    torsos.append(1.0)
                    continue
                ground = np.mean(foot, axis=0)
                ys.append(float(ground[1]))
                xs.append(float(ground[0]))
                torsos.append(max(float(np.linalg.norm(pts["left_shoulder"] - pts["left_hip"])), 1.0))
            vy = [None] + [(ys[k] - ys[k - 1]) / torsos[k] if ys[k] is not None and ys[k - 1] is not None else None for k in range(1, len(ys))]
            last = -10_000
            for index in range(1, len(frames) - 1):
                v = vy[index]
                if v is None or v < speed or index - last < STOMP_COOLDOWN_S * fps:
                    continue
                if (vy[index - 1] or 0.0) > v or (vy[index + 1] or 0.0) > v:
                    continue  # no es el pico de la bajada
                # El golpe: la velocidad cae por debajo de un tercio del pico en pocos fotogramas
                # (la pose suavizada redondea la frenada).
                hit = next((k for k in range(index + 1, min(index + STOMP_STOP_FRAMES, len(frames))) if vy[k] is not None and vy[k] < v * STOMP_STOP), None)
                if hit is None or ys[hit] is None:
                    continue
                # Alto que tenía el pie antes de bajar, medido en el golpe (ya en el piso).
                window = [y for y in ys[max(index - lookback, 0) : index] if y is not None]
                if not window or (ys[hit] - min(window)) / torsos[hit] < lift:
                    continue
                events.append(
                    MotionEvent(
                        name=name,
                        target=f"{person}:{side}_ankle",
                        start_frame=frames[max(index - lookback // 2, 0)].frame,
                        end_frame=frames[hit].frame,
                        confidence=float(min(v / (2 * STOMP_SPEED), 1.0)),
                        detail="Pisotón: el pie baja rápido y se frena en el piso." if name == "stomp" else "Paso: el pie vuelve a apoyarse en el piso.",
                        position=(float(xs[hit] / width), float(ys[hit] / height)),
                        kind=side,
                    )
                )
                last = hit
    return sorted(events, key=lambda e: e.start_frame)


# ----- poses sostenidas: el gesto dura al menos POSE_MIN_S -----

POSE_MIN_S = 0.3
HEART_NEAR = 0.32  # muñecas juntas, en torsos
HEART_MIN_S = 0.5
ARMS_UP = 0.25  # muñecas por encima de la nariz, en torsos
OPEN_WIDE = 2.3  # muñecas separadas, en anchos de hombros
OPEN_LEVEL = 0.35  # muñecas a la altura de los hombros (torsos)
ROCK_RATIO = 1.6  # índice y meñique más largos que medio y anular (doblados)
HEAD_REACH = 0.9  # muñecas a menos de esto (anchos de hombros) de la nariz, de lado
LUNGE_S = 0.4
LUNGE_GROWTH = 0.3  # el ancho de hombros crece un 30% en LUNGE_S: se acerca a la cámara
POINT_REACH = 0.85  # brazo extendido (hombro-muñeca, torsos)
POINT_INDEX = 1.6  # índice más largo que el resto de los dedos (desde la muñeca)
EAR_NEAR = 0.45  # dedos junto a la oreja (tamaños de cara)
EAR_FACE_MIN = 0.45  # y no junto a la boca o la mejilla (eso es tocarse la cara)
EYES_NEAR = 0.32  # dedos sobre los ojos (tamaños de cara)
SPIN_MAX_S = 1.0  # de espaldas como mucho esto entre dos tramos de frente
SPIN_MIN_S = 0.3
SPIN_BACK_S = 0.15  # de espaldas de verdad, no un cruce de hombros de un fotograma


def _spans(flags: list[str | None], frames: list[FrameRecord], fps: float, min_s: float = POSE_MIN_S):
    """Tramos seguidos con la misma etiqueta (no None) de al menos `min_s`: (inicio, fin, etiqueta)."""
    out, start = [], None
    for index in range(len(flags) + 1):
        current = flags[index] if index < len(flags) else None
        if start is not None and (current != flags[start]):
            if index - start >= min_s * fps:
                out.append((frames[start].frame, frames[index - 1].frame, flags[start]))
            start = None
        if start is None and current is not None:
            start = index
    return out


def _pose_events(frames, fps, width, height, name, detail, flag_of, min_s=POSE_MIN_S) -> list[MotionEvent]:
    events: list[MotionEvent] = []
    for person in sorted({p.person_id for record in frames for p in _people(record)}):
        flags, where = [], {}
        for record in frames:
            owner, pts = _pose(record, person, width, height)
            result = flag_of(record, owner, pts) if pts is not None and "left_shoulder" in pts and "left_hip" in pts and "right_shoulder" in pts else None
            if result is None:
                flags.append(None)
                continue
            flags.append(result[0])
            where[record.frame] = result[1]
        for start, end, kind in _spans(flags, frames, fps, min_s):
            position = where.get(start)
            events.append(
                MotionEvent(
                    name=name,
                    target=f"{person}:{kind}" if kind not in ("", "both") else person,
                    start_frame=start,
                    end_frame=end,
                    confidence=0.8,
                    detail=detail,
                    position=(float(position[0] / width), float(position[1] / height)) if position is not None else None,
                    kind=kind,
                )
            )
    return sorted(events, key=lambda e: e.start_frame)


def _torso(pts) -> float:
    return max(float(np.linalg.norm(pts["left_shoulder"] - pts["left_hip"])), 1.0)


def heart_hands_events(frames, fps, width, height):
    """Corazón con las manos: las dos muñecas juntas frente al pecho."""

    def flag(record, owner, pts):
        if "left_wrist" not in pts or "right_wrist" not in pts:
            return None
        if record.prop is not None and record.prop.state in ("left", "right", "both"):
            return None  # las manos juntas sostienen el objeto
        torso, mid = _torso(pts), (pts["left_wrist"] + pts["right_wrist"]) / 2
        top, bottom = min(pts["left_shoulder"][1], pts["right_shoulder"][1]), pts["left_hip"][1]
        if np.linalg.norm(pts["left_wrist"] - pts["right_wrist"]) / torso < HEART_NEAR and top - 0.1 * torso <= mid[1] <= bottom:
            return "both", mid
        return None

    # Al menos HEART_MIN_S: un aplauso también junta las manos, pero no se sostiene.
    return _pose_events(frames, fps, width, height, "heart_hands", "Las dos manos juntas frente al pecho (corazón).", flag, min_s=HEART_MIN_S)


def arms_up_events(frames, fps, width, height):
    """Brazos arriba / victoria: las dos muñecas por encima de la cabeza."""

    def flag(record, owner, pts):
        if "left_wrist" not in pts or "right_wrist" not in pts or "nose" not in pts:
            return None
        torso, nose = _torso(pts), pts["nose"]
        if max(pts["left_wrist"][1], pts["right_wrist"][1]) < nose[1] - ARMS_UP * torso:
            return "both", nose - np.array([0.0, 0.6 * torso])
        return None

    return _pose_events(frames, fps, width, height, "arms_up", "Los dos brazos arriba (victoria).", flag)


def arms_open_events(frames, fps, width, height):
    """Brazos abiertos en cruz: muñecas muy separadas a la altura de los hombros."""

    def flag(record, owner, pts):
        if "left_wrist" not in pts or "right_wrist" not in pts:
            return None
        torso = _torso(pts)
        shoulders = float(np.linalg.norm(pts["left_shoulder"] - pts["right_shoulder"]))
        level = (pts["left_shoulder"][1] + pts["right_shoulder"][1]) / 2
        wide = abs(pts["left_wrist"][0] - pts["right_wrist"][0]) / max(shoulders, 1.0)
        if wide > OPEN_WIDE and all(abs(pts[f"{s}_wrist"][1] - level) / torso < OPEN_LEVEL for s in ("left", "right")):
            return "both", (pts["left_shoulder"] + pts["right_shoulder"]) / 2
        return None

    return _pose_events(frames, fps, width, height, "arms_open", "Los brazos abiertos en cruz.", flag)


def point_events(frames, fps, width, height):
    """Señalar: brazo extendido con el índice estirado y los demás dedos recogidos."""

    def flag(record, owner, pts):
        torso = _torso(pts)
        for side in ("left", "right"):
            hand = owner.left_hand if side == "left" else owner.right_hand
            if hand is None or f"{side}_wrist" not in pts or f"{side}_shoulder" not in pts:
                continue
            lm = {l.name.replace(f"{side}_", ""): np.array([l.x * width, l.y * height]) for l in hand.landmarks}
            if not all(k in lm for k in ("wrist", "index_finger_tip", "middle_finger_tip", "ring_finger_tip")) and not all(k in lm for k in ("wrist", "index_tip", "middle_tip", "ring_tip")):
                continue
            tip = lm.get("index_finger_tip", lm.get("index_tip"))
            others = [lm.get(f"{f}_finger_tip", lm.get(f"{f}_tip")) for f in ("middle", "ring", "pinky")]
            others = [o for o in others if o is not None]
            index_len = float(np.linalg.norm(tip - lm["wrist"]))
            rest = float(np.mean([np.linalg.norm(o - lm["wrist"]) for o in others]))
            reach = float(np.linalg.norm(pts[f"{side}_wrist"] - pts[f"{side}_shoulder"])) / torso
            if reach >= POINT_REACH and index_len > POINT_INDEX * rest:
                return side, tip
        return None

    events = _pose_events(frames, fps, width, height, "point", "Señala con el índice y el brazo extendido.", flag)
    for event in events:
        record = next((r for r in frames if r.frame == event.start_frame), None)
        owner, pts = _pose(record, event.target.split(":")[0], width, height) if record else (None, None)
        if pts and f"{event.kind}_elbow" in pts and event.position is not None:
            direction = np.array(event.position) * [width, height] - pts[f"{event.kind}_elbow"]
            event.direction_deg = float(np.degrees(np.arctan2(direction[1], direction[0])))
    return events


def _face_hand(owner, pts, width, height):
    frame = face_frame(owner, width, height)
    if frame is None:
        return None
    return frame[1]


def hand_ear_events(frames, fps, width, height):
    """Mano en el oído ("no te oigo"): dedos junto a una oreja y lejos de los ojos."""

    def flag(record, owner, pts):
        size = _face_hand(owner, pts, width, height)
        if size is None or "left_eye" not in pts or "right_eye" not in pts:
            return None
        eyes = (pts["left_eye"] + pts["right_eye"]) / 2
        for side in ("left", "right"):
            tips = fingertips(owner, side, width, height)
            for ear_name in ("left_ear", "right_ear"):
                ear = pts.get(ear_name)
                if ear is None or not tips:
                    continue
                near_ear = min(float(np.linalg.norm(t - ear)) for t in tips) / size
                near_eyes = min(float(np.linalg.norm(t - eyes)) for t in tips) / size
                # Junto a la boca o la mejilla es tocarse la cara (face_touch), no el oído.
                center = face_frame(owner, width, height)[0]
                near_face = min(float(np.linalg.norm(t - center)) for t in tips) / size
                if near_ear < EAR_NEAR and near_eyes > EYES_NEAR and near_face > EAR_FACE_MIN:
                    return side, ear
        return None

    return _pose_events(frames, fps, width, height, "hand_ear", "La mano en el oído (no te oigo).", flag)


def cover_eyes_events(frames, fps, width, height):
    """Mano en los ojos: los dedos tapan los ojos."""

    def flag(record, owner, pts):
        size = _face_hand(owner, pts, width, height)
        if size is None or "left_eye" not in pts or "right_eye" not in pts:
            return None
        eyes = (pts["left_eye"] + pts["right_eye"]) / 2
        for side in ("left", "right"):
            tips = fingertips(owner, side, width, height)
            if tips and min(float(np.linalg.norm(t - eyes)) for t in tips) / size < EYES_NEAR:
                return side, eyes
        return None

    return _pose_events(frames, fps, width, height, "cover_eyes", "La mano tapa los ojos.", flag, min_s=0.25)


def spin_body_events(frames, fps, width, height):
    """Giro sobre sí mismo: pasa de frente a espaldas y vuelve en menos de SPIN_MAX_S."""
    events: list[MotionEvent] = []
    for person in sorted({p.person_id for record in frames for p in _people(record)}):
        side = []
        for record in frames:
            _, pts = _pose(record, person, width, height)
            if pts is None or "left_shoulder" not in pts or "right_shoulder" not in pts or "left_hip" not in pts:
                side.append(None)
                continue
            dx = float(pts["left_shoulder"][0] - pts["right_shoulder"][0]) / _torso(pts)
            side.append("front" if dx > 0.2 else "back" if dx < -0.15 else "side")
        index = 0
        while index < len(frames):
            if side[index] != "back":
                index += 1
                continue
            end = index
            while end < len(frames) and side[end] != "front":
                end += 1
            start = index
            while start > 0 and side[start - 1] not in ("front", None):
                start -= 1
            before = start > 0 and side[start - 1] == "front"
            after = end < len(frames) and side[end] == "front"
            backs = sum(1 for k in range(start, end) if side[k] == "back")
            if before and after and SPIN_MIN_S * fps <= (end - start) <= SPIN_MAX_S * fps and backs >= SPIN_BACK_S * fps:
                events.append(MotionEvent(name="spin_body", target=person, start_frame=frames[start].frame, end_frame=frames[end - 1].frame, confidence=0.8, detail="Giro sobre sí mismo (frente → espaldas → frente)."))
            index = end + 1
    return sorted(events, key=lambda e: e.start_frame)


# Paso: como el pisotón, pero cualquier pie que vuelve a apoyarse (huellas).
STEP_LIFT = 0.05
STEP_SPEED = 0.012


def step_events(frames, fps, width, height):
    return stomp_events(frames, fps, width, height, lift=STEP_LIFT, speed=STEP_SPEED, name="step")


def _frenzy(frames, fps, width, height):
    from vfxglow.analysis.attention import frenzy_events

    return frenzy_events(frames, fps, width, height)


# Detectores de gestos y nombres de sus eventos (el pipeline los recalcula en análisis
# anteriores; ver Pipeline._ensure_derived).
def _finger(lm: dict, name: str):
    return lm.get(f"{name}_finger_tip", lm.get(f"{name}_tip"))


def rock_hands_events(frames, fps, width, height):
    """Cuernos de rock 🤘: índice y meñique estirados, medio y anular doblados (video_35, seg. 0,7)."""

    def flag(record, owner, pts):
        found = []
        for side in ("left", "right"):
            hand = owner.left_hand if side == "left" else owner.right_hand
            if hand is None:
                continue
            lm = {l.name.replace(f"{side}_", ""): np.array([l.x * width, l.y * height]) for l in hand.landmarks}
            wrist = lm.get("wrist")
            tips = {f: _finger(lm, f) for f in ("index", "middle", "ring", "pinky")}
            if wrist is None or any(t is None for t in tips.values()):
                continue
            reach = {f: float(np.linalg.norm(t - wrist)) for f, t in tips.items()}
            folded = (reach["middle"] + reach["ring"]) / 2
            if min(reach["index"], reach["pinky"]) > ROCK_RATIO * folded:
                found.append(side)
        if not found:
            return None
        side = "both" if len(found) == 2 else found[0]
        anchor = pts.get(f"{found[0]}_wrist")
        return (side, anchor) if anchor is not None else None

    return _pose_events(frames, fps, width, height, "rock_hands", "Cuernos de rock con la mano.", flag)


def hands_on_head_events(frames, fps, width, height):
    """Las dos manos sobre la cabeza (sujetan la gorra, forman un aro): video_35 seg. 3,4 y 13,2."""

    def flag(record, owner, pts):
        if not all(k in pts for k in ("left_wrist", "right_wrist", "nose", "left_shoulder", "right_shoulder")):
            return None
        torso, nose = _torso(pts), pts["nose"]
        width_sh = float(np.linalg.norm(pts["left_shoulder"] - pts["right_shoulder"]))
        near = all(abs(pts[f"{s}_wrist"][0] - nose[0]) < HEAD_REACH * width_sh for s in ("left", "right"))
        high = all(pts[f"{s}_wrist"][1] < nose[1] + 0.05 * torso and pts[f"{s}_wrist"][1] > nose[1] - 0.6 * torso for s in ("left", "right"))
        return ("both", nose - np.array([0.0, 0.3 * torso])) if near and high else None

    return _pose_events(frames, fps, width, height, "hands_on_head", "Las dos manos sobre la cabeza.", flag)


def arms_x_events(frames, fps, width, height):
    """Brazos cruzados en X frente al pecho: cada muñeca del otro lado y por encima de su codo."""

    def flag(record, owner, pts):
        if not all(f"{s}_{j}" in pts for s in ("left", "right") for j in ("wrist", "elbow", "shoulder")):
            return None
        mid = (pts["left_shoulder"][0] + pts["right_shoulder"][0]) / 2
        side_l = np.sign(pts["left_shoulder"][0] - mid)
        crossed = np.sign(pts["left_wrist"][0] - mid) == -side_l and np.sign(pts["right_wrist"][0] - mid) == side_l
        raised = all(pts[f"{s}_wrist"][1] < pts[f"{s}_elbow"][1] for s in ("left", "right"))
        return ("both", (pts["left_wrist"] + pts["right_wrist"]) / 2) if crossed and raised else None

    return _pose_events(frames, fps, width, height, "arms_x", "Brazos cruzados en X frente al pecho.", flag)


def lunge_events(frames, fps, width, height):
    """Se lanza hacia la cámara: el cuerpo crece rápido (LUNGE_GROWTH en LUNGE_S) (video_35, 14,2: Venom)."""
    events: list[MotionEvent] = []
    window = max(int(LUNGE_S * fps), 2)
    for person in sorted({p.person_id for record in frames for p in _people(record)}):
        sizes = []
        for record in frames:
            _, pts = _pose(record, person, width, height)
            if pts and "left_shoulder" in pts and "right_shoulder" in pts and "nose" in pts:
                sizes.append(float(np.linalg.norm(pts["left_shoulder"] - pts["right_shoulder"])))
            else:
                sizes.append(np.nan)
        sizes = np.array(sizes)
        last = -10**9
        for i in range(window, len(frames)):
            a, b = sizes[i - window], sizes[i]
            if np.isfinite(a) and np.isfinite(b) and b > a * (1 + LUNGE_GROWTH) and i - last > window * 2:
                _, pts = _pose(frames[i], person, width, height)
                events.append(MotionEvent(name="lunge", target=person, start_frame=frames[i - window].frame, end_frame=frames[i].frame,
                                          confidence=0.8, detail="Se lanza hacia la cámara.", kind="both",
                                          position=(float(pts["nose"][0] / width), float(pts["nose"][1] / height))))
                last = i
    return events


# Revólver con la mano (dance_two_mens, seg. 7,1-8,2): índice estirado, los otros dedos recogidos
# y el pulgar levantado como el martillo. Medido allí (largo del índice sobre la palma; punta de
# los otros dedos sobre su nudillo, desde la muñeca): índice 0,75-0,9 y dedos recogidos 1,1-1,35;
# con la mano abierta 0,65 y 1,5-1,7. El pulgar levantado forma 50-60° con el índice; al
# "disparar" cae a ~33° (dos veces: 7,5 y 8,0 s).
GUN_INDEX = 0.7
GUN_CURL = 1.4
GUN_COCKED_DEG = 45.0
GUN_DROP_DEG = 15.0
GUN_SHOT_GAP_S = 0.3
# El brazo del revólver suele apuntar hacia la cámara y se ve más corto que al señalar (0,7 allí).
GUN_REACH = 0.6


def _gun_hand(owner, side: str, width: int, height: int):
    """(índice estirado, dedos recogidos, ángulo del pulgar, punta del índice, dirección) o None."""
    hand = owner.left_hand if side == "left" else owner.right_hand
    if hand is None:
        return None
    lm = {l.name.replace(f"{side}_", ""): np.array([l.x * width, l.y * height]) for l in hand.landmarks}
    need = ("wrist", "index_mcp", "index_tip", "middle_mcp", "middle_tip", "ring_mcp", "ring_tip", "pinky_mcp", "pinky_tip", "thumb_mcp", "thumb_tip")
    if not all(k in lm for k in need):
        return None
    palm = max(float(np.linalg.norm(lm["middle_mcp"] - lm["wrist"])), 1e-6)
    index = float(np.linalg.norm(lm["index_tip"] - lm["index_mcp"])) / palm
    curl = float(np.mean([np.linalg.norm(lm[f"{k}_tip"] - lm["wrist"]) / max(np.linalg.norm(lm[f"{k}_mcp"] - lm["wrist"]), 1e-6) for k in ("middle", "ring", "pinky")]))
    barrel = lm["index_tip"] - lm["index_mcp"]
    thumb = lm["thumb_tip"] - lm["thumb_mcp"]
    cos = float(np.dot(barrel, thumb) / max(np.linalg.norm(barrel) * np.linalg.norm(thumb), 1e-6))
    return index, curl, float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))), lm["index_tip"], barrel


def finger_gun_events(frames, fps, width, height):
    """Revólver con la mano: la pose (brazo extendido, índice estirado, dedos recogidos) con el
    pulgar levantado en algún momento. Cada caída del pulgar es un disparo; se anotan en `detail`
    ("disparos=180,192"). Sin caída, el efecto dispara en un instante al azar de la pose."""

    def flag(record, owner, pts):
        for side in ("right", "left"):
            if f"{side}_wrist" not in pts or f"{side}_shoulder" not in pts:
                continue
            shape = _gun_hand(owner, side, width, height)
            reach = float(np.linalg.norm(pts[f"{side}_wrist"] - pts[f"{side}_shoulder"])) / _torso(pts)
            if shape is not None and reach >= GUN_REACH and shape[0] >= GUN_INDEX and shape[1] <= GUN_CURL:
                return side, shape[3]
        return None

    events = _pose_events(frames, fps, width, height, "finger_gun", "Revólver con la mano.", flag)
    by_frame = {record.frame: record for record in frames}
    out = []
    for event in events:
        person, side = event.target.split(":")[0], event.kind
        angles, barrels = [], {}
        for frame in range(event.start_frame, event.end_frame + 1):
            record = by_frame.get(frame)
            owner = next((p for p in _people(record) if p.person_id == person), None) if record else None
            shape = _gun_hand(owner, side, width, height) if owner is not None else None
            angles.append((frame, shape[2] if shape else None))
            if shape is not None:
                barrels[frame] = shape[4]
        values = [a for _, a in angles if a is not None]
        if sum(1 for a in values if a >= GUN_COCKED_DEG) < 3:
            continue  # nunca levantó el pulgar: es señalar, no un revólver
        smooth = []
        for k, (frame, _) in enumerate(angles):  # mediana de 3 contra el temblor de los dedos
            near = [a for _, a in angles[max(k - 1, 0):k + 2] if a is not None]
            smooth.append((frame, float(np.median(near)) if near else None))
        shots: list[int] = []
        for k, (frame, angle) in enumerate(smooth):
            recent = [a for _, a in smooth[max(k - 6, 0):k] if a is not None]
            if angle is None or not recent or max(recent) < GUN_COCKED_DEG:
                continue
            if angle <= max(recent) - GUN_DROP_DEG and (not shots or frame - shots[-1] >= GUN_SHOT_GAP_S * fps):
                shots.append(frame)
        event.detail = "disparos=" + ",".join(str(f) for f in shots)
        barrel = barrels.get(event.start_frame) if event.start_frame in barrels else next(iter(barrels.values()), None)
        if barrel is not None:
            event.direction_deg = float(np.degrees(np.arctan2(barrel[1], barrel[0])))
        out.append(event)
    return out


GESTURE_DETECTORS = (
    throw_events,
    neck_slash_events,
    stomp_events,
    _frenzy,
    heart_hands_events,
    arms_up_events,
    arms_open_events,
    point_events,
    hand_ear_events,
    cover_eyes_events,
    spin_body_events,
    step_events,
    rock_hands_events,
    hands_on_head_events,
    arms_x_events,
    lunge_events,
    finger_gun_events,
)
GESTURE_NAMES = {"finger_gun", "rock_hands", "hands_on_head", "arms_x", "lunge", "throw", "neck_slash", "stomp", "frenzy", "heart_hands", "arms_up", "arms_open", "point", "hand_ear", "cover_eyes", "spin_body", "step"}
