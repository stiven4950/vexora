"""Mano en la cara (face_touch), cara de caricatura con jalón, garabatos sobre la gorra y
triggers anclados al final del evento."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import FrameRecord, HandFrame, Landmark, MotionEvent, Prop
from vfxglow.analysis.touch import face_touch_events
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget, EffectTrigger
from vfxglow.engine.engine import EffectEngine
from vfxglow.engine.timeline import ActivationTimeline

W, H = 400, 800


def _lm(name: str, x: float, y: float) -> Landmark:
    return Landmark(name=name, x=x, y=y, c=0.95)


def _pose() -> list[Landmark]:
    return [
        _lm("nose", 0.5, 0.2),
        _lm("left_eye", 0.47, 0.19),
        _lm("right_eye", 0.53, 0.19),
        _lm("mouth_left", 0.48, 0.22),
        _lm("mouth_right", 0.52, 0.22),
        _lm("left_ear", 0.42, 0.2),
        _lm("right_ear", 0.58, 0.2),
        _lm("left_shoulder", 0.4, 0.3),
        _lm("right_shoulder", 0.6, 0.3),
        _lm("left_hip", 0.42, 0.55),
        _lm("right_hip", 0.58, 0.55),
        _lm("left_wrist", 0.3, 0.5),
        _lm("right_wrist", 0.7, 0.5),
    ]


def _hand(x: float, y: float) -> HandFrame:
    return HandFrame(landmarks=[_lm("right_index_tip", x, y), _lm("right_wrist", x + 0.05, y + 0.05)], score=1.0)


def _frame(i: int, hand: tuple[float, float], prop: Prop | None = None) -> FrameRecord:
    return FrameRecord(frame=i, time_s=i / 30, pose=_pose(), right_hand=_hand(*hand), prop=prop)


def test_face_touch_needs_fingers_on_the_face_for_a_while() -> None:
    frames = [_frame(i, (0.53, 0.21) if 5 <= i < 20 else (0.8, 0.6)) for i in range(30)]
    events = face_touch_events(frames, 30.0, W, H)
    assert len(events) == 1 and events[0].kind == "right"
    assert (events[0].start_frame, events[0].end_frame) == (5, 19)
    brief = [_frame(i, (0.53, 0.21) if 5 <= i < 8 else (0.8, 0.6)) for i in range(30)]
    assert face_touch_events(brief, 30.0, W, H) == []


def test_hand_holding_the_prop_is_not_a_face_touch() -> None:
    cap = Prop(label="cap", contour=[(0.5, 0.2), (0.55, 0.2), (0.55, 0.23), (0.5, 0.23)], box=(0.5, 0.2, 0.55, 0.23), state="right")
    frames = [_frame(i, (0.53, 0.21), cap) for i in range(20)]
    assert face_touch_events(frames, 30.0, W, H) == []


def _render(effect: Effect, frames: list[FrameRecord], events: list[MotionEvent]) -> list[np.ndarray]:
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=events)
    return [engine.render_frame(f, f.frame, W, H, 60)[0][2] for f in frames]


def test_kiss_then_lips_travel_to_the_hand() -> None:
    effect = Effect(id="kiss", type="face_toon", target=EffectTarget(kind="joint", id="face"), style=EffectStyle(shapes=["kiss"]), triggers=[{"event": "face_touch", "hold": 12, "fade_in": 0, "fade_out": 0}])
    event = MotionEvent(name="face_touch", target="person_0:face", start_frame=0, end_frame=5, confidence=1.0, kind="right")
    frames = [_frame(i, (0.53, 0.21) if i <= 5 else (0.85, 0.15)) for i in range(16)]
    layers = _render(effect, frames, [event])
    touching = np.nonzero(layers[3][..., 3] > 0.5)
    assert touching[1].size and abs(touching[1].mean() - 0.5 * W) < 0.06 * W  # en la cara
    pulled = np.nonzero(layers[15][..., 3] > 0.5)
    assert pulled[1].max() > 0.75 * W  # los labios llegaron hacia la mano (x=0,85)


def test_doodle_draws_on_the_upper_end_of_the_prop() -> None:
    contour = [(0.5 + 0.08 * np.cos(t), 0.5 + 0.04 * np.sin(t) * W / H) for t in np.linspace(0, 2 * np.pi, 30, endpoint=False)]
    prop = Prop(label="cap", contour=contour, box=(0.42, 0.48, 0.58, 0.52), state="both")
    effect = Effect(id="d", type="prop_doodle", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["horn"]))
    layer = _render(effect, [_frame(i, (0.8, 0.6), prop) for i in range(8)], [])[-1]
    ys, _ = np.nonzero(layer[..., 3] > 0.5)
    assert ys.size and ys.min() < 0.5 * H - 0.04 * W  # la punta sale por encima de la gorra


def test_trigger_anchored_at_the_end_of_the_event() -> None:
    effect = Effect(id="e", type="prop_doodle", target=EffectTarget(kind="joint", id="body"), triggers=[EffectTrigger(event="prop_spin", anchor="end", hold=10, fade_in=0, fade_out=0)])
    timeline = ActivationTimeline(effect, [MotionEvent(name="prop_spin", target="p:prop", start_frame=10, end_frame=40, confidence=1.0)])
    assert timeline.at(30)[0] == 0.0 and timeline.at(45)[0] == 1.0 and timeline.at(52)[0] == 0.0


def test_expressions_draw_and_surprise_wins_with_open_mouth() -> None:
    from vfxglow.engine.face_toon import EMOTES, _pick_emote
    from vfxglow.director.schema import EffectStyle

    for shape in EMOTES:
        effect = Effect(id=shape, type="face_toon", target=EffectTarget(kind="joint", id="face"), style=EffectStyle(shapes=[shape]))
        layer = _render(effect, [_frame(i, (0.8, 0.6)) for i in range(8)], [])[-1]
        assert layer[..., 3].max() > 0.3, shape
    style = EffectStyle(shapes=list(EMOTES))
    open_mouth = {"face_13": np.array([200.0, 170.0]), "face_14": np.array([200.0, 190.0])}
    assert _pick_emote(list(EMOTES), open_mouth, 50.0, None, style, 0) == "exclaim"


def test_masks_draw_and_a_hand_on_top_takes_over() -> None:
    from vfxglow.engine.face_toon import MASKS, FINGERS

    def open_hand(x: float, y: float) -> HandFrame:
        marks = [_lm("right_wrist", x, y + 0.06)]
        for k, finger in enumerate(FINGERS):
            joints = ("cmc", "mcp", "ip", "tip") if finger == "thumb" else ("mcp", "pip", "dip", "tip")
            for j, joint in enumerate(joints):
                marks.append(_lm(f"right_{finger}_{joint}", x + (k - 2) * 0.012 * (1 + j * 0.3), y + 0.03 - j * 0.015))
        return HandFrame(landmarks=marks, score=1.0)

    for shape in MASKS:
        effect = Effect(id=shape, type="face_toon", target=EffectTarget(kind="joint", id="face"), style=EffectStyle(shapes=[shape]))
        bare = _render(effect, [FrameRecord(frame=i, time_s=i / 30, pose=_pose()) for i in range(8)], [])[-1]
        assert bare[int(0.19 * H), int(0.47 * W), 3] > 0.3, shape  # el ojo de la máscara
        covered = _render(effect, [FrameRecord(frame=i, time_s=i / 30, pose=_pose(), right_hand=open_hand(0.5, 0.2)) for i in range(8)], [])[-1]
        # La mano tapa la cara: la máscara se apaga (el costado del óvalo de la cara ya no está) y
        # se dibuja la mano.
        side = (168, 165)
        assert covered[side][3] < 0.5 * bare[side][3], shape
        assert covered[..., 3].max() > 0.3, shape
