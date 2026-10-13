"""Pareja: unísono contra solo, y el coreógrafo que copia el efecto a la pareja o le cede el turno."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.duet import duet_at, duet_timeline
from vfxglow.analysis.schema import DuetSpan, FrameRecord, Landmark, MotionBrief, MotionEvent, PersonPose, VideoMeta
from vfxglow.director.choreography import Catalog, choreograph
from vfxglow.engine.swoosh import focused

W, H, FPS = 800, 800, 30.0
BASE = {
    "left_shoulder": (-0.06, -0.25), "right_shoulder": (0.06, -0.25), "left_hip": (-0.05, 0.0), "right_hip": (0.05, 0.0),
    "left_elbow": (-0.1, -0.15), "right_elbow": (0.1, -0.15), "left_wrist": (-0.12, -0.05), "right_wrist": (0.12, -0.05),
    "left_knee": (-0.05, 0.15), "right_knee": (0.05, 0.15), "left_ankle": (-0.05, 0.3), "right_ankle": (0.05, 0.3),
}


def _person(pid: str, cx: float, i: int, kick: bool = False) -> PersonPose:
    """Persona que sube y baja los brazos; con `kick`, en cambio, brazos arriba y patada lateral."""
    lift = 0.22 if kick else 0.12 * np.sin(i * 0.25)
    knee = 0.3 * abs(np.sin(i * 0.3)) if kick else 0.0
    lms = []
    for name, (x, y) in BASE.items():
        dy = -lift if "wrist" in name else (-lift / 2 if "elbow" in name else 0.0)
        dx = knee if name in ("left_knee", "left_ankle") else 0.0
        lms.append(Landmark(name=name, x=cx + x + dx, y=0.5 + y + dy, c=0.95))
    return PersonPose(person_id=pid, pose=lms)


def _frames(kick_b) -> list[FrameRecord]:
    return [
        FrameRecord(frame=i, time_s=i / FPS, people=[_person("person_0", 0.3, i), _person("person_1", 0.7, i, kick_b(i))])
        for i in range(240)
    ]


def test_same_steps_are_unison_and_different_steps_are_a_solo() -> None:
    spans = duet_timeline(_frames(lambda i: i >= 120), FPS, W, H)
    assert duet_at(spans, 50).mode == "unison"
    assert duet_at(spans, 190).mode == "solo"


def test_one_person_is_not_a_duet() -> None:
    frames = [FrameRecord(frame=i, time_s=i / FPS, people=[_person("person_0", 0.5, i)]) for i in range(60)]
    assert duet_timeline(frames, FPS, W, H) == []


def _brief(events: list[MotionEvent], duet: list[DuetSpan]) -> MotionBrief:
    meta = VideoMeta(path="x", fps=30.0, width=100, height=100, frame_count=300, duration_s=10.0)
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="", duet=duet)


def _catalog() -> Catalog:
    return Catalog.model_validate(
        {
            "name": "t",
            "duet": True,
            "defaults": {"type": "adornment", "target": {"kind": "joint", "id": "body"}},
            "reactions": [
                {"action": "spotlight", "options": [{"name": "rodillas", "effects": [{"style": {"shapes": ["knee_dots"]}, "trigger": {"hold": 4}}]}]},
                {"action": "hand_ear", "options": [{"name": "corona", "effects": [{"style": {"shapes": ["crown"]}, "trigger": {"hold": 4}}]}]},
            ],
        }
    )


def _spot(person: str, frame: int) -> MotionEvent:
    return MotionEvent(name="spotlight", target=person, start_frame=frame, end_frame=frame + 30, confidence=1.0, kind="legs")


def test_in_unison_the_partner_gets_the_same_effect() -> None:
    duet = [DuetSpan(start_frame=0, end_frame=299, mode="unison", leader="person_0", partner="person_1")]
    script, choreo = choreograph(_catalog(), _brief([_spot("person_0", 10), _spot("person_1", 12)], duet))
    twins = [e for e in script.effects if e.id.endswith("_pareja")]
    assert twins and twins[0].triggers[0].targets == ["person_1"]
    # La pareja no enciende otro efecto propio encima.
    own = [d.choice for d in choreo.decisions if d.target == "person_1" and not d.choice.endswith("(espejo)")]
    assert own and own[0].startswith("nada")
    assert all(e.style.by_person for e in script.effects)


def test_in_a_solo_only_the_leader_lights_up_but_a_gesture_answers() -> None:
    duet = [DuetSpan(start_frame=0, end_frame=299, mode="solo", leader="person_1", partner="person_0")]
    crown = MotionEvent(name="hand_ear", target="person_0:right", start_frame=40, end_frame=50, confidence=1.0, attacker="person_0", kind="right")
    script, choreo = choreograph(_catalog(), _brief([_spot("person_0", 10), _spot("person_1", 12), crown], duet))
    picked = {(d.target, d.choice) for d in choreo.decisions}
    assert ("person_0", "nada (turno de la pareja)") in picked
    assert ("person_1", "rodillas") in picked
    assert ("person_0:right", "corona") in picked
    assert not [e for e in script.effects if e.id.endswith("_pareja")]


def test_an_event_naming_a_person_focuses_all_their_limbs() -> None:
    event = MotionEvent(name="spotlight", target="person_1", start_frame=0, end_frame=5, confidence=1.0)
    assert focused(event, "person_1:left_wrist")
    assert not focused(event, "person_0:left_wrist")
