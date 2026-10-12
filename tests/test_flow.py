"""La energía que recorre el cuerpo: onda de contornos, aros por la extremidad, líneas que
aparecen desde la mano y activaciones seguidas que se alargan."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectTarget, EffectTrigger
from vfxglow.engine.bodyglow import Body, reveal, wave_pieces
from vfxglow.engine.timeline import ActivationTimeline


def _leg_contour() -> np.ndarray:
    ys = np.linspace(400, 800, 60)
    return np.vstack([np.stack([np.full(60, 180.0), ys], axis=1), np.stack([np.full(60, 220.0), ys[::-1]], axis=1)])


def test_wave_draws_only_bands_that_travel_up() -> None:
    contour = _leg_contour()
    early = wave_pieces(contour, frame=1, period=20)
    later = wave_pieces(contour, frame=5, period=20)
    assert early and sum(len(p) for p in early) < len(contour) * 0.5  # trazos parciales
    lowest = lambda pieces: max(float(p[:, 1].mean()) for p in pieces)
    assert lowest(later) < lowest(early)  # las bandas subieron


def test_lines_appear_from_the_hand_that_brings_the_energy() -> None:
    body = Body({"right_wrist": np.array([300.0, 300.0]), "left_wrist": np.array([100.0, 300.0])}, None)
    lines = [np.array([[110.0, 300.0], [130.0, 300.0]]), np.array([[280.0, 300.0], [290.0, 300.0]])]
    event = MotionEvent(name="spotlight", target="person_0", start_frame=0, end_frame=10, confidence=1.0, kind="right_arm")
    first = reveal(lines, body, event, frames_on=2)
    assert len(first) == 1 and first[0][0, 0] == 280.0
    assert len(reveal(lines, body, event, frames_on=20)) == 2


def test_contiguous_events_extend_the_activation() -> None:
    effect = Effect(id="e", type="body_glow", target=EffectTarget(kind="joint", id="legs"), triggers=[EffectTrigger(event="spotlight", hold=4, fade_in=0, fade_out=0)])
    events = [MotionEvent(name="spotlight", target="p", start_frame=s, end_frame=s + 36, confidence=1.0, kind="legs") for s in (0, 37)]
    timeline = ActivationTimeline(effect, events)
    assert len(timeline.windows) == 1 and timeline.at(60)[0] == 1.0
