"""Protagonistas: el público no entra al análisis; el solista es siempre person_0."""

from __future__ import annotations

from vfxglow.analysis.cast import keep_performers
from vfxglow.analysis.schema import FrameRecord, Landmark, PersonPose


def _person(pid: str, x: float, height: float) -> PersonPose:
    box = (x - height / 4, 0.9 - height, x + height / 4, 0.9)
    return PersonPose(person_id=pid, pose=[Landmark(name="nose", x=x, y=0.9 - height * 0.9, c=0.9)], box=box)


def test_audience_is_dropped_and_the_dancer_keeps_one_identity() -> None:
    frames = []
    for i in range(40):
        dancer, audience = _person("person_0", 0.3 + i * 0.01, 0.6), _person("person_1", 0.8, 0.25)
        # El detector cruza las casillas a mitad del video.
        if i >= 20:
            dancer, audience = dancer.model_copy(update={"person_id": "person_1"}), audience.model_copy(update={"person_id": "person_0"})
        frames.append(FrameRecord(frame=i, time_s=i / 25, people=[dancer, audience]))
    # En un cuadro la pose no ve al bailarín: el público no toma su lugar.
    frames[30].people = [p for p in frames[30].people if p.box[3] - p.box[1] < 0.3]
    assert keep_performers(frames) == "solo"
    assert all(len(f.people) == 1 and f.people[0].person_id == "person_0" and f.people[0].box[3] - f.people[0].box[1] > 0.5 for f in frames if f.frame != 30)
    assert frames[30].people == [] and frames[10].pose == frames[10].people[0].pose


def test_two_dancers_stay_a_pair() -> None:
    frames = [FrameRecord(frame=i, time_s=i / 25, people=[_person("person_0", 0.3, 0.6), _person("person_1", 0.7, 0.55)]) for i in range(20)]
    assert keep_performers(frames) == "pareja"
    assert all([p.person_id for p in f.people] == ["person_0", "person_1"] for f in frames)
