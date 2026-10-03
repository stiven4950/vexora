"""Detector de eventos, timeline y filtro de glitches del tracker."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.events import EventDetector
from vfxglow.analysis.kinematics import add_motion
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent, VideoMeta
from vfxglow.analysis.smoothing import reject_jumps
from vfxglow.config import EventsConfig
from vfxglow.director.schema import Effect, EffectTarget, EffectTime, EffectTrigger
from vfxglow.engine.timeline import ActivationTimeline


def _lm(name: str, x: float, y: float, c: float = 0.95) -> Landmark:
    return Landmark(name=name, x=x, y=y, z=0.0, c=c)


def _body(i: int, n: int, wrist_x: float, wrist_y: float) -> FrameRecord:
    t = i / max(n - 1, 1)
    cx = 0.4 + 0.02 * t
    return FrameRecord(
        frame=i,
        time_s=i / 30,
        pose=[
            _lm("nose", cx, 0.22),
            _lm("left_shoulder", cx - 0.1, 0.36),
            _lm("right_shoulder", cx + 0.1, 0.36),
            _lm("left_elbow", cx - 0.14, 0.5),
            _lm("right_elbow", cx + 0.14, 0.5),
            _lm("left_wrist", cx - 0.16, 0.62),
            _lm("right_wrist", wrist_x, wrist_y),
            _lm("left_hip", cx - 0.08, 0.6),
            _lm("right_hip", cx + 0.08, 0.6),
            _lm("left_knee", cx - 0.08, 0.76),
            _lm("right_knee", cx + 0.08, 0.76),
            _lm("left_ankle", cx - 0.08, 0.9),
            _lm("right_ankle", cx + 0.08, 0.9),
        ],
    )


def test_reject_jumps_invalidates_tracker_teleport() -> None:
    values = np.array([0.2, 0.21, 0.9, 0.91, 0.22])
    valid = np.ones(5, dtype=bool)
    out = reject_jumps(values, valid, max_jump=0.18, max_gap=2)
    assert not out[2]


def test_glitch_spike_does_not_create_swing() -> None:
    n = 12
    frames = []
    for i in range(n):
        x, y = 0.55, 0.5
        if i == 6:
            x, y = 0.95, 0.05
        frames.append(_body(i, n, x, y))
    meta = VideoMeta(path="x.mp4", fps=30, width=200, height=200, frame_count=n, duration_s=n / 30)
    add_motion(frames, meta, glitch_speed=2.5)
    assert any(item.glitch for item in frames[6].motion if item.name == "right_wrist")
    events = EventDetector(EventsConfig()).detect(frames, meta)
    assert not any(event.name == "fast_swing" and event.start_frame <= 6 <= event.end_frame for event in events)


def test_fast_swing_and_impact_from_real_motion() -> None:
    n = 16
    frames = []
    for i in range(n):
        if i < 4:
            x, y = 0.55, 0.55
        elif i < 10:
            x = 0.55 + 0.05 * (i - 3)
            y = 0.55 - 0.04 * (i - 3)
        else:
            x, y = 0.80, 0.31
        frames.append(_body(i, n, x, y))
    meta = VideoMeta(path="x.mp4", fps=30, width=200, height=200, frame_count=n, duration_s=n / 30)
    add_motion(frames, meta, glitch_speed=2.5)
    events = EventDetector(EventsConfig(swing_speed=0.08, swing_frames=3, impact_decel=0.05)).detect(frames, meta)
    names = {event.name for event in events}
    assert "fast_swing" in names
    assert any(event.target == "right_wrist" for event in events if event.name == "fast_swing")


def test_timeline_fades_and_hold() -> None:
    effect = Effect(
        id="bolt",
        type="lightning",
        target=EffectTarget(kind="joint", id="right_wrist"),
        time=EffectTime(start_frame=0, end_frame=0),
        triggers=[
            EffectTrigger(event="fast_swing", joint="right_wrist", hold=4, cooldown=2, fade_in=2, fade_out=2)
        ],
    )
    events = [
        MotionEvent(name="fast_swing", target="right_wrist", start_frame=10, end_frame=12, confidence=0.8, peak_speed=0.4)
    ]
    timeline = ActivationTimeline(effect, events)
    assert timeline.at(9)[0] == 0.0
    assert 0.0 < timeline.at(11)[0] < 1.0
    assert timeline.at(13)[0] == 1.0
    assert timeline.at(14)[0] == 1.0
    assert timeline.at(15)[0] < 1.0
    assert timeline.at(16)[0] == 0.0
    assert timeline.at(12)[1] is events[0]


def test_strike_phases_anticipate_contact_and_find_recoil() -> None:
    from vfxglow.analysis.events import WINDUP_LEAD
    from vfxglow.analysis.schema import JointMotion, PersonPose

    def frame(i: int, vx: float) -> FrameRecord:
        wrist = JointMotion(name="left_wrist", speed=abs(vx), direction_deg=0.0, vx=vx, vy=0.0)
        return FrameRecord(frame=i, time_s=i / 30, people=[PersonPose(person_id="person_1", motion=[wrist])])

    frames = [frame(i, 0.5 if i <= 12 else -0.2) for i in range(20)]
    contact = MotionEvent(
        name="person_contact",
        target="person_1:left_wrist",
        start_frame=10,
        end_frame=11,
        confidence=0.8,
        peak_speed=0.5,
        attacker="person_1",
        receiver="person_0",
    )
    detector = EventDetector(EventsConfig())
    detector.frames = frames
    phases = {event.name: event for event in detector._strike_phases([contact])}
    windup, recoil = phases["strike_windup"], phases["strike_recoil"]
    assert (windup.start_frame, windup.end_frame) == (10 - WINDUP_LEAD, 9)
    assert windup.attacker == "person_1" and windup.target == "person_1:left_wrist"
    assert (recoil.start_frame, recoil.end_frame) == (12, 13)
