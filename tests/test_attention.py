"""Línea de atención: protagonista por momento, reglas de objeto y transferencia, y el motor que
apaga lo que no está en foco."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.attention import attention_timeline, focus_at
from vfxglow.analysis.schema import AttentionSpan, FrameRecord, Landmark, MotionEvent, Prop
from vfxglow.config import EngineConfig
from vfxglow.director.choreography import attention_spotlights
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine
from vfxglow.engine.focus import effect_regions

W, H, FPS = 400, 800, 30.0


def _pose(i: int, moving: str) -> list[Landmark]:
    """Persona quieta salvo la parte `moving`, que oscila."""
    wobble = 0.04 * np.sin(i * 0.9)
    pts = {
        "nose": (0.5, 0.2), "left_ear": (0.47, 0.2), "right_ear": (0.53, 0.2),
        "left_shoulder": (0.42, 0.3), "right_shoulder": (0.58, 0.3), "left_hip": (0.44, 0.55), "right_hip": (0.56, 0.55),
        "left_elbow": (0.36, 0.4), "right_elbow": (0.64, 0.4), "left_wrist": (0.34, 0.5), "right_wrist": (0.66, 0.5),
        "left_knee": (0.45, 0.7), "right_knee": (0.55, 0.7), "left_ankle": (0.45, 0.9), "right_ankle": (0.55, 0.9),
    }
    joints = {"right_arm": ("right_elbow", "right_wrist"), "legs": ("left_knee", "right_knee", "left_ankle", "right_ankle")}[moving]
    lms = []
    for name, (x, y) in pts.items():
        # Un poco de movimiento de fondo en todo para que lo "habitual" no sea cero.
        jitter = 0.002 * np.sin(i * 1.7 + len(name))
        lms.append(Landmark(name=name, x=x + (wobble if name in joints else jitter), y=y, c=0.95))
    return lms


def _frames(moving_by_frame) -> list[FrameRecord]:
    return [FrameRecord(frame=i, time_s=i / FPS, pose=_pose(i, moving_by_frame(i))) for i in range(150)]


def test_protagonist_follows_the_part_that_moves_more_than_usual() -> None:
    frames = _frames(lambda i: "right_arm" if i < 75 else "legs")
    spans = attention_timeline(frames, [], FPS, W, H)
    assert "right_arm" in focus_at(spans, 30)
    assert "legs" in focus_at(spans, 120)


def test_prop_in_hand_wins_over_the_arm_that_holds_it() -> None:
    frames = _frames(lambda i: "right_arm")
    cap = Prop(label="cap", contour=[(0.6, 0.5), (0.7, 0.5), (0.7, 0.55), (0.6, 0.55)], box=(0.6, 0.5, 0.7, 0.55), state="right")
    for record in frames:
        record.prop = cap
    spans = attention_timeline(frames, [], FPS, W, H)
    assert focus_at(spans, 75) == {"prop"} or "prop" in focus_at(spans, 75)
    assert "right_arm" not in focus_at(spans, 75)


def test_energy_passes_from_the_face_to_the_hand_that_touched_it() -> None:
    frames = _frames(lambda i: "legs")
    touch = MotionEvent(name="face_touch", target="person_0:face", start_frame=20, end_frame=60, confidence=1.0, kind="right")
    spans = attention_timeline(frames, [touch], FPS, W, H)
    assert "head" in focus_at(spans, 40)
    assert "right_arm" in focus_at(spans, 85)


def test_spotlights_from_attention_are_chunked_and_skip_the_prop() -> None:
    spans = [AttentionSpan(person="person_0", start_frame=0, end_frame=89, primary="legs", secondary="right_arm"), AttentionSpan(person="person_0", start_frame=90, end_frame=150, primary="prop")]
    events = attention_spotlights(spans, FPS)
    assert {e.kind for e in events} == {"legs", "right_arm"}
    assert len([e for e in events if e.kind == "legs"]) == 2  # 3 s en trozos de ~1,2 s


def test_engine_fades_out_effects_outside_the_focus() -> None:
    effect = Effect(id="legs", type="body_glow", target=EffectTarget(kind="joint", id="legs"), style=EffectStyle(fill=0.0))
    assert effect_regions(effect, None) == {"legs"}
    spans = [AttentionSpan(person="person_0", start_frame=0, end_frame=19, primary="legs"), AttentionSpan(person="person_0", start_frame=20, end_frame=59, primary="head")]
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect], attention=spans), EngineConfig(), events=[])
    frames = _frames(lambda i: "legs")
    alpha = [engine.render_frame(frames[i], i, W, H, 60)[0][2][..., 3].max() for i in range(40)]
    assert alpha[15] > 0.5 and alpha[35] == 0.0
