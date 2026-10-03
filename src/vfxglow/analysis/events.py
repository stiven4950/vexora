"""Detector de eventos cinemáticos. Convierte tracks en momentos con nombre.

Cada evento tiene un intervalo, la articulación u objeto que lo produce, el punto
donde ocurre y la velocidad de pico. El motor los usa como disparadores; el brief
los resume para el director. Las muestras marcadas como glitch del tracker nunca
disparan nada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from vfxglow.analysis.kinematics import _runs, torso_length_px
from vfxglow.analysis.schema import FrameRecord, MotionEvent, VideoMeta
from vfxglow.config import EventsConfig

# Anticipación antes de un contacto y búsqueda máxima del retroceso, en fotogramas.
# A 30 fps un golpe dura 1-2 fotogramas y el tracker no resuelve la aceleración previa,
# así que la preparación no se mide: el análisis es offline y conoce el contacto de antemano.
WINDUP_LEAD = 8
RECOIL_MAX = 15

EVENT_CATALOG: dict[str, str] = {
    "fast_swing": "La muñeca supera la velocidad umbral varios fotogramas seguidos.",
    "impact": "Una muñeca o tobillo frena de golpe tras moverse rápido.",
    "foot_strike": "Un pie baja con velocidad y se detiene en la parte baja del cuadro.",
    "hand_contact": "La mano se mueve y luego queda quieta, como si tocara algo.",
    "object_contact": "La mano permanece junto a un objeto detectado.",
    "held_object": "La mano acompaña al mismo objeto durante un tramo largo.",
    "turn": "El vector de hombros gira deprisa.",
    "jump": "Caderas y tobillos suben juntos y vuelven a bajar.",
    "hand_open": "La mano se abre.",
    "hand_closed": "La mano se cierra.",
    "arms_crossed": "Las muñecas cruzan la línea media del cuerpo.",
    "raise_hand": "La muñeca sube por encima del hombro.",
    "still": "El cuerpo permanece casi quieto.",
    "person_contact": "La muñeca de una persona alcanza el torso o la cabeza de la otra.",
    "strike_windup": "Anticipación fija antes de un contacto entre personas (carga previa al golpe).",
    "strike_recoil": "Tras el contacto, la muñeca invierte su dirección (retroceso).",
    "tool_touch": "La mano se mueve junto al rostro, como un pincel que pinta.",
}


@dataclass
class _JointSeries:
    x: np.ndarray
    y: np.ndarray
    ok: np.ndarray
    speed: np.ndarray
    vx: np.ndarray
    vy: np.ndarray
    direction: np.ndarray


class EventDetector:
    def __init__(self, cfg: EventsConfig) -> None:
        self.cfg = cfg

    def detect(self, frames: list[FrameRecord], meta: VideoMeta) -> list[MotionEvent]:
        if not frames:
            return []
        self.n = len(frames)
        self.frames = frames
        self.meta = meta
        self.series = {
            name: self._joint(name)
            for name in ("left_wrist", "right_wrist", "left_ankle", "right_ankle", "nose")
        }
        events: list[MotionEvent] = []
        for side in ("left", "right"):
            wrist = f"{side}_wrist"
            events += self._fast_swing(wrist)
            events += self._impacts(wrist, "impact")
            events += self._hand_contact(wrist)
            events += self._hand_state(side, wrist)
            events += self._raise(side, wrist)
            events += self._object_contact(wrist)
            events += self._impacts(f"{side}_ankle", "foot_strike")
        events += self._turn()
        events += self._jump()
        events += self._arms_crossed()
        events += self._still()
        contacts = self._person_contact()
        events += contacts
        events += self._strike_phases(contacts)
        events += self._people_swings()
        events += self._tool_touch()
        events.sort(key=lambda event: (event.start_frame, event.name))
        return events

    # ----- series -----

    def _joint(self, name: str) -> _JointSeries:
        n = self.n
        x = np.full(n, np.nan)
        y = np.full(n, np.nan)
        ok = np.zeros(n, dtype=bool)
        speed = np.zeros(n)
        vx = np.zeros(n)
        vy = np.zeros(n)
        direction = np.zeros(n)
        for i, frame in enumerate(self.frames):
            for lm in frame.pose:
                if lm.name == name and lm.c > 0:
                    x[i], y[i] = lm.x, lm.y
                    ok[i] = True
                    break
            for item in frame.motion:
                if item.name == name:
                    if item.glitch:
                        ok[i] = False
                        speed[i] = 0.0
                    else:
                        speed[i] = item.speed
                        vx[i], vy[i] = item.vx, item.vy
                        direction[i] = item.direction_deg
                    break
        return _JointSeries(x, y, ok, speed, vx, vy, direction)

    def _pos(self, s: _JointSeries, i: int) -> tuple[float, float] | None:
        if not s.ok[i] or not np.isfinite(s.x[i]):
            return None
        return (float(s.x[i]), float(s.y[i]))

    def _event(
        self,
        name: str,
        target: str,
        start: int,
        end: int,
        confidence: float,
        detail: str,
        s: _JointSeries | None = None,
        at: int | None = None,
        **extra,
    ) -> MotionEvent:
        position = None
        peak = 0.0
        direction = 0.0
        if s is not None:
            window = s.speed[start : end + 1]
            if len(window):
                peak_index = start + int(np.argmax(window))
                peak = float(window.max())
                direction = float(s.direction[peak_index])
            index = at if at is not None else start
            position = self._pos(s, index)
        return MotionEvent(
            name=name,
            target=target,
            start_frame=start,
            end_frame=end,
            confidence=float(np.clip(confidence, 0.0, 1.0)),
            detail=detail,
            position=position,
            peak_speed=peak,
            direction_deg=direction,
            **extra,
        )

    # ----- detectores -----

    def _fast_swing(self, joint: str) -> list[MotionEvent]:
        s = self.series[joint]
        fast = (s.speed > self.cfg.swing_speed) & s.ok
        out = []
        for start, end in _runs(fast):
            if end - start + 1 >= self.cfg.swing_frames:
                peak = start + int(np.argmax(s.speed[start : end + 1]))
                out.append(
                    self._event(
                        "fast_swing",
                        joint,
                        start,
                        end,
                        min(1.0, s.speed[peak] / (self.cfg.swing_speed * 3)),
                        EVENT_CATALOG["fast_swing"],
                        s,
                        at=peak,
                    )
                )
        return out

    def _impacts(self, joint: str, name: str) -> list[MotionEvent]:
        s = self.series[joint]
        out = []
        last = -100
        for i in range(2, self.n):
            if not (s.ok[i] and s.ok[i - 1] and s.ok[i - 2]):
                continue
            before = max(s.speed[i - 1], s.speed[i - 2])
            drop = before - s.speed[i]
            if before < self.cfg.swing_speed * 0.8 or drop < self.cfg.impact_decel:
                continue
            if i - last < 4:
                continue
            if name == "foot_strike":
                if s.vy[i - 1] <= 0 or not np.isfinite(s.y[i]) or s.y[i] < 0.55:
                    continue
            last = i
            event = self._event(
                name,
                joint,
                i,
                i,
                min(1.0, drop / (self.cfg.impact_decel * 3)),
                EVENT_CATALOG[name],
                s,
                at=i,
            )
            event.direction_deg = float(s.direction[i - 1])
            event.peak_speed = float(before)
            out.append(event)
        return out

    def _hand_contact(self, joint: str) -> list[MotionEvent]:
        s = self.series[joint]
        moving = (s.speed > self.cfg.swing_speed * 0.5) & s.ok
        still = (s.speed < 0.035) & s.ok
        out = []
        for start, end in _runs(still):
            if end - start + 1 < self.cfg.contact_hold or start < 2:
                continue
            if not moving[max(0, start - 4) : start].any():
                continue
            out.append(
                self._event(
                    "hand_contact",
                    joint,
                    start,
                    end,
                    0.75,
                    EVENT_CATALOG["hand_contact"],
                    s,
                    at=start,
                )
            )
        return out

    def _hand_state(self, side: str, joint: str) -> list[MotionEvent]:
        s = self.series[joint]
        state = np.zeros(self.n, dtype=np.int8)
        current = 0
        for i, frame in enumerate(self.frames):
            hand = frame.hand_state.get(side)
            if hand is None or not hand.valid:
                state[i] = 0
                continue
            if hand.openness >= self.cfg.open_threshold:
                current = 1
            elif hand.openness <= self.cfg.closed_threshold:
                current = -1
            state[i] = current
        out = []
        for value, name in ((1, "hand_open"), (-1, "hand_closed")):
            for start, end in _runs(state == value):
                if end - start + 1 >= 4:
                    out.append(self._event(name, joint, start, end, 0.7, EVENT_CATALOG[name], s, at=start))
        return out

    def _raise(self, side: str, joint: str) -> list[MotionEvent]:
        s = self.series[joint]
        raised = np.zeros(self.n, dtype=bool)
        for i, frame in enumerate(self.frames):
            shoulder = next((lm.y for lm in frame.pose if lm.name == f"{side}_shoulder" and lm.c > 0), None)
            if shoulder is not None and s.ok[i] and s.y[i] < shoulder - 0.04:
                raised[i] = True
        return [
            self._event("raise_hand", joint, start, end, 0.8, EVENT_CATALOG["raise_hand"], s, at=start)
            for start, end in _runs(raised)
            if end - start >= 3
        ]

    def _object_contact(self, joint: str) -> list[MotionEvent]:
        s = self.series[joint]
        near: dict[int, np.ndarray] = {}
        labels: dict[int, str] = {}
        for i, frame in enumerate(self.frames):
            if not s.ok[i] or not frame.objects:
                continue
            torso = torso_length_px(frame, self.meta.width, self.meta.height)
            radius = self.cfg.contact_radius * torso
            hx, hy = s.x[i] * self.meta.width, s.y[i] * self.meta.height
            for obj in frame.objects:
                if obj.id < 0:
                    continue
                cx, cy = obj.center
                cx *= self.meta.width
                cy *= self.meta.height
                half_w = (obj.box[2] - obj.box[0]) * self.meta.width * 0.5
                half_h = (obj.box[3] - obj.box[1]) * self.meta.height * 0.5
                dx = max(abs(hx - cx) - half_w, 0.0)
                dy = max(abs(hy - cy) - half_h, 0.0)
                if math.hypot(dx, dy) <= radius:
                    near.setdefault(obj.id, np.zeros(self.n, dtype=bool))[i] = True
                    labels[obj.id] = obj.label
        out = []
        for obj_id, mask in near.items():
            for start, end in _runs(mask):
                length = end - start + 1
                if length < 3:
                    continue
                name = "held_object" if length >= self.cfg.held_frames else "object_contact"
                out.append(
                    self._event(
                        name,
                        joint,
                        start,
                        end,
                        0.8 if name == "held_object" else 0.65,
                        EVENT_CATALOG[name],
                        s,
                        at=start,
                        object_id=obj_id,
                        object_label=labels[obj_id],
                    )
                )
        return out

    def _turn(self) -> list[MotionEvent]:
        rate = np.array([abs(frame.torso_yaw_rate) for frame in self.frames])
        fast = rate > self.cfg.turn_rate_deg
        out = []
        for start, end in _runs(fast):
            if end - start + 1 >= 3:
                event = self._event(
                    "turn",
                    "mid_shoulder",
                    start,
                    end,
                    min(1.0, rate[start : end + 1].max() / (self.cfg.turn_rate_deg * 3)),
                    EVENT_CATALOG["turn"],
                )
                event.position = self._mid_shoulder(start)
                event.peak_speed = float(rate[start : end + 1].max())
                out.append(event)
        return out

    def _mid_shoulder(self, i: int) -> tuple[float, float] | None:
        pts = {lm.name: (lm.x, lm.y) for lm in self.frames[i].pose if lm.c > 0}
        if "left_shoulder" in pts and "right_shoulder" in pts:
            return (
                (pts["left_shoulder"][0] + pts["right_shoulder"][0]) * 0.5,
                (pts["left_shoulder"][1] + pts["right_shoulder"][1]) * 0.5,
            )
        return None

    def _jump(self) -> list[MotionEvent]:
        hip = np.full(self.n, np.nan)
        for i, frame in enumerate(self.frames):
            pts = {lm.name: lm.y for lm in frame.pose if lm.c > 0}
            if "left_hip" in pts and "right_hip" in pts:
                hip[i] = (pts["left_hip"] + pts["right_hip"]) * 0.5
        ankles = (self.series["left_ankle"].y + self.series["right_ankle"].y) * 0.5
        out = []
        if np.isnan(hip).all():
            return out
        window = 30
        airborne = np.zeros(self.n, dtype=bool)
        for i in range(self.n):
            if not np.isfinite(hip[i]) or not np.isfinite(ankles[i]):
                continue
            lo, hi = max(0, i - window), min(self.n, i + window)
            base_hip = np.nanmedian(hip[lo:hi])
            base_ankle = np.nanmedian(ankles[lo:hi])
            if base_hip - hip[i] > self.cfg.jump_rise and base_ankle - ankles[i] > self.cfg.jump_rise * 0.8:
                airborne[i] = True
        for start, end in _runs(airborne):
            if 2 <= end - start + 1 <= 40:
                event = self._event("jump", "mid_hip", start, end, 0.7, EVENT_CATALOG["jump"])
                peak = start + int(np.nanargmin(hip[start : end + 1]))
                event.position = self._mid_hip(peak)
                out.append(event)
        return out

    def _mid_hip(self, i: int) -> tuple[float, float] | None:
        pts = {lm.name: (lm.x, lm.y) for lm in self.frames[i].pose if lm.c > 0}
        if "left_hip" in pts and "right_hip" in pts:
            return (
                (pts["left_hip"][0] + pts["right_hip"][0]) * 0.5,
                (pts["left_hip"][1] + pts["right_hip"][1]) * 0.5,
            )
        return None

    def _arms_crossed(self) -> list[MotionEvent]:
        left = self.series["left_wrist"]
        right = self.series["right_wrist"]
        crossed = np.zeros(self.n, dtype=bool)
        for i, frame in enumerate(self.frames):
            pts = {lm.name: lm.x for lm in frame.pose if lm.c > 0}
            if not (left.ok[i] and right.ok[i] and "left_shoulder" in pts and "right_shoulder" in pts):
                continue
            shoulders = pts["left_shoulder"] - pts["right_shoulder"]
            wrists = left.x[i] - right.x[i]
            if abs(shoulders) > 0.02 and np.sign(wrists) == -np.sign(shoulders):
                crossed[i] = True
        out = []
        for start, end in _runs(crossed):
            if end - start + 1 >= 4:
                event = self._event("arms_crossed", "mid_shoulder", start, end, 0.7, EVENT_CATALOG["arms_crossed"])
                if left.ok[start] and right.ok[start]:
                    event.position = (
                        float((left.x[start] + right.x[start]) * 0.5),
                        float((left.y[start] + right.y[start]) * 0.5),
                    )
                out.append(event)
        return out

    def _still(self) -> list[MotionEvent]:
        speeds = np.array(
            [max((m.speed for m in frame.motion if not m.glitch), default=0.0) for frame in self.frames]
        )
        out = []
        for start, end in _runs(speeds < 0.02):
            if end - start >= 6:
                event = self._event("still", "person_0", start, end, 0.7, EVENT_CATALOG["still"])
                event.position = self._mid_shoulder(start)
                out.append(event)
        return out

    def _person_contact(self) -> list[MotionEvent]:
        """Muñeca rápida de A contra torso o nariz de B. El color del efecto irá por atacante."""
        hits: list[tuple[int, str, str, str, float, float, float]] = []
        for index, frame in enumerate(self.frames):
            if len(frame.people) < 2:
                continue
            for attacker in frame.people:
                for receiver in frame.people:
                    if attacker.person_id == receiver.person_id:
                        continue
                    torso = _person_point(receiver, "mid")
                    nose = _person_point(receiver, "nose")
                    reach = _torso_norm(receiver)
                    for side in ("left", "right"):
                        wrist = _person_point(attacker, f"{side}_wrist")
                        speed = _person_speed(attacker, f"{side}_wrist")
                        if wrist is None or speed < self.cfg.swing_speed:
                            continue
                        targets = [point for point in (torso, nose) if point is not None]
                        if not targets:
                            continue
                        dist = min(float(np.hypot(wrist[0] - point[0], wrist[1] - point[1])) for point in targets)
                        own = _person_point(attacker, "mid")
                        if own is not None and dist > float(np.hypot(wrist[0] - own[0], wrist[1] - own[1])):
                            continue
                        if dist > max(self.cfg.contact_radius, 1.05) * reach:
                            continue
                        hits.append((index, attacker.person_id, receiver.person_id, f"{side}_wrist", speed, wrist[0], wrist[1]))
        return _cluster_contacts(hits, EVENT_CATALOG["person_contact"])

    def _strike_phases(self, contacts: list[MotionEvent]) -> list[MotionEvent]:
        """Descompone cada contacto en approach/acceleration -> contact -> recoil.

        windup: WINDUP_LEAD fotogramas antes del contacto (anticipación, no medida).
        recoil: desde el final del contacto hasta que la muñeca se mueve en sentido opuesto al golpe.
        """
        from vfxglow.analysis.schema import MotionEvent

        phases: list[MotionEvent] = []
        for contact in contacts:
            if not contact.attacker or ":" not in contact.target:
                continue
            joint = contact.target.split(":", 1)[1]

            def motion(index: int):
                if not 0 <= index < len(self.frames):
                    return None
                return _person_motion(self.frames[index], contact.attacker, joint)

            first = max(contact.start_frame - WINDUP_LEAD, 0)
            if first < contact.start_frame:
                phases.append(
                    MotionEvent(
                        name="strike_windup",
                        target=contact.target,
                        start_frame=first,
                        end_frame=contact.start_frame - 1,
                        confidence=contact.confidence,
                        detail=EVENT_CATALOG["strike_windup"],
                        peak_speed=contact.peak_speed,
                        attacker=contact.attacker,
                        receiver=contact.receiver,
                    )
                )
            hit = motion(contact.end_frame)
            if hit is None or hit.speed <= 0:
                continue
            for index in range(contact.end_frame + 1, contact.end_frame + 1 + RECOIL_MAX):
                after = motion(index)
                if after is not None and after.vx * hit.vx + after.vy * hit.vy < 0:
                    phases.append(
                        MotionEvent(
                            name="strike_recoil",
                            target=contact.target,
                            start_frame=contact.end_frame + 1,
                            end_frame=index,
                            confidence=contact.confidence,
                            detail=EVENT_CATALOG["strike_recoil"],
                            peak_speed=float(after.speed),
                            attacker=contact.attacker,
                            receiver=contact.receiver,
                        )
                    )
                    break
        return phases

    def _people_swings(self) -> list[MotionEvent]:
        """Swings por persona, con ancla person_N:joint, para que cada color siga a su actor."""
        from vfxglow.analysis.schema import MotionEvent

        out: list[MotionEvent] = []
        for slot in (0, 1):
            person_id = f"person_{slot}"
            for joint in ("left_wrist", "right_wrist", "left_ankle", "right_ankle"):
                speed = np.zeros(self.n)
                ok = np.zeros(self.n, dtype=bool)
                xs = np.full(self.n, np.nan)
                ys = np.full(self.n, np.nan)
                for index, frame in enumerate(self.frames):
                    person = next((item for item in frame.people if item.person_id == person_id), None)
                    if person is None:
                        continue
                    for item in person.motion:
                        if item.name == joint and not item.glitch:
                            speed[index] = item.speed
                            ok[index] = item.speed > 0
                    for landmark in person.pose:
                        if landmark.name == joint and landmark.c > 0:
                            xs[index], ys[index] = landmark.x, landmark.y
                for start, end in _runs((speed > self.cfg.swing_speed) & ok):
                    if end - start + 1 < self.cfg.swing_frames:
                        continue
                    peak = start + int(np.argmax(speed[start : end + 1]))
                    position = (float(xs[peak]), float(ys[peak])) if np.isfinite(xs[peak]) else None
                    out.append(
                        MotionEvent(
                            name="fast_swing",
                            target=f"{person_id}:{joint}",
                            start_frame=start,
                            end_frame=end,
                            confidence=min(1.0, float(speed[peak])),
                            detail=EVENT_CATALOG["fast_swing"],
                            position=position,
                            peak_speed=float(speed[peak]),
                            attacker=person_id,
                        )
                    )
        return out

    def _tool_touch(self) -> list[MotionEvent]:
        """La mano trabaja junto a la cara. No es un golpe: la velocidad es moderada."""
        mask = np.zeros(self.n, dtype=bool)
        positions: list[tuple[float, float] | None] = [None] * self.n
        joints: list[str] = ["right_wrist"] * self.n
        for index, frame in enumerate(self.frames):
            if len(frame.people) > 1:
                continue
            nose = next(((lm.x, lm.y) for lm in frame.pose if lm.name == "nose" and lm.c > 0.2), None)
            if nose is None:
                continue
            for side in ("left", "right"):
                wrist = next(((lm.x, lm.y) for lm in frame.pose if lm.name == f"{side}_wrist" and lm.c > 0.2), None)
                speed = next((item.speed for item in frame.motion if item.name == f"{side}_wrist" and not item.glitch), 0.0)
                if wrist is None or not (0.02 < speed < self.cfg.swing_speed * 1.4):
                    continue
                if float(np.hypot(wrist[0] - nose[0], wrist[1] - nose[1])) < 0.16:
                    mask[index] = True
                    positions[index] = wrist
                    joints[index] = f"{side}_wrist"
                    break
        out: list[MotionEvent] = []
        for start, end in _runs(mask):
            if end - start + 1 < 4:
                continue
            point = next(pos for pos in positions[start : end + 1] if pos is not None)
            event = self._event("tool_touch", joints[start], start, end, 0.8, EVENT_CATALOG["tool_touch"])
            event.position = point
            out.append(event)
        return out


def _person_point(person, name: str) -> tuple[float, float] | None:
    pts = {lm.name: (lm.x, lm.y) for lm in person.pose if lm.c > 0.15}
    if name == "mid":
        if "left_shoulder" in pts and "right_hip" in pts:
            return (
                (pts["left_shoulder"][0] + pts["right_hip"][0]) * 0.5,
                (pts["left_shoulder"][1] + pts["right_hip"][1]) * 0.5,
            )
        return pts.get("nose")
    return pts.get(name)


def _person_motion(frame, person_id: str, name: str):
    for person in frame.people:
        if person.person_id == person_id:
            for item in person.motion:
                if item.name == name and not item.glitch:
                    return item
    return None


def _person_speed(person, name: str) -> float:
    for item in person.motion:
        if item.name == name and not item.glitch:
            return float(item.speed)
    return 0.0


def _torso_norm(person) -> float:
    pts = {lm.name: (lm.x, lm.y) for lm in person.pose if lm.c > 0.15}
    if "left_shoulder" in pts and "left_hip" in pts:
        return float(max(np.hypot(pts["left_shoulder"][0] - pts["left_hip"][0], pts["left_shoulder"][1] - pts["left_hip"][1]), 0.08))
    return 0.2


def _cluster_contacts(hits: list[tuple[int, str, str, str, float, float, float]], detail: str) -> list[MotionEvent]:
    from vfxglow.analysis.schema import MotionEvent

    if not hits:
        return []
    hits.sort(key=lambda item: item[0])
    groups: list[list[tuple]] = [[hits[0]]]
    for hit in hits[1:]:
        prev = groups[-1][-1]
        same = hit[1] == prev[1] and hit[2] == prev[2] and hit[0] <= prev[0] + 3
        if same:
            groups[-1].append(hit)
        else:
            groups.append([hit])
    events: list[MotionEvent] = []
    for group in groups:
        if len(group) < 2 and group[0][4] < 0.35:
            continue
        peak = max(group, key=lambda item: item[4])
        events.append(
            MotionEvent(
                name="person_contact",
                target=f"{peak[1]}:{peak[3]}",
                start_frame=group[0][0],
                end_frame=group[-1][0],
                confidence=min(1.0, peak[4]),
                detail=detail,
                position=(peak[5], peak[6]),
                peak_speed=peak[4],
                attacker=peak[1],
                receiver=peak[2],
            )
        )
    return events
