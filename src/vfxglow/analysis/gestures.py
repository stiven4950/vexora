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


def stomp_events(frames: list[FrameRecord], fps: float, width: int, height: int) -> list[MotionEvent]:
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
                if v is None or v < STOMP_SPEED or index - last < STOMP_COOLDOWN_S * fps:
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
                if not window or (ys[hit] - min(window)) / torsos[hit] < STOMP_LIFT:
                    continue
                events.append(
                    MotionEvent(
                        name="stomp",
                        target=f"{person}:{side}_ankle",
                        start_frame=frames[max(index - lookback // 2, 0)].frame,
                        end_frame=frames[hit].frame,
                        confidence=float(min(v / (2 * STOMP_SPEED), 1.0)),
                        detail="Pisotón: el pie baja rápido y se frena en el piso.",
                        position=(float(xs[hit] / width), float(ys[hit] / height)),
                        kind=side,
                    )
                )
                last = hit
    return sorted(events, key=lambda e: e.start_frame)
