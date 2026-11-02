"""Rostros de terror en neón: de la cuadrícula de referencia a la máscara viva sobre la cara."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.horror_masks import HORROR_MASKS, _warp, load_mask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def test_the_grid_cell_gives_eyes_nose_mouth_and_lines() -> None:
    from mask_from_grid import extract

    mask = extract(1)
    roles = {s["role"] for s in mask["strokes"]}
    assert {"eye_right", "eye_left", "nose", "mouth", "line"} <= roles
    assert mask["anchors"]["eye_right"][0] == pytest.approx(-0.5, abs=0.01)
    assert mask["anchors"]["eye_left"][0] == pytest.approx(0.5, abs=0.01)
    assert mask["anchors"]["mouth"][1] > mask["anchors"]["nose"][1] > 0  # la boca debajo de la nariz


def test_the_mouth_screams_and_the_eyes_blink() -> None:
    mask = load_mask("ghostface")
    mouth = next(s for s in mask["strokes"] if s["role"] == "mouth")["points"]
    closed = _warp(mouth, "mouth", mask["anchors"], {"jawOpen": 0.0})
    open_ = _warp(mouth, "mouth", mask["anchors"], {"jawOpen": 1.0})
    assert np.ptp(open_[:, 1]) > np.ptp(closed[:, 1]) * 1.5
    eye = next(s for s in mask["strokes"] if s["role"] == "eye_left")["points"]
    shut = _warp(eye, "eye_left", mask["anchors"], {"eyeBlinkLeft": 1.0})
    assert np.ptp(shut[:, 1]) < np.ptp(eye[:, 1]) * 0.3


@pytest.mark.parametrize("shape", HORROR_MASKS)
def test_every_mask_draws_on_the_face(shape: str) -> None:
    points = {"nose": np.array([200.0, 130.0]), "right_iris": np.array([180.0, 110.0]), "left_iris": np.array([220.0, 110.0]),
              "left_shoulder": np.array([250.0, 200.0]), "right_shoulder": np.array([150.0, 200.0]),
              "left_hip": np.array([240.0, 330.0]), "right_hip": np.array([160.0, 330.0])}
    body = Body(points, None)
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "x", "hold": 10}])
    event = MotionEvent(name="x", target="person_0", start_frame=0, end_frame=39, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    sizes = []
    for f in (1, 30):  # al aparecer solo partículas y algún trazo; armada, todos
        runtime.active_frames = f
        layer = np.zeros((400, 400, 4), np.float32)
        items = adornment(shape, body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        sizes.append(len(items))
        assert layer[..., 3].max() > 0 or items
    assert sizes[1] > sizes[0]
    centers = np.vstack([c for c, _ in items])
    assert abs(float(np.median(centers[:, 0])) - 200.0) < 40  # sobre la cara


def test_nothing_else_goes_on_the_face_while_a_special_face_is_on() -> None:
    from vfxglow.analysis.schema import FrameRecord, Landmark, PersonPose
    from vfxglow.config import EngineConfig
    from vfxglow.director.schema import EffectScript
    from vfxglow.engine.engine import EffectEngine

    def effect(eid: str, shape: str, event: str) -> Effect:
        return Effect(id=eid, type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape], focus=False),
                      triggers=[{"event": event, "hold": 30, "fade_in": 0, "fade_out": 0}])

    pose = [Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in {"nose": (0.5, 0.33), "left_eye": (0.53, 0.31), "right_eye": (0.47, 0.31),
            "left_shoulder": (0.6, 0.45), "right_shoulder": (0.4, 0.45), "left_hip": (0.58, 0.8), "right_hip": (0.42, 0.8)}.items()]
    events = [MotionEvent(name="smile", target="person_0", start_frame=0, end_frame=40, confidence=1.0),
              MotionEvent(name="still", target="person_0", start_frame=10, end_frame=40, confidence=1.0)]
    script = EffectScript(title="t", theme="t", effects=[effect("sonrisa", "cheek_glow", "smile"), effect("mascara", "terror_ghostface", "still")])
    engine = EffectEngine(script, EngineConfig(), events=events)
    drawn: dict[str, list[float]] = {"sonrisa": [], "mascara": []}
    for i in range(30):
        record = FrameRecord(frame=i, time_s=i / 30, pose=pose, people=[PersonPose(person_id="person_0", pose=pose)])
        for eid, _, layer in engine.render_frame(record, i, 400, 600, 60):
            drawn[eid].append(float(layer[..., 3].max()))
    assert max(drawn["sonrisa"][:9]) > 0.2  # antes de la máscara, la sonrisa se ve
    assert max(drawn["mascara"][15:]) > 0.2
    assert max(drawn["sonrisa"][12:]) == 0.0  # con la máscara puesta, nada más sobre la cara


def test_the_choreography_rejects_face_effects_during_a_special_face() -> None:
    from vfxglow.analysis.schema import MotionBrief, VideoMeta
    from vfxglow.director.choreography import choreograph, load_catalog
    from vfxglow.director.seasons import apply_to_catalog, load_seasons

    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    halloween = next(s for s in load_seasons(ROOT / "configs/seasons.yaml") if s.id == "halloween")
    catalog = apply_to_catalog(catalog, halloween)
    n = 300
    events = [MotionEvent(name="entrance", target="person_0", start_frame=0, end_frame=5, confidence=1.0)]
    events += [MotionEvent(name="smile", target="person_0", start_frame=f, end_frame=f + 20, confidence=1.0) for f in range(15, 90, 25)]
    meta = VideoMeta(path="x", fps=30.0, width=400, height=600, frame_count=n, duration_s=n / 30)
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="", people=["person_0"])
    for seed in range(6):
        _, choreo = choreograph(catalog, brief, seed)
        masks = [d for d in choreo.decisions if "terror" in d.choice]
        if not masks:
            continue
        mask = masks[0]
        during = [d for d in choreo.decisions if d.action == "smile" and mask.frame <= d.frame <= mask.until]
        assert during and all(d.choice.startswith("nada") for d in during), during
        return
    pytest.fail("la máscara no salió en ninguna semilla")


def test_a_mask_can_come_out_in_a_single_color() -> None:
    from vfxglow.engine.horror_masks import MONO, _colored

    mask = load_mask("pennywise")
    single = set()
    for seed in range(400):
        colors = {tuple(np.round(s["color"], 2).tolist()) for s in _colored(mask, seed)}
        if len(colors) == 1:
            single |= colors
    assert single == {tuple(np.round(np.asarray(c, np.float32), 2).tolist()) for c in MONO}


def test_each_appearance_can_have_another_color_and_the_mask_stays_intact() -> None:
    from vfxglow.engine.horror_masks import MASK_PALETTES, _colored

    mask = load_mask("pennywise")
    before = mask["strokes"][0]["color"].copy()
    seen = {tuple(np.round(_colored(mask, seed)[0]["color"], 2).tolist()) for seed in range(400)}
    assert len(seen) >= len(MASK_PALETTES) - 1
    assert np.array_equal(mask["strokes"][0]["color"], before)

