"""Anillos en los ojos, delineado progresivo, dibujos del director y plan de arte."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.names import FACE_FEATURES
from vfxglow.analysis.schema import Beat, MotionBrief, VideoMeta
from vfxglow.config import DirectorConfig
from vfxglow.director.director import CreativeDirector
from vfxglow.director.schema import Drawing
from vfxglow.director.strategies import _expand_one
from vfxglow.director.validator import ScriptError, validate_script
from vfxglow.engine.anchors import add_face_points
from vfxglow.engine.effects import EffectRuntime, render_effect

ROOT = Path(__file__).resolve().parents[1]
H, W = 240, 200


def _face(dx: float = 0.0, open_eyes: bool = True) -> dict[str, np.ndarray]:
    """Cara sintética: ojos en y=100, separados 60 px."""
    pts: dict[str, np.ndarray] = {}
    lid = 6.0 if open_eyes else 0.4
    for side, cx, corners, lids, iris in (
        ("right", 70.0, (33, 133), (159, 145), (468, 469, 470, 471, 472)),
        ("left", 130.0, (362, 263), (386, 374), (473, 474, 475, 476, 477)),
    ):
        c = np.array([cx + dx, 100.0])
        pts[f"face_{corners[0]}"] = c + [-14, 0]
        pts[f"face_{corners[1]}"] = c + [14, 0]
        pts[f"face_{lids[0]}"] = c + [0, -lid]
        pts[f"face_{lids[1]}"] = c + [0, lid]
        pts[f"face_{iris[0]}"] = c
        for k, offset in enumerate(([4, 0], [0, -4], [-4, 0], [0, 4])):
            pts[f"face_{iris[k + 1]}"] = c + offset
        chain = FACE_FEATURES[f"{side}_eye"][:-1]
        for k, index in enumerate(chain):
            a = 2 * np.pi * k / len(chain)
            pts.setdefault(f"face_{index}", c + [np.cos(a) * 14, np.sin(a) * lid])
    add_face_points(pts)
    return pts


def _render(effect, points, frame=0, active=1000):
    runtime = EffectRuntime(effect, 1, 8)
    runtime.active_frames = active
    return render_effect(runtime, None, points, frame, W, H, 1.0, None, 100)


def test_eye_rings_follow_iris_and_close_with_the_lid() -> None:
    effect = _expand_one("eye_rings", "star")[0]
    layer = _render(effect, _face())
    energy = layer[..., :3].sum(axis=2)
    assert energy[80:120, 50:90].sum() > 0 and energy[80:120, 110:150].sum() > 0
    assert energy[:, :40].sum() == 0
    closed = _render(effect, _face(open_eyes=False))
    assert closed[..., :3].sum() < layer[..., :3].sum() * 0.05


def test_eye_rings_change_color_over_time() -> None:
    effect = _expand_one("eye_rings", "star")[0]
    effect.style.rings = 1
    a = _render(effect, _face(), frame=0)[..., :3].sum(axis=(0, 1))
    b = _render(effect, _face(), frame=40)[..., :3].sum(axis=(0, 1))
    assert not np.allclose(a / a.sum(), b / b.sum(), atol=0.02)


def test_linework_draws_progressively() -> None:
    effect = _expand_one("face_linework", "star")[0]
    effect.target.id = "eyes"
    early = _render(effect, _face(), active=5)[..., 3].sum()
    full = _render(effect, _face(), active=1000)[..., 3].sum()
    assert 0 < early < full * 0.6


def test_drawing_moves_with_the_face() -> None:
    effect = _expand_one("face_linework", "star")[0]
    effect.type = "drawing"
    effect.style.draw_on = 0
    effect.style.drawing = Drawing(space="face", strokes=["M -0.6 -0.9 L -0.9 -1.6 L -0.3 -1.0", "M 0.6 -0.9 L 0.9 -1.6 L 0.3 -1.0"])
    xs = []
    for dx in (0.0, 30.0):
        alpha = _render(effect, _face(dx=dx))[..., 3]
        ys, cols = np.nonzero(alpha > 0.05)
        assert ys.max() < 100  # por encima de los ojos: cuernos
        xs.append(cols.mean())
    assert xs[1] - xs[0] == pytest.approx(30.0, abs=3.0)


def test_validator_rejects_bad_drawing() -> None:
    from vfxglow.director.schema import EffectScript

    effect = _expand_one("face_linework", "star")[0]
    effect.type = "drawing"
    effect.style.drawing = Drawing(strokes=["M 0 0 L 9 9"])
    with pytest.raises(ScriptError, match="fuera"):
        validate_script(EffectScript(title="t", theme="t", effects=[effect]))
    effect.target.id = "all"
    effect.type = "face_linework"
    effect.style.drawing = None
    validate_script(EffectScript(title="t", theme="t", effects=[effect]), cuts=[5])


def _brief() -> MotionBrief:
    return MotionBrief(
        video=VideoMeta(path="v.mp4", fps=30, width=W, height=H, frame_count=90, duration_s=3),
        person_id="person_0",
        anchors=["right_iris", "left_iris", "face_center"],
        limbs=[],
        events=[],
        summary="",
        beats=[
            Beat(id=0, start_frame=0, end_frame=29, kind="gesture"),
            Beat(id=1, start_frame=30, end_frame=59, kind="gesture"),
            Beat(id=2, start_frame=60, end_frame=89, kind="cut"),
        ],
    )


def test_artist_plan_merges_beats_and_keeps_drawings(tmp_path: Path) -> None:
    plan = """{"title":"Calabaza","theme":"halloween","palette":[[255,140,20],[0.4,0.9,1]],
    "beats":[{"beat":0,"use":["face_linework"],"color":0},{"beat":1,"use":["face_linework","eye_rings"],"drawing":"horns","color":0},
             {"beat":2,"use":["eye_rings"],"color":1}],
    "drawings":{"horns":{"space":"face","strokes":["M -0.6 -0.9 L -0.9 -1.6 L -0.3 -1.0"],"draw_on":10}}}"""
    calls = []

    def complete(prompt: str) -> str:
        calls.append(prompt)
        return plan

    config = DirectorConfig(provider="openai")
    director = CreativeDirector(config, ROOT / "configs" / "presets", complete=complete, cache_dir=tmp_path)
    script = director.create(_brief())
    by_type = {}
    for effect in script.effects:
        by_type.setdefault(effect.type, []).append(effect)
    lines = by_type["face_linework"]
    assert len(lines) == 1 and (lines[0].time.start_frame, lines[0].time.end_frame) == (0, 59)
    assert lines[0].style.colors[0] == pytest.approx((1.0, 140 / 255, 20 / 255))
    assert len(by_type["eye_rings"]) == 2
    assert by_type["drawing"][0].time.start_frame == 30
    assert "0|0-29|gesture" in calls[0] and "Brief JSON" not in calls[0]
    CreativeDirector(config, ROOT / "configs" / "presets", complete=complete, cache_dir=tmp_path).create(_brief())
    assert len(calls) == 1
