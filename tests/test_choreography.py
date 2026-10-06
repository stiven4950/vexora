"""Coreógrafo: sorteo determinista de reacciones por ocurrencia."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from vfxglow.analysis.schema import MotionBrief, MotionEvent, VideoMeta
from vfxglow.director.choreography import Catalog, choreograph, load_catalog
from vfxglow.director.schema import Effect, EffectTarget, EffectTrigger
from vfxglow.director.validator import validate_script
from vfxglow.engine.timeline import ActivationTimeline

ROOT = Path(__file__).resolve().parents[1]


def _brief(events: list[MotionEvent]) -> MotionBrief:
    meta = VideoMeta(path="x", fps=30.0, width=100, height=100, frame_count=900, duration_s=30.0)
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="")


def _swing(frame: int, target: str = "person_1:right_wrist") -> MotionEvent:
    return MotionEvent(name="fast_swing", target=target, start_frame=frame, end_frame=frame + 2, confidence=1.0)


def _catalog(**option_extra) -> Catalog:
    return Catalog.model_validate(
        {
            "name": "t",
            "seed": 3,
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {
                    "action": "fast_swing",
                    "options": [
                        {"name": "swoosh", "weight": 1.0, "effects": [{"trigger": {"hold": 4}}], **option_extra},
                        {"name": "nada", "weight": 1.0},
                    ],
                }
            ],
        }
    )


def test_same_seed_same_choreography_other_seed_differs() -> None:
    brief = _brief([_swing(f) for f in range(0, 800, 20)])
    catalog = _catalog()
    first = choreograph(catalog, brief)[1].decisions
    again = choreograph(catalog, brief)[1].decisions
    other = choreograph(catalog, brief, seed=99)[1].decisions
    assert [d.choice for d in first] == [d.choice for d in again]
    assert [d.choice for d in first] != [d.choice for d in other]
    assert set(Counter(d.choice for d in first)) == {"swoosh", "nada"}


def test_chosen_frames_reach_the_trigger_and_only_they_fire() -> None:
    events = [_swing(f) for f in range(0, 400, 20)]
    script, log = choreograph(_catalog(), _brief(events))
    chosen = [d.frame for d in log.decisions if d.choice == "swoosh"]
    trigger = script.effects[0].triggers[0]
    assert trigger.frames == chosen and trigger.hold == 4
    windows = ActivationTimeline(script.effects[0], events).windows
    assert [w.start for w in windows] == chosen


def test_limbs_and_cooldown_restrict_the_draw() -> None:
    kicks = [_swing(f, "person_1:left_ankle") for f in range(0, 200, 20)]
    _, log = choreograph(_catalog(limbs=["right_wrist"]), _brief(kicks))
    assert {d.choice for d in log.decisions} == {"nada"}
    _, log = choreograph(_catalog(cooldown=100), _brief([_swing(f) for f in range(0, 400, 10)]))
    used = [d.frame for d in log.decisions if d.choice == "swoosh"]
    assert all(b - a >= 100 for a, b in zip(used, used[1:]))


def test_trigger_frames_filter_events() -> None:
    effect = Effect(id="e", type="stars", target=EffectTarget(kind="event_point", id="contact"),
                    triggers=[EffectTrigger(event="fast_swing", frames=[40])])
    windows = ActivationTimeline(effect, [_swing(20), _swing(40), _swing(60)]).windows
    assert [w.start for w in windows] == [40]


def test_fight_catalog_is_valid() -> None:
    catalog = load_catalog(ROOT / "configs" / "catalogs" / "pelea.yaml")
    events = [_swing(f) for f in range(0, 600, 15)] + [
        MotionEvent(name="person_contact", target="person_1:left_wrist", start_frame=100, end_frame=100, confidence=1.0, position=(0.5, 0.5)),
        MotionEvent(name="fist_clash", target="person_0:right_wrist", start_frame=200, end_frame=200, confidence=1.0, position=(0.5, 0.5)),
        MotionEvent(name="body_bump", target="body", start_frame=30, end_frame=30, confidence=1.0, position=(0.5, 0.5)),
    ]
    script, _ = choreograph(catalog, _brief(events))
    validate_script(script)
