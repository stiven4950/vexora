"""Línea de atención: quién es el protagonista en cada momento (ver docs/criterio_de_analisis.md, P1).

Por fotograma y persona se puntúa cada región:

- Partes del cuerpo (`left_arm`, `right_arm`, `legs`, `head`, `torso`): recorrido de sus
  articulaciones en una ventana corta, en torsos, dividido por lo habitual para esa parte en el
  video. Vale 1 lo normal; lo que se mueve más de lo normal pasa de 1.
- `prop` (el objeto protagonista): en las manos o en el aire manda (PROP_SCORE más el
  movimiento de la mano que lo sostiene, que deja de contar como brazo); puesto, no.
- `head`: si la mano toca la cara (`face_touch`, y un momento después: el jalón) o el objeto llega
  a la cabeza (`prop_worn`), manda la cabeza; con todo el cuerpo quieto, la atención pasa a la
  mirada (STILL_HEAD).
- Transferencia: al soltar la cara, el brazo de esa mano hereda el foco (TRANSFER_S).

El primer foco es la región con más puntuación; hay un segundo foco si otra región, distinta y
alejada, también destaca (SECOND_MIN): un pie que pinta el piso mientras las manos lanzan la gorra.
El primer foco solo cambia si otra región lo supera con margen durante HOLD fotogramas
(histéresis), para que no parpadee.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import AttentionSpan, FrameRecord, MotionEvent, PersonPose

REGIONS: dict[str, tuple[str, ...]] = {
    "left_arm": ("left_elbow", "left_wrist"),
    "right_arm": ("right_elbow", "right_wrist"),
    "legs": ("left_knee", "right_knee", "left_ankle", "right_ankle", "left_foot_index", "right_foot_index"),
    "head": ("nose", "left_ear", "right_ear"),
    "torso": ("left_shoulder", "right_shoulder", "left_hip", "right_hip"),
}
# Peso de cada parte (la cabeza y el torso destacan menos aunque se muevan igual de "raro").
WEIGHTS = {"left_arm": 1.0, "right_arm": 1.0, "legs": 1.0, "head": 0.85, "torso": 0.75}
WINDOW_S = 0.4
PROP_SCORE = 2.0
TOUCH_SCORE = 2.6
WORN_SCORE = 2.2
STILL_HEAD = 1.1
# Todo el cuerpo por debajo de esto (relativo) = quieto.
STILL_BODY = 0.55
SECOND_MIN = 1.5
SWITCH_MARGIN = 1.15
HOLD_S = 0.2
MIN_SPAN_S = 0.4
# Tras soltar la cara, la cabeza sigue mandando lo que dura el jalón, y luego el brazo de esa
# mano hereda el foco un rato.
TOUCH_AFTER_S = 0.4
TRANSFER_S = 1.4
TRANSFER_SCORE = 2.5
# Gestos: lanzamiento (el brazo, durante la carga y un poco tras la suelta) y corte de cuello
# (la cabeza, mientras duran los ojos en X y las gafas).
GESTURE_SCORE = 2.6
GESTURE_AFTER_S = 0.6
SLASH_AFTER_S = 1.2


def _people(record: FrameRecord) -> list[PersonPose]:
    if record.people:
        return record.people
    if record.pose:
        return [PersonPose(person_id=record.person_id, pose=record.pose)]
    return []


def _travel(frames: list[FrameRecord], person: str, width: int, height: int) -> dict[str, np.ndarray]:
    """Recorrido por fotograma de cada región, en torsos."""
    out = {region: np.zeros(len(frames)) for region in REGIONS}
    previous: dict[str, np.ndarray] | None = None
    for index, record in enumerate(frames):
        owner = next((p for p in _people(record) if p.person_id == person), None)
        if owner is None:
            previous = None
            continue
        pts = {lm.name: np.array([lm.x * width, lm.y * height]) for lm in owner.pose if lm.c > 0.5}
        torso = 0.0
        if "left_shoulder" in pts and "left_hip" in pts:
            torso = float(np.linalg.norm(pts["left_shoulder"] - pts["left_hip"]))
        torso = max(torso, height * 0.08)
        if previous is not None:
            for region, joints in REGIONS.items():
                steps = [np.linalg.norm(pts[j] - previous[j]) for j in joints if j in pts and j in previous]
                if steps:
                    out[region][index] = float(np.mean(steps)) / torso
        previous = pts
    return out


def _windows(events: list[MotionEvent], names: tuple[str, ...], person: str, n: int, frame_of: dict[int, int], after: int = 0) -> np.ndarray:
    mask = np.zeros(n, dtype=bool)
    for event in events:
        if event.name in names and event.target.split(":")[0] == person:
            first, last = frame_of.get(event.start_frame), frame_of.get(min(event.end_frame + after, max(frame_of)))
            if first is not None and last is not None:
                mask[first : last + 1] = True
    return mask


def attention_timeline(frames: list[FrameRecord], events: list[MotionEvent], fps: float, width: int, height: int) -> list[AttentionSpan]:
    if not frames:
        return []
    n = len(frames)
    frame_of = {record.frame: index for index, record in enumerate(frames)}
    window = max(int(WINDOW_S * fps), 1)
    kernel = np.ones(window) / window
    people = sorted({p.person_id for record in frames for p in _people(record)})
    spans: list[AttentionSpan] = []
    for person in people:
        travel = _travel(frames, person, width, height)
        scores: dict[str, np.ndarray] = {}
        for region, steps in travel.items():
            smooth = np.convolve(steps, kernel, mode="same")
            moving = smooth[smooth > 1e-4]
            typical = max(float(np.median(moving)) if moving.size else 1.0, 1e-3)
            scores[region] = smooth / typical * WEIGHTS[region]
        body = np.max(np.stack(list(scores.values())), axis=0)
        # El objeto en las manos absorbe a la mano que lo sostiene: lo que mueve esa mano es
        # el objeto moviéndose (P5).
        prop = np.zeros(n)
        for index, record in enumerate(frames):
            state = record.prop.state if record.prop is not None and record.prop.person == person else None
            if state not in ("left", "right", "both", "air"):
                continue
            holders = {"left": ("left_arm",), "right": ("right_arm",), "both": ("left_arm", "right_arm"), "air": ()}[state]
            prop[index] = PROP_SCORE + max((scores[arm][index] for arm in holders), default=0.0)
            for arm in holders:
                scores[arm][index] = 0.0
        scores["prop"] = prop
        # Al soltar la cara, la energía sale por la mano que la tocaba: su brazo hereda el foco (P3).
        for event in events:
            if event.name == "face_touch" and event.target.split(":")[0] == person and event.kind in ("left", "right"):
                first = frame_of.get(event.end_frame)
                if first is not None:
                    arm = f"{event.kind}_arm"
                    stop = min(first + int((TOUCH_AFTER_S + TRANSFER_S) * fps), n)
                    scores[arm][first:stop] = np.maximum(scores[arm][first:stop], TRANSFER_SCORE)
        # Un gesto con significado se lleva la atención mientras dura (P4).
        for event in events:
            if event.target.split(":")[0] != person:
                continue
            first, last = frame_of.get(event.start_frame), frame_of.get(event.end_frame)
            if first is None or last is None:
                continue
            if event.name == "throw" and event.kind in ("left", "right"):
                arm = f"{event.kind}_arm"
                stop = min(last + int(GESTURE_AFTER_S * fps), n)
                scores[arm][first:stop] = np.maximum(scores[arm][first:stop], GESTURE_SCORE)
        slash = _windows(events, ("neck_slash",), person, n, frame_of, after=int(SLASH_AFTER_S * fps))
        touch = _windows(events, ("face_touch",), person, n, frame_of, after=int(TOUCH_AFTER_S * fps))
        worn = _windows(events, ("prop_worn",), person, n, frame_of)
        head = scores["head"].copy()
        head = np.where(body < STILL_BODY, np.maximum(head, STILL_HEAD), head)
        head = np.where(worn, np.maximum(head, WORN_SCORE), head)
        head = np.where(touch, np.maximum(head, TOUCH_SCORE), head)
        head = np.where(slash, np.maximum(head, GESTURE_SCORE), head)
        scores["head"] = head
        spans += _spans(scores, frames, person, fps)
    return spans


def _spans(scores: dict[str, np.ndarray], frames: list[FrameRecord], person: str, fps: float) -> list[AttentionSpan]:
    regions = list(scores)
    table = np.stack([scores[r] for r in regions])
    hold = max(int(HOLD_S * fps), 1)
    primary: list[str] = []
    current, challenger, streak = None, None, 0
    for index in range(table.shape[1]):
        column = table[:, index]
        best = regions[int(np.argmax(column))]
        if current is None:
            current = best
        elif best != current and column[regions.index(best)] > column[regions.index(current)] * SWITCH_MARGIN:
            streak = streak + 1 if best == challenger else 1
            challenger = best
            if streak >= hold:
                current, challenger, streak = best, None, 0
        else:
            challenger, streak = None, 0
        primary.append(current)
    secondary: list[str | None] = []
    for index, main in enumerate(primary):
        column = {r: table[k, index] for k, r in enumerate(regions) if r != main and not _overlaps(r, main)}
        other = max(column, key=column.get) if column else None
        secondary.append(other if other is not None and column[other] >= SECOND_MIN else None)
    # Tramos: se funden los de menos de MIN_SPAN_S con el anterior.
    out: list[AttentionSpan] = []
    shortest = int(MIN_SPAN_S * fps)
    start = 0
    for index in range(1, len(primary) + 1):
        if index == len(primary) or primary[index] != primary[start]:
            second = _mode(secondary[start:index])
            if out and index - start < shortest:
                out[-1] = out[-1].model_copy(update={"end_frame": frames[index - 1].frame})
            else:
                out.append(AttentionSpan(person=person, start_frame=frames[start].frame, end_frame=frames[index - 1].frame, primary=primary[start], secondary=second))
            start = index
    return out


def _overlaps(a: str, b: str) -> bool:
    """Un brazo y el objeto que sostiene no son dos focos: son el mismo."""
    return {a, b} <= {"prop", "left_arm", "right_arm"}


def _mode(values: list[str | None]) -> str | None:
    present = [v for v in values if v is not None]
    if len(present) < len(values) * 0.5:
        return None
    labels, counts = np.unique(present, return_counts=True)
    return str(labels[int(np.argmax(counts))])


def focus_at(spans: list[AttentionSpan], frame: int, person: str | None = None) -> set[str]:
    """Regiones protagonistas en ese fotograma (primera y, si hay, segunda)."""
    for span in spans:
        if span.start_frame <= frame <= span.end_frame and (person is None or span.person == person):
            return {span.primary} | ({span.secondary} if span.secondary else set())
    return set()


# Frenesí: energía media de brazos y piernas (relativa a lo habitual de cada uno) por encima de
# esto durante al menos FRENZY_MIN_S. video_33: 6-8 tramos; video_34: 3-4 por persona.
FRENZY = 2.0
FRENZY_MIN_S = 0.6
FRENZY_WINDOW_S = 0.6


def frenzy_events(frames: list[FrameRecord], fps: float, width: int, height: int) -> list[MotionEvent]:
    """frenzy: todo el cuerpo se mueve mucho más de lo normal a la vez (modo discoteca)."""
    if not frames:
        return []
    window = max(int(FRENZY_WINDOW_S * fps), 1)
    kernel = np.ones(window) / window
    events: list[MotionEvent] = []
    for person in sorted({p.person_id for record in frames for p in _people(record)}):
        travel = _travel(frames, person, width, height)
        parts = []
        for region in ("left_arm", "right_arm", "legs"):
            smooth = np.convolve(travel[region], kernel, mode="same")
            moving = smooth[smooth > 1e-4]
            parts.append(smooth / max(float(np.median(moving)) if moving.size else 1.0, 1e-3))
        energy = np.mean(np.stack(parts), axis=0)
        hot = energy > FRENZY
        index = 0
        while index < len(frames):
            if not hot[index]:
                index += 1
                continue
            end = index
            while end < len(frames) and hot[end]:
                end += 1
            if end - index >= FRENZY_MIN_S * fps:
                events.append(
                    MotionEvent(
                        name="frenzy",
                        target=person,
                        start_frame=frames[index].frame,
                        end_frame=frames[end - 1].frame,
                        confidence=float(min(energy[index:end].mean() / (2 * FRENZY), 1.0)),
                        detail="Todo el cuerpo se mueve mucho más de lo normal (modo discoteca).",
                    )
                )
            index = end
    return sorted(events, key=lambda e: e.start_frame)
