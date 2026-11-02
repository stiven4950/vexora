"""Señales de la cara comunes a los efectos (engine/face_signals.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vfxglow.engine.face_signals import signals


def _runtime(fps: float = 30.0) -> SimpleNamespace:
    return SimpleNamespace(swoosh={}, fps=fps, expressions={}, head_pose=(0.0, 0.0, 0.0), voice=0.0, energy=0.0)


def _run(runtime, frames: list[dict], pose=None) -> list:
    out = []
    for index, expressions in enumerate(frames):
        runtime.expressions = expressions
        if pose is not None:
            runtime.head_pose = pose[index]
        out.append(signals(runtime, index))
    return out


OPEN = {"eyeBlinkLeft": 0.05, "eyeBlinkRight": 0.05}
SHUT = {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}


def test_a_blink_starts_once_and_the_eyes_open_once_even_slowly() -> None:
    half = {"eyeBlinkLeft": 0.45, "eyeBlinkRight": 0.45}
    out = _run(_runtime(), [OPEN, OPEN, SHUT, SHUT, half, OPEN, OPEN])
    assert [s.blink_start for s in out] == [False, False, True, False, False, False, False]
    assert [s.eyes_opened for s in out] == [False, False, False, False, False, True, False]


def test_a_wink_says_which_eye_closed() -> None:
    wink = {"eyeBlinkLeft": 0.8, "eyeBlinkRight": 0.1}
    out = _run(_runtime(), [OPEN, wink, wink, OPEN])
    assert [s.wink for s in out] == [None, "left", None, None]
    assert not any(s.blink_start for s in out)


def test_opening_the_mouth_is_an_edge() -> None:
    out = _run(_runtime(), [{}, {"jawOpen": 0.6}, {"jawOpen": 0.7}, {}, {"jawOpen": 0.6}])
    assert [s.jaw_open_start for s in out] == [False, True, False, False, True]


def test_the_stare_grows_while_still_and_a_blink_breaks_it() -> None:
    frames = [OPEN] * 40 + [SHUT] + [OPEN] * 3
    out = _run(_runtime(), frames)
    assert out[5].stare == 0.0
    assert out[39].stare == pytest.approx(1.0)
    assert out[41].stare == 0.0


def test_turning_the_head_breaks_the_stare_and_gives_its_speed() -> None:
    pose = [(float(k * 2), 0.0, 0.0) for k in range(30)]
    out = _run(_runtime(), [OPEN] * 30, pose)
    assert all(s.stare == 0.0 for s in out)
    assert out[-1].yaw_rate == pytest.approx(60.0, rel=0.05)


def test_a_calm_face_relaxes_and_a_smile_wakes_it() -> None:
    out = _run(_runtime(), [OPEN] * 70 + [{"mouthSmileLeft": 0.9, "mouthSmileRight": 0.9}] * 10)
    assert out[20].relaxed == 0.0
    assert out[69].relaxed > 0.9
    assert out[-1].relaxed == 0.0


@pytest.mark.parametrize("fps", [15.0, 30.0])
def test_the_stare_takes_the_same_time_at_any_frame_rate(fps: float) -> None:
    seconds = 0.6
    out = _run(_runtime(fps), [OPEN] * int(seconds * fps + 1))
    assert out[-1].stare == pytest.approx((seconds - 0.3) / 0.6, abs=0.12)


def test_the_signals_are_computed_once_per_frame() -> None:
    runtime = _runtime()
    runtime.expressions = SHUT
    first = signals(runtime, 0)
    assert signals(runtime, 0) is first
