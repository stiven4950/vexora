"""Objeto protagonista: estado según manos y cabeza, eventos de traspaso y su contorno en neón."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.props import _to_prop, assign_states, frame_state, prop_events
from vfxglow.analysis.schema import FrameRecord, Landmark, Prop
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine

W, H = 400, 800


def _lm(name: str, x: float, y: float) -> Landmark:
    return Landmark(name=name, x=x, y=y, c=0.95)


def _pose(left_wrist=(0.3, 0.5), right_wrist=(0.7, 0.5)) -> list[Landmark]:
    return [
        _lm("nose", 0.5, 0.2),
        _lm("left_ear", 0.46, 0.2),
        _lm("right_ear", 0.54, 0.2),
        _lm("left_shoulder", 0.4, 0.3),
        _lm("right_shoulder", 0.6, 0.3),
        _lm("left_hip", 0.42, 0.55),
        _lm("right_hip", 0.58, 0.55),
        _lm("left_wrist", *left_wrist),
        _lm("right_wrist", *right_wrist),
    ]


def _cap(cx: float, cy: float, r: float = 0.03) -> Prop:
    contour = [(cx + r * np.cos(t), cy + r * np.sin(t) * W / H) for t in np.linspace(0, 2 * np.pi, 24, endpoint=False)]
    return Prop(label="baseball cap", contour=contour, box=(cx - r, cy - r * W / H, cx + r, cy + r * W / H))


def _frame(i: int, cap: tuple[float, float]) -> FrameRecord:
    return FrameRecord(frame=i, time_s=i / 30, pose=_pose(), prop=_cap(*cap))


def test_state_follows_hands_and_head() -> None:
    assert frame_state(_frame(0, (0.3, 0.5)), W, H)[0] == "left"
    assert frame_state(_frame(0, (0.7, 0.5)), W, H)[0] == "right"
    assert frame_state(_frame(0, (0.5, 0.75)), W, H)[0] == "air"
    # Sobre la coronilla, sin manos cerca: puesta.
    assert frame_state(_frame(0, (0.5, 0.15)), W, H)[0] == "worn"
    near_head = FrameRecord(frame=0, time_s=0.0, pose=_pose(left_wrist=(0.47, 0.15)), prop=_cap(0.5, 0.15))
    assert frame_state(near_head, W, H)[0] == "fitting"


def test_transfer_and_worn_events() -> None:
    path = [(0.3, 0.5)] * 20 + [(0.5, 0.45)] * 6 + [(0.7, 0.5)] * 20 + [(0.5, 0.15)] * 15 + [(0.5, 0.75)] * 4 + [(0.5, 0.15)] * 15
    frames = [_frame(i, c) for i, c in enumerate(path)]
    assign_states(frames, W, H)
    events = prop_events(frames, 30.0)
    transfer = [e for e in events if e.name == "prop_transfer"]
    assert len(transfer) == 1 and transfer[0].kind == "left_to_right"
    assert transfer[0].start_frame == 19 and transfer[0].end_frame == 26
    # El salto corto fuera de la cabeza (pose que falla) no da un segundo prop_worn.
    worn = [e for e in events if e.name == "prop_worn"]
    assert len(worn) == 1 and worn[0].start_frame == 46
    assert {f.prop.state for f in frames[46:]} == {"worn"}


def test_state_filter_removes_flicker() -> None:
    path = [(0.3, 0.5)] * 5 + [(0.5, 0.75)] + [(0.3, 0.5)] * 5
    frames = [_frame(i, c) for i, c in enumerate(path)]
    assign_states(frames, W, H)
    assert {f.prop.state for f in frames} == {"left"}


def test_head_without_nose_uses_ears() -> None:
    pose = [lm for lm in _pose() if lm.name != "nose"]
    record = FrameRecord(frame=0, time_s=0.0, pose=pose, prop=_cap(0.5, 0.15))
    assert frame_state(record, W, H)[0] == "worn"


def test_mask_to_prop_keeps_largest_piece() -> None:
    mask = np.zeros((H, W), dtype=bool)
    mask[100:200, 100:220] = True
    mask[600:604, 10:14] = True  # ruido
    prop = _to_prop(mask, "cap", W, H, 40)
    assert prop is not None and len(prop.contour) <= 40
    assert prop.box[0] * W == 100 and round(prop.box[3] * H) == 200


def _render(prop: Prop, shapes: list[str]) -> np.ndarray:
    effect = Effect(id="cap", type="prop_outline", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=shapes, fill=0.0))
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[])
    track = FrameRecord(frame=0, time_s=0.0, pose=_pose(), prop=prop)
    layer = None
    for i in range(8):
        layer = engine.render_frame(track.model_copy(update={"frame": i}), i, W, H, 40)[0][2]
    return layer


def test_prop_outline_draws_around_the_object_and_skips_when_worn() -> None:
    prop = _cap(0.3, 0.5, 0.08)
    layer = _render(prop, ["outline"])
    ys, xs = np.nonzero(layer[..., 3] > 0.5)
    assert xs.size and abs(xs.mean() - 0.3 * W) < 6 and abs(ys.mean() - 0.5 * H) < 6
    # El centro del objeto queda sin pintar: es un contorno, no un relleno.
    assert layer[int(0.5 * H), int(0.3 * W), 3] < 0.2
    worn = prop.model_copy(update={"state": "worn"})
    assert _render(worn, ["outline"])[..., 3].max() == 0
    assert _render(worn, ["outline", "worn"])[..., 3].max() > 0.5
