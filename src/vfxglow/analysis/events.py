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
# Choque de puños: muñecas de personas distintas a menos de CLASH_RADIUS torsos, tras
# acercarse al menos CLASH_CLOSING torsos en los CLASH_WINDOW fotogramas previos.
CLASH_RADIUS = 0.35
CLASH_CLOSING = 0.4
CLASH_WINDOW = 4
CLASH_COOLDOWN = 10
# Choque de cuerpos: cajas que se solapan al menos BUMP_OVERLAP (fracción del ancho de la
# más estrecha) tras acercarse, sin golpe ni choque de puños a BUMP_QUIET fotogramas.
BUMP_OVERLAP = 0.3
BUMP_WINDOW = 4
BUMP_QUIET = 6
BUMP_COOLDOWN = 90
# Pausa: la mediana (LULL_MEDIAN fotogramas) de la actividad máxima de todos queda bajo
# LULL_SPEED durante LULL_MIN fotogramas, con acción en los LULL_AFTER previos. La mediana
# ignora un pico suelto: alguien que se acomoda la chaqueta no rompe la pausa.
LULL_SPEED = 0.12
LULL_MEDIAN = 9
LULL_MIN = 12
LULL_AFTER = 60
# Intención: en la pausa o hasta INTENT_TAIL después, una muñeca se desplaza al menos
# INTENT_MOVE torsos en INTENT_SPAN fotogramas. Se mide desplazamiento y no velocidad: llevar
# la mano al pecho es lento. Como mucho INTENT_MAX por persona y pausa, separadas INTENT_GAP.
# Golpe intencionado: swing hasta STRIKE_AFTER fotogramas después de una intención.
INTENT_MOVE = 0.35
INTENT_SPAN = 8
INTENT_TAIL = 25
INTENT_MAX = 2
INTENT_GAP = 12
STRIKE_AFTER = 45
# Tajo: la punta recorre al menos BLADE_SWING torsos por fotograma durante BLADE_FRAMES.
BLADE_SWING = 0.25
BLADE_FRAMES = 2
# Voltereta: cabeza por debajo de las caderas durante FLIP_FRAMES; aterrizaje hasta
# LAND_WITHIN fotogramas después de un salto o voltereta, cuando los tobillos dejan de subir.
FLIP_FRAMES = 3
# Torso a más de TUMBLE_TILT grados de la vertical durante TUMBLE_FRAMES: cuerpo en el aire o
# en el suelo. Más fiable que la cabeza bajo la cadera, que la pose pierde a mitad del giro.
TUMBLE_TILT = 55.0
# Foco: tramos de SPOT_WINDOW fotogramas. Un tramo cuenta si alguna parte recorre SPOT_MIN torsos;
# gana la parte que más supera su propio recorrido habitual (ver _spotlights).
SPOT_WINDOW = 36
SPOT_MIN = 0.4
SPOT_PARTS: dict[str, tuple[tuple[str, ...], float]] = {
    "left_arm": (("left_elbow", "left_wrist"), 1.0),
    "right_arm": (("right_elbow", "right_wrist"), 1.0),
    "legs": (("left_knee", "right_knee", "left_ankle", "right_ankle"), 1.0),
    "feet": (("left_heel", "right_heel", "left_foot_index", "right_foot_index"), 0.8),
    "head": (("nose", "left_ear", "right_ear"), 0.9),
    "torso": (("left_shoulder", "right_shoulder", "left_hip", "right_hip"), 0.8),
}
GROUND_WINDOW = 30
TUMBLE_FRAMES = 3
LAND_WITHIN = 20

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
    "mouth_open": "Abre la boca.",
    "blink": "Parpadea.",
    "wink": "Guiña un ojo.",
    "eyes_wide": "Abre mucho los ojos.",
    "smile": "Sonríe.",
    "brows_up": "Sube las cejas.",
    "cheeks_puff": "Infla las mejillas.",
    "pucker": "Pone los labios en beso.",
    "surprise": "Pone cara de impresión: cejas arriba con los ojos o la boca abiertos.",
    "gaze_shift": "La mirada salta a otro lado.",
    "speaking": "Habla o grita: suena fuerte y la boca se mueve.",
    "head_turn": "Gira la cabeza rápido hacia un lado.",
    "head_tilt": "Inclina la cabeza hacia un hombro.",
    "paint_stroke": "Un trazo de maquillaje o pintura nueva sobre la cara.",
    "still": "El cuerpo permanece casi quieto.",
    "person_contact": "La muñeca de una persona alcanza el torso o la cabeza de la otra.",
    "strike_windup": "Anticipación fija antes de un contacto entre personas (carga previa al golpe).",
    "strike_recoil": "Tras el contacto, la muñeca invierte su dirección (retroceso).",
    "fist_clash": "Las manos de dos personas se acercan deprisa y se tocan (choque de puños).",
    "body_bump": "Dos personas que se acercan chocan con el cuerpo (hombro con hombro).",
    "lull": "Pausa: tras un tramo de acción, todos quedan casi quietos (fin de una ronda).",
    "intent": "Durante o justo después de una pausa, una persona empieza a mover una extremidad: anuncia lo que va a hacer.",
    "intended_strike": "Golpe rápido que llega poco después de una intención de la misma persona.",
    "blade_swing": "La punta de una hoja (espada, bastón) se mueve deprisa: un tajo.",
    "blade_ground": "La punta de una hoja baja deprisa hasta el piso: golpe contra el suelo.",
    "flip": "El cuerpo queda invertido (cabeza por debajo de las caderas): voltereta o mortal.",
    "landing": "Los pies vuelven al suelo tras un salto o una voltereta.",
    "spotlight": "En este tramo, la parte del cuerpo que más se mueve (brazo, piernas, cabeza, torso, pies).",
    "tumble": "El torso se inclina mucho (acostado, de lado o boca abajo): rueda, mortal, caída.",
    "entrance": "La persona aparece al inicio del plano.",
    "tool_touch": "La mano se mueve junto al rostro, como un pincel que pinta.",
    "prop_transfer": "El objeto protagonista (p. ej. una gorra) pasa de una mano a la otra.",
    "prop_worn": "El objeto protagonista llega a la cabeza (se pone la gorra).",
    "prop_spin": "El objeto protagonista gira en las manos.",
    "face_touch": "La mano toca la cara.",
    "throw": "Amago de lanzamiento: carga con el brazo arriba y suelta de golpe extendiéndolo.",
    "heart_hands": "Las dos manos juntas frente al pecho (corazón).",
    "arms_up": "Los dos brazos arriba (victoria).",
    "arms_open": "Los brazos abiertos en cruz.",
    "point": "Señala con el índice y el brazo extendido.",
    "hand_ear": "La mano en el oído (no te oigo).",
    "cover_eyes": "La mano tapa los ojos.",
    "spin_body": "Giro sobre sí mismo (frente → espaldas → frente).",
    "step": "Paso: el pie vuelve a apoyarse en el piso.",
    "frenzy": "Todo el cuerpo se mueve mucho más de lo normal a la vez (modo discoteca).",
    "beat": "Golpe de la música (onset de audio).",
    "look": "Lugar reservado para un efecto largo de la cara.",
    "outfit": "Un outfit del desfile: la toma entre dos cortes.",
    "outfit_head": "La pieza de cabeza de un outfit del desfile.",
    "outfit_zone": "Las zonas pintadas de un outfit del desfile.",
    "outfit_reveal": "El estreno de un outfit nuevo del desfile.",
    "outfit_wave": "La onda que cruza el pantalón de un outfit del desfile.",
    "ambient": "Momento para llenar el espacio alrededor de la persona.",
    "frown": "Frunce el ceño o entrecierra los ojos.",
    "stomp": "Pisotón: el pie levantado baja rápido y se frena en el piso.",
    "neck_slash": "Corte de cuello: la mano cruza el cuello de lado (\"ya valió\").",
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
        events += self._fist_clash()
        bumps = self._body_bump(events)
        # Un choque de puños "sin historia" junto a un choque de cuerpos es el mismo encuentro.
        events = [
            event
            for event in events
            if not (_weak_clash(event) and any(abs(event.start_frame - bump.start_frame) <= BUMP_QUIET * 2 for bump in bumps))
        ]
        events += bumps
        events += self._people_swings()
        events += self._tool_touch()
        lulls = self._lulls()
        intents = self._intents(lulls)
        events += lulls + intents + self._intended_strikes(intents, events)
        swings = self._blade_swings()
        flips = self._flips()
        tumbles = self._tumbles()
        events += swings + self._blade_ground(swings) + flips + tumbles
        events += self._landings([e for e in events if e.name in {"jump", "flip", "tumble"}])
        events += self._entrance()
        events += self._spotlights()
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

    def _fist_clash(self) -> list[MotionEvent]:
        """Dos manos de personas distintas que se encuentran tras acercarse deprisa.

        Estar cerca no basta (pelean de cerca durante tramos largos): hace falta que la
        distancia se haya cerrado rápido justo antes.
        """
        from vfxglow.analysis.schema import MotionEvent

        width, height = self.meta.width, self.meta.height
        closest: dict[int, tuple[float, str, str, np.ndarray, np.ndarray]] = {}
        for index, frame in enumerate(self.frames):
            if len(frame.people) < 2:
                continue
            a, b = frame.people[0], frame.people[1]
            scale = _torso_px(a, width, height) or _torso_px(b, width, height)
            if not scale:
                continue
            best = None
            for wa in ("left_wrist", "right_wrist"):
                pa = _person_point(a, wa)
                for wb in ("left_wrist", "right_wrist"):
                    pb = _person_point(b, wb)
                    if pa is None or pb is None:
                        continue
                    va, vb = np.array([pa[0] * width, pa[1] * height]), np.array([pb[0] * width, pb[1] * height])
                    dist = float(np.linalg.norm(va - vb)) / scale
                    if best is None or dist < best[0]:
                        best = (dist, f"{a.person_id}:{wa}", f"{b.person_id}:{wb}", va, vb)
            if best is not None:
                closest[index] = best
        events: list[MotionEvent] = []
        last = -10_000
        for index, (dist, key_a, key_b, va, vb) in sorted(closest.items()):
            if dist > CLASH_RADIUS or index - last < CLASH_COOLDOWN:
                continue
            before = [closest[i] for i in range(index - CLASH_WINDOW, index) if i in closest]
            if before:
                if before[0][0] - dist < CLASH_CLOSING:
                    continue
            elif dist > CLASH_RADIUS * 0.5:
                # Sin historia (el tracker acaba de recuperar a la segunda persona) solo cuenta
                # si las manos ya aparecen juntas.
                continue
            else:
                before = []
            # Quien más movió la mano en la ventana es el que lanza el golpe.
            moved_a = float(np.linalg.norm(va - before[0][3])) if before else 0.0
            moved_b = float(np.linalg.norm(vb - before[0][4])) if before else 0.0
            attacker, receiver = (key_a, key_b) if moved_a >= moved_b else (key_b, key_a)
            mid = (va + vb) * 0.5
            events.append(
                MotionEvent(
                    name="fist_clash",
                    target=attacker,
                    start_frame=index,
                    end_frame=index,
                    confidence=float(min(1.0, (before[0][0] - dist) / (2 * CLASH_CLOSING))) if before else 0.5,
                    detail=EVENT_CATALOG["fist_clash"] + ("" if before else WEAK_CLASH),
                    position=(float(mid[0] / width), float(mid[1] / height)),
                    attacker=attacker.split(":", 1)[0],
                    receiver=receiver.split(":", 1)[0],
                )
            )
            last = index
        return events

    def _body_bump(self, found: list[MotionEvent]) -> list[MotionEvent]:
        """Dos cuerpos que se juntan: cajas solapadas tras acercarse.

        Al chocar se ocluyen y el tracker suele quedarse con una sola persona; el choque se
        fecha en ese último fotograma con las dos (o en el primero con solape fuerte).
        """
        from vfxglow.analysis.schema import MotionEvent

        busy = {
            frame
            for event in found
            if event.name in {"person_contact", "fist_clash"} and not _weak_clash(event)
            for frame in range(event.start_frame - BUMP_QUIET, event.end_frame + BUMP_QUIET + 1)
        }
        pairs: dict[int, tuple[tuple, tuple]] = {}
        for index, frame in enumerate(self.frames):
            boxes = [person.box for person in frame.people if person.box is not None]
            if len(boxes) >= 2:
                pairs[index] = (boxes[0], boxes[1])
        events: list[MotionEvent] = []
        last = -10_000
        for index, (a, b) in sorted(pairs.items()):
            if index in busy or index - last < BUMP_COOLDOWN:
                continue
            overlap = min(a[2], b[2]) - max(a[0], b[0])
            narrow = max(min(a[2] - a[0], b[2] - b[0]), 1e-6)
            merged = index + 1 < len(self.frames) and len(self.frames[index + 1].people) < 2
            # Sin fusión, el solape solo cuenta si las dos poses son fiables (con hombros).
            solid = all(
                _person_point(person, "left_shoulder") or _person_point(person, "right_shoulder")
                for person in self.frames[index].people[:2]
            )
            if overlap / narrow < BUMP_OVERLAP or not (merged or (overlap / narrow > 0.6 and solid)):
                continue
            earlier = [pairs[i] for i in range(index - BUMP_WINDOW, index) if i in pairs]
            # Si el tracker los fusiona, eso ya prueba que se juntaron; las cajas previas pueden
            # ser de poses parciales y no sirven para medir el acercamiento.
            if earlier and not merged:
                then = abs(_center(earlier[0][0])[0] - _center(earlier[0][1])[0])
                if then <= abs(_center(a)[0] - _center(b)[0]):
                    continue
            # Punto del choque: entre los dos cuerpos, a la altura de los hombros.
            x = (max(a[0], b[0]) + min(a[2], b[2])) * 0.5
            y = min(a[1], b[1]) + 0.25 * (max(a[3], b[3]) - min(a[1], b[1]))
            events.append(
                MotionEvent(
                    name="body_bump",
                    target="body",
                    start_frame=index,
                    end_frame=index,
                    confidence=float(min(1.0, overlap / narrow)),
                    detail=EVENT_CATALOG["body_bump"],
                    position=(float(x), float(y)),
                    attacker=self.frames[index].people[0].person_id,
                    receiver=self.frames[index].people[1].person_id,
                )
            )
            last = index
        return events

    def _activity(self) -> dict[str, np.ndarray]:
        """Por persona, velocidad máxima de las muñecas por fotograma (NaN si no está)."""
        series: dict[str, np.ndarray] = {}
        for index, frame in enumerate(self.frames):
            for person in frame.people:
                speeds = [m.speed for m in person.motion if m.name in ("left_wrist", "right_wrist") and not m.glitch]
                if speeds:
                    series.setdefault(person.person_id, np.full(self.n, np.nan))[index] = max(speeds)
        return {pid: _smooth_nan(values, 5) for pid, values in series.items()}

    def _lulls(self) -> list[MotionEvent]:
        from vfxglow.analysis.schema import MotionEvent

        activity = self._activity()
        if not activity:
            return []
        stacked = np.vstack(list(activity.values()))
        present = ~np.isnan(stacked)
        peak = np.where(present.any(axis=0), np.nanmax(np.where(present, stacked, -1.0), axis=0), np.nan)
        filled = np.where(np.isnan(peak), LULL_SPEED * 10, peak)
        half = LULL_MEDIAN // 2
        median = np.array([np.median(filled[max(0, i - half) : i + half + 1]) for i in range(self.n)])
        quiet = (median < LULL_SPEED) & ~np.isnan(peak)
        busy = peak >= self.cfg.swing_speed
        events: list[MotionEvent] = []
        index = 0
        while index < self.n:
            if not quiet[index]:
                index += 1
                continue
            end = index
            while end + 1 < self.n and (quiet[end + 1] or np.isnan(peak[end + 1])):
                end += 1
            if end - index + 1 >= LULL_MIN and busy[max(0, index - LULL_AFTER) : index].any():
                events.append(
                    MotionEvent(
                        name="lull",
                        target="scene",
                        start_frame=index,
                        end_frame=end,
                        confidence=1.0,
                        detail=EVENT_CATALOG["lull"],
                    )
                )
            index = end + 1
        return events

    def _intents(self, lulls: list[MotionEvent]) -> list[MotionEvent]:
        """Las muñecas que se ponen en marcha durante una pausa, por persona."""
        from vfxglow.analysis.schema import MotionEvent

        events: list[MotionEvent] = []
        people = sorted({p.person_id for frame in self.frames for p in frame.people})
        for lull in lulls:
            for pid in people:
                found = 0
                last = -10_000
                for index in range(max(lull.start_frame, INTENT_SPAN), min(self.n, lull.end_frame + INTENT_TAIL)):
                    if found >= INTENT_MAX or index - last < INTENT_GAP:
                        continue
                    person = next((p for p in self.frames[index].people if p.person_id == pid), None)
                    before = next((p for p in self.frames[index - INTENT_SPAN].people if p.person_id == pid), None)
                    if person is None or before is None:
                        continue
                    torso = _torso_norm(person)
                    best = None
                    for joint in ("left_wrist", "right_wrist"):
                        now, then = _person_point(person, joint), _person_point(before, joint)
                        if now is None or then is None:
                            continue
                        move = float(np.hypot(now[0] - then[0], now[1] - then[1])) / torso
                        if move >= INTENT_MOVE and (best is None or move > best[0]):
                            best = (move, joint, now)
                    if best is None:
                        continue
                    move, joint, wrist = best
                    start = index - INTENT_SPAN // 2
                    # Dos pausas seguidas comparten ventana: la misma intención no se cuenta dos veces.
                    if any(e.attacker == pid and abs(e.start_frame - start) < INTENT_GAP for e in events):
                        continue
                    events.append(
                        MotionEvent(
                            name="intent",
                            target=f"{pid}:{joint}",
                            start_frame=start,
                            end_frame=index,
                            confidence=float(min(1.0, move)),
                            detail=EVENT_CATALOG["intent"],
                            position=wrist,
                            peak_speed=move / INTENT_SPAN,
                            attacker=pid,
                            kind=_intent_kind(person, joint, self._rival(index, pid)),
                        )
                    )
                    found += 1
                    last = index
        return events

    def _rival(self, index: int, pid: str):
        return next((p for p in self.frames[index].people if p.person_id != pid), None)

    def _intended_strikes(self, intents: list[MotionEvent], found: list[MotionEvent]) -> list[MotionEvent]:
        from vfxglow.analysis.schema import MotionEvent

        strikes: list[MotionEvent] = []
        taken: set[tuple[int, str]] = set()
        for intent in intents:
            pid = intent.attacker
            swing = next(
                (
                    e
                    for e in sorted(found, key=lambda e: e.start_frame)
                    if e.name == "fast_swing"
                    and e.target.startswith(f"{pid}:")
                    and intent.start_frame < e.start_frame <= intent.end_frame + STRIKE_AFTER
                ),
                None,
            )
            if swing is not None and (swing.start_frame, swing.target) not in taken:
                taken.add((swing.start_frame, swing.target))
                strikes.append(
                    swing.model_copy(
                        update={"name": "intended_strike", "detail": EVENT_CATALOG["intended_strike"], "kind": intent.kind, "attacker": pid}
                    )
                )
        return strikes

    # ----- hojas y acrobacias -----

    def _blade_tips(self) -> dict[tuple[str, str], dict[int, np.ndarray]]:
        tips: dict[tuple[str, str], dict[int, np.ndarray]] = {}
        for index, frame in enumerate(self.frames):
            for blade in frame.blades:
                tips.setdefault((blade.person, blade.hand), {})[index] = np.array(blade.tip)
        return tips

    def _scale(self, index: int) -> float:
        """Torso en coordenadas normalizadas de alto (las de las hojas no son cuadradas)."""
        frame = self.frames[index]
        person = frame.people[0] if frame.people else None
        torso = _torso_norm(person) if person is not None else 0.2
        return max(torso, 0.05)

    def _blade_swings(self) -> list[MotionEvent]:
        from vfxglow.analysis.schema import MotionEvent

        aspect = self.meta.width / max(self.meta.height, 1)
        events: list[MotionEvent] = []
        for (person, hand), tips in self._blade_tips().items():
            fast = []
            for index, tip in tips.items():
                before = tips.get(index - 1)
                if before is None:
                    continue
                step = float(np.hypot((tip[0] - before[0]) * aspect, tip[1] - before[1]))
                if step >= BLADE_SWING * self._scale(index):
                    fast.append(index)
            for start, end in _spans(fast, gap=1):
                if end - start + 1 < BLADE_FRAMES:
                    continue
                peak = tips[end]
                events.append(
                    MotionEvent(
                        name="blade_swing",
                        target=f"{person}:blade_{hand}_tip",
                        start_frame=start,
                        end_frame=end,
                        confidence=0.8,
                        detail=EVENT_CATALOG["blade_swing"],
                        position=(float(peak[0]), float(peak[1])),
                        attacker=person,
                    )
                )
        return events

    def _floor(self, index: int) -> float | None:
        """Altura del piso: el tobillo más bajo, normalizado."""
        ys = [lm.y for lm in self.frames[index].pose if lm.name in ("left_ankle", "right_ankle", "left_heel", "right_heel") and lm.c > 0.3]
        return max(ys) if ys else None

    def _ground(self, index: int) -> float | None:
        """Piso estable: el pie más bajo en un entorno de ±GROUND_WINDOW fotogramas.

        Con el tobillo del propio fotograma, una persona en el aire "lleva el piso" consigo.
        """
        lows = [self._floor(i) for i in range(max(0, index - GROUND_WINDOW), min(self.n, index + GROUND_WINDOW + 1))]
        lows = [y for y in lows if y is not None]
        return float(np.percentile(lows, 90)) if lows else None

    def _blade_ground(self, swings: list[MotionEvent]) -> list[MotionEvent]:
        from vfxglow.analysis.schema import MotionEvent

        events = []
        for swing in swings:
            floor = self._ground(swing.end_frame)
            if floor is None or swing.position is None:
                continue
            if swing.position[1] >= floor - 0.04:
                events.append(
                    swing.model_copy(update={"name": "blade_ground", "detail": EVENT_CATALOG["blade_ground"], "position": (swing.position[0], floor)})
                )
        return events

    def _flips(self) -> list[MotionEvent]:
        inverted = np.zeros(self.n, dtype=bool)
        for index, frame in enumerate(self.frames):
            pts = {lm.name: lm.y for lm in frame.pose if lm.c > 0.3}
            if "nose" in pts and "left_hip" in pts and "right_hip" in pts:
                inverted[index] = pts["nose"] > (pts["left_hip"] + pts["right_hip"]) * 0.5
        out = []
        for start, end in _runs(inverted):
            if end - start + 1 >= FLIP_FRAMES:
                event = self._event("flip", "mid_hip", start, end, 0.8, EVENT_CATALOG["flip"])
                event.position = self._mid_hip((start + end) // 2)
                out.append(event)
        return out

    def _tumbles(self) -> list[MotionEvent]:
        aspect = self.meta.width / max(self.meta.height, 1)
        tilted = np.zeros(self.n, dtype=bool)
        for index, frame in enumerate(self.frames):
            pts = {lm.name: (lm.x * aspect, lm.y) for lm in frame.pose if lm.c > 0.3}
            need = ("left_shoulder", "right_shoulder", "left_hip", "right_hip")
            if not all(name in pts for name in need):
                continue
            shoulders = np.mean([pts["left_shoulder"], pts["right_shoulder"]], axis=0)
            hips = np.mean([pts["left_hip"], pts["right_hip"]], axis=0)
            up = shoulders - hips
            if np.linalg.norm(up) < 1e-6:
                continue
            tilt = np.degrees(np.arccos(np.clip(-up[1] / np.linalg.norm(up), -1.0, 1.0)))
            tilted[index] = tilt > TUMBLE_TILT
        out = []
        for start, end in _runs(tilted):
            if end - start + 1 >= TUMBLE_FRAMES:
                event = self._event("tumble", "mid_hip", start, end, 0.8, EVENT_CATALOG["tumble"])
                event.position = self._mid_hip((start + end) // 2)
                out.append(event)
        return out

    def _landings(self, airborne: list[MotionEvent]) -> list[MotionEvent]:
        out = []
        for event in sorted(airborne, key=lambda e: e.end_frame):
            if out and event.end_frame - out[-1].start_frame < LAND_WITHIN:
                continue
            for index in range(event.end_frame, min(self.n - 1, event.end_frame + LAND_WITHIN)):
                floor, after = self._floor(index), self._floor(index + 1)
                if floor is not None and after is not None and after <= floor + 0.003:
                    pts = {lm.name: (lm.x, lm.y) for lm in self.frames[index].pose if lm.c > 0.3}
                    feet = [pts[name] for name in ("left_ankle", "right_ankle") if name in pts]
                    landing = self._event("landing", "feet", index, index, 0.7, EVENT_CATALOG["landing"])
                    ground = self._ground(index)
                    landing.position = (float(np.mean([f[0] for f in feet])), ground) if feet and ground is not None else None
                    out.append(landing)
                    break
        return out

    def _entrance(self) -> list[MotionEvent]:
        first = next((index for index, frame in enumerate(self.frames) if frame.pose), None)
        if first is None or first > 15:
            return []
        event = self._event("entrance", "nose", first, first, 1.0, EVENT_CATALOG["entrance"])
        event.attacker = self.frames[first].people[0].person_id if self.frames[first].people else "person_0"
        return [event]

    def _spotlights(self) -> list[MotionEvent]:
        """Por tramo y persona, la parte que más se mueve respecto a lo habitual para esa parte.

        En un baile los brazos siempre recorren más que la cabeza o el torso; comparar recorridos
        crudos elegiría casi siempre un brazo. Se divide el recorrido de cada parte en el tramo
        por su mediana en todo el video: gana lo que se mueve más de lo normal.
        """
        from vfxglow.analysis.schema import MotionEvent

        aspect = self.meta.width / max(self.meta.height, 1)
        people = sorted({p.person_id for frame in self.frames for p in frame.people}) or ["person_0"]
        windows = list(range(0, self.n, SPOT_WINDOW))
        events: list[MotionEvent] = []
        for pid in people:
            table: list[tuple[int, int, dict[str, float], object]] = []
            for start in windows:
                end = min(start + SPOT_WINDOW, self.n) - 1
                travel = {part: 0.0 for part in SPOT_PARTS}
                torsos, previous, middle = [], None, None
                for index in range(start, end + 1):
                    frame = self.frames[index]
                    person = next((p for p in frame.people if p.person_id == pid), None)
                    pose = person.pose if person is not None else (frame.pose if pid == "person_0" else [])
                    pts = {lm.name: np.array([lm.x * aspect, lm.y]) for lm in pose if lm.c > 0.5}
                    if person is not None:
                        torsos.append(_torso_norm(person))
                        middle = person
                    if previous is not None:
                        for part, (joints, _w) in SPOT_PARTS.items():
                            steps = [np.linalg.norm(pts[j] - previous[j]) for j in joints if j in pts and j in previous]
                            if steps:
                                travel[part] += float(np.mean(steps))
                    previous = pts
                torso = max(float(np.median(torsos)) if torsos else 0.2, 0.05)
                table.append((start, end, {k: v / torso for k, v in travel.items()}, middle))
            typical = {part: max(float(np.median([row[2][part] for row in table])), 0.05) for part in SPOT_PARTS}
            for start, end, travel, middle in table:
                if max(travel.values()) < SPOT_MIN:
                    continue  # tramo quieto: nada que resaltar
                scored = {part: travel[part] / typical[part] * SPOT_PARTS[part][1] for part in travel}
                part, score = max(scored.items(), key=lambda item: item[1])
                events.append(
                    MotionEvent(
                        name="spotlight",
                        target=f"{pid}:{part}",
                        start_frame=start,
                        end_frame=end,
                        confidence=float(min(1.0, score / 3.0)),
                        detail=EVENT_CATALOG["spotlight"],
                        position=_person_point(middle, "mid") if middle is not None else None,
                        attacker=pid,
                        kind=part,
                    )
                )
        return events

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


def _spans(frames: list[int], gap: int = 1) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for frame in sorted(frames):
        if spans and frame - spans[-1][1] <= gap:
            spans[-1] = (spans[-1][0], frame)
        else:
            spans.append((frame, frame))
    return spans


def _smooth_nan(values: np.ndarray, size: int) -> np.ndarray:
    """Media móvil que ignora los huecos (NaN) y los conserva."""
    filled = np.nan_to_num(values, nan=0.0)
    weight = (~np.isnan(values)).astype(np.float64)
    kernel = np.ones(size)
    total = np.convolve(filled, kernel, mode="same")
    count = np.convolve(weight, kernel, mode="same")
    out = np.where(count > 0, total / np.maximum(count, 1e-9), np.nan)
    out[np.isnan(values)] = np.nan
    return out


def _intent_kind(person, joint: str, rival) -> str:
    """Qué anuncia la mano: al pecho, guardia alta, brazo atrás (carga) o solo se agita."""
    side = joint.split("_", 1)[0]
    wrist = _person_point(person, joint)
    shoulder = _person_point(person, f"{side}_shoulder")
    chest = _person_point(person, "mid")
    nose = _person_point(person, "nose")
    if wrist is None or shoulder is None:
        return "stir"
    torso = _torso_norm(person)
    if chest is not None and float(np.hypot(wrist[0] - chest[0], wrist[1] - chest[1])) < 0.45 * torso:
        return "hand_to_chest"
    if nose is not None and wrist[1] < shoulder[1] and float(np.hypot(wrist[0] - nose[0], wrist[1] - nose[1])) < 0.8 * torso:
        return "guard_up"
    if rival is not None:
        target = _person_point(rival, "mid")
        if target is not None and abs(wrist[0] - target[0]) > abs(shoulder[0] - target[0]):
            return "arm_back"
    return "stir"


WEAK_CLASH = " Sin historia previa: la segunda persona reapareció con las manos juntas."


def _weak_clash(event) -> bool:
    return event.name == "fist_clash" and event.detail.endswith(WEAK_CLASH)


def _center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5)


def _torso_px(person, width: int, height: int) -> float | None:
    pts = {lm.name: (lm.x * width, lm.y * height) for lm in person.pose if lm.c > 0.15}
    for side in ("left", "right"):
        if f"{side}_shoulder" in pts and f"{side}_hip" in pts:
            return float(max(np.hypot(*np.subtract(pts[f"{side}_shoulder"], pts[f"{side}_hip"])), 8.0))
    return None


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
