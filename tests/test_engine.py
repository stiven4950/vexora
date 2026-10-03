"""Motor, flujo, composición y compuertas de CUDA."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.flow import farneback
from vfxglow.analysis.schema import FrameRecord, Landmark, VideoMeta
from vfxglow.config import EngineConfig, RefinerConfig
from vfxglow.director.presets import load_preset
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget, EffectTime
from vfxglow.engine.engine import EffectEngine
from vfxglow.io.store import write_jsonl, write_model
from vfxglow.io.video import write_silent_video
from vfxglow.pipeline import Pipeline
from vfxglow.refiner.refiner import mix_seed
from vfxglow.refiner.warp import warp_image

ROOT = Path(__file__).resolve().parents[1]


def _track(i: int, n: int) -> FrameRecord:
    t = i / max(n - 1, 1)

    def lm(name: str, x: float, y: float) -> Landmark:
        return Landmark(name=name, x=x, y=y, z=0.0, c=0.99)

    cx = 0.45
    return FrameRecord(
        frame=i,
        time_s=i / 30,
        pose=[
            lm("nose", cx, 0.2),
            lm("left_shoulder", cx - 0.12, 0.34),
            lm("right_shoulder", cx + 0.12, 0.34),
            lm("left_elbow", cx - 0.18, 0.48),
            lm("right_elbow", cx + 0.18, 0.46),
            lm("left_wrist", cx - 0.22, 0.6),
            lm("right_wrist", 0.62 + 0.12 * np.sin(t * 6), 0.42 + 0.08 * np.cos(t * 6)),
            lm("left_hip", cx - 0.08, 0.58),
            lm("right_hip", cx + 0.08, 0.58),
            lm("left_knee", cx - 0.08, 0.74),
            lm("right_knee", cx + 0.09, 0.74),
            lm("left_ankle", cx - 0.08, 0.9),
            lm("right_ankle", cx + 0.1, 0.9),
        ],
    )


def _script_all_types() -> EffectScript:
    def fx(id_: str, kind: str, target: str, secondary: str | None = None, target_kind: str = "joint") -> Effect:
        return Effect(
            id=id_,
            type=kind,  # type: ignore[arg-type]
            target=EffectTarget(kind=target_kind, id=target, secondary=secondary),  # type: ignore[arg-type]
            time=EffectTime(start_frame=0, end_frame=5, fade_in=0, fade_out=0),
            style=EffectStyle(intensity=1.0, thickness=0.05, hdr_gain=2.0, colors=[(1.0, 0.4, 0.05), (1.0, 0.9, 0.4)]),
        )

    return EffectScript(
        title="todos",
        theme="test",
        seed=3,
        effects=[
            fx("trail", "trail", "right_wrist"),
            fx("parts", "particles", "right_wrist"),
            fx("ribbon", "ribbon", "right_arm", target_kind="chain"),
            fx("stroke", "stroke", "left_arm", target_kind="chain"),
            fx("aura", "aura", "person", target_kind="mask"),
            fx("bolt", "lightning", "right_wrist"),
            fx("rune", "decal", "face_oval", target_kind="face_region"),
            fx("warp", "distortion", "spine", target_kind="chain"),
            fx("cracks", "cracks", "right_wrist"),
            fx("ripples", "ripples", "right_wrist"),
            fx("charge", "charge", "right_wrist"),
            fx("sparks", "sparks", "right_wrist"),
        ],
    )


def test_engine_draws_every_effect_type() -> None:
    n = 4
    tracks = [_track(i, n) for i in range(n)]
    engine = EffectEngine(_script_all_types(), EngineConfig(history=8, max_particles=80))
    energy = {effect.id: 0.0 for effect in engine.script.effects}
    for i, track in enumerate(tracks):
        for effect_id, _group, layer in engine.render_frame(track, i, 160, 120, n):
            energy[effect_id] += float(layer[..., :3].sum())
    assert energy["parts"] > 0
    assert energy["trail"] > 0
    assert energy["ribbon"] > 0
    assert energy["stroke"] > 0
    assert energy["aura"] > 0
    assert energy["bolt"] > 0
    assert energy["rune"] > 0
    assert energy["cracks"] > 0
    assert energy["ripples"] > 0
    assert energy["sparks"] > 0
    assert energy["charge"] > 0


def test_farneback_and_warp_follow_motion() -> None:
    prev = np.zeros((48, 64, 3), dtype=np.uint8)
    curr = prev.copy()
    prev[20:28, 10:18] = 255
    curr[20:28, 16:24] = 255
    flow = farneback(prev, curr)
    assert flow.shape == (48, 64, 2)
    assert float(flow[24, 14, 0]) > 0
    layer = np.zeros((48, 64, 4), dtype=np.float32)
    layer[20:28, 16:24, 0] = 1
    layer[20:28, 16:24, 3] = 1
    synthetic = np.zeros((48, 64, 2), dtype=np.float32)
    synthetic[..., 0] = 6
    warped = warp_image(layer, synthetic)
    assert warped[24, 22, 0] > warped[24, 16, 0]


def test_mix_seed_is_stable() -> None:
    assert mix_seed(7, "fire", 3) == mix_seed(7, "fire", 3)
    assert mix_seed(7, "fire", 3) != mix_seed(7, "fire", 4)


def test_hq_and_refiner_guards() -> None:
    from vfxglow.analysis.hq_backend import HQDetector
    from vfxglow.analysis.sam2_backend import Sam2Masker
    from vfxglow.refiner.refiner import DiffusionRefiner

    with pytest.raises(RuntimeError, match="CUDA"):
        Sam2Masker("cfg", "missing.pt", "cpu")
    with pytest.raises(RuntimeError, match="CUDA"):
        DiffusionRefiner(RefinerConfig(enabled=True), "mps")
    try:
        import rtmlib  # noqa: F401
        import ultralytics  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="hq"):
            HQDetector("balanced", "cpu")
    else:
        pytest.skip("extras hq instalados")


def test_pipeline_render_and_compose(tmp_path: Path) -> None:
    import yaml

    from vfxglow.analysis.schema import AnalysisHeader
    from vfxglow.composite.composite import composite_frame
    from vfxglow.config import load_config
    from vfxglow.engine.engine import load_layer

    n, w, h = 6, 160, 96
    frames = []
    for _ in range(n):
        image = np.full((h, w, 3), 40, dtype=np.uint8)
        image[:, :, 1] = 70
        image[0, 0] = (8, 16, 24)
        frames.append(image)
    video = tmp_path / "plate.mp4"
    write_silent_video(video, frames, 30)
    cfg = load_config(ROOT / "configs" / "default.yaml")
    cfg.paths.runs_dir = str(tmp_path / "runs")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    pipeline = Pipeline(config_path, video)
    meta = VideoMeta(path=str(video), fps=30, width=w, height=h, frame_count=n, duration_s=n / 30, has_audio=False)
    write_model(
        pipeline.run_dir / "analysis" / "header.json",
        AnalysisHeader(video=meta, device="cpu", level="fast", models={"pose": "synthetic"}, store_face=False),
    )
    tracks = [_track(i, n) for i in range(n)]
    write_jsonl(pipeline.run_dir / "analysis" / "tracks.jsonl", tracks)
    script = load_preset(ROOT / "configs" / "presets" / "avatar_fire.yaml", n)
    write_model(pipeline.run_dir / "scripts" / "effect_script.json", script)
    pipeline.render()
    layers = [
        (effect, load_layer(pipeline.run_dir / "layers" / effect.id / "f000003.npy"))
        for effect in script.effects
    ]
    composed = composite_frame(frames[3], layers, script.grade)
    rgb = frames[3][..., ::-1]
    assert np.abs(composed[0, 0].astype(np.int16) - rgb[0, 0].astype(np.int16)).max() <= 1
    assert composed.mean() > rgb.mean()
    final = pipeline.compose()
    assert final.exists() and final.stat().st_size > 0
    assert (pipeline.run_dir / "layers" / "index.json").exists()


def test_groups_can_disable_lightning() -> None:
    from vfxglow.composite.composite import composite_frame
    from vfxglow.director.schema import EffectRender

    plate = np.full((32, 40, 3), 30, dtype=np.uint8)
    effect = Effect(
        id="bolt",
        type="lightning",
        target=EffectTarget(kind="joint", id="right_wrist"),
        render=EffectRender(group="lightning"),
    )
    layer = np.zeros((32, 40, 4), dtype=np.float32)
    layer[10:20, 10:20, :3] = 4.0
    layer[10:20, 10:20, 3] = 1.0
    off = composite_frame(plate, [(effect, layer)], effect_script_grade(), enabled_groups={"glow"})
    on = composite_frame(plate, [(effect, layer)], effect_script_grade(), enabled_groups={"lightning"})
    assert np.allclose(off, plate[..., ::-1], atol=1)
    assert on.mean() > off.mean()


def effect_script_grade():
    from vfxglow.director.schema import Grade

    return Grade()


def test_lightning_is_continuous_across_frames() -> None:
    n = 6
    tracks = [_track(i, n) for i in range(n)]
    script = EffectScript(
        title="rayo",
        theme="test",
        seed=2,
        effects=[
            Effect(
                id="bolt",
                type="lightning",
                target=EffectTarget(kind="joint", id="right_wrist"),
                time=EffectTime(start_frame=0, end_frame=n - 1, fade_in=0, fade_out=0),
                style=EffectStyle(intensity=1.0, thickness=0.04, hdr_gain=3.0, colors=[(0.8, 0.9, 1.0)]),
            )
        ],
    )
    engine = EffectEngine(script, EngineConfig(history=6, max_particles=40))
    prev = None
    diffs = []
    for i, track in enumerate(tracks):
        _, _, layer = engine.render_frame(track, i, 160, 120, n)[0]
        if prev is not None:
            diffs.append(float(np.mean(np.abs(layer - prev))))
        prev = layer
        assert layer[..., :3].sum() > 0
    assert diffs and max(diffs) < 0.35


def test_pointset_keeps_confidence_and_source() -> None:
    from vfxglow.engine.anchors import PointSet, collect_points

    track = FrameRecord(
        frame=0,
        time_s=0.0,
        pose=[Landmark(name="nose", x=0.5, y=0.5, c=0.4), Landmark(name="left_wrist", x=0.2, y=0.2, c=0.0)],
    )
    points = collect_points(track, 100, 100)
    assert isinstance(points, PointSet)
    assert points.confidence("nose") == pytest.approx(0.4)
    assert points.origin("nose") == "pose"
    assert "left_wrist" not in points
    points["vel:nose"] = np.zeros(2)
    assert points.confidence("vel:nose") == 1.0 and points.origin("vel:nose") == "derived"


def _effect(kind: str, target: str, target_kind: str = "joint") -> Effect:
    return Effect(id=kind, type=kind, target=EffectTarget(kind=target_kind, id=target))


def test_constraints_veto_bright_features_and_fade_face() -> None:
    from vfxglow.engine.anchors import PointSet
    from vfxglow.engine.constraints import FrameState, gain_for

    points = PointSet()
    points.put("left_eye", np.zeros(2), 0.9, "face_mesh")
    eyes_bright = FrameState(bright=frozenset({"eyes"}))
    assert gain_for(_effect("feature_light", "left_eye"), eyes_bright, points) == 0.0
    assert gain_for(_effect("feature_light", "nose"), eyes_bright, points) == 1.0
    # Los anillos de face_neon sobre lentes blancos son intencionales: el veto no los toca.
    assert gain_for(_effect("eye_rings", "eyes", "face_region"), eyes_bright, points) == 1.0
    held = FrameState(face_fade=0.25)
    assert gain_for(_effect("eye_rings", "eyes", "face_region"), held, points) == 0.25
    assert gain_for(_effect("trail", "left_eye"), held, points) == 1.0


def test_constraints_low_confidence_degrades_only_when_enabled() -> None:
    from vfxglow.engine.anchors import PointSet
    from vfxglow.engine.constraints import FrameState, gain_for

    points = PointSet()
    points.put("right_wrist", np.zeros(2), 0.2, "pose")
    trail = _effect("trail", "right_wrist")
    assert gain_for(trail, FrameState(), points) == 1.0
    assert gain_for(trail, FrameState(), points, min_confidence=0.5) == pytest.approx(0.4)


def test_mouth_and_head_top_follow_the_current_frame() -> None:
    from vfxglow.engine.anchors import collect_points

    def frame(x: float) -> FrameRecord:
        return FrameRecord(
            frame=0,
            time_s=0.0,
            pose=[
                Landmark(name="nose", x=x, y=0.5, c=1.0),
                Landmark(name="mouth_left", x=x + 0.02, y=0.55, c=1.0),
                Landmark(name="mouth_right", x=x - 0.02, y=0.55, c=1.0),
            ],
        )

    a = collect_points(frame(0.3), 100, 200)
    b = collect_points(frame(0.7), 100, 200)
    assert a["mouth"] == pytest.approx([30.0, 110.0])
    assert b["mouth"] == pytest.approx([70.0, 110.0])
    assert b["head_top"] == pytest.approx([70.0, 100.0 - 16.0])
    assert "mouth" not in collect_points(FrameRecord(frame=1, time_s=0.0), 100, 200)


def test_held_face_does_not_cross_a_cut() -> None:
    from vfxglow.engine.anchors import PointSet

    face = [Landmark(name=f"face_{i}", x=0.5 + 0.001 * i, y=0.4, c=0.9) for i in (33, 133, 362, 263, 468, 473)]
    with_face = FrameRecord(frame=0, time_s=0.0, face=face)
    script = EffectScript(
        title="t",
        theme="t",
        effects=[Effect(id="rings", type="eye_rings", target=EffectTarget(kind="face_region", id="eyes"))],
    )
    config = EngineConfig(face_hold=8)

    held = EffectEngine(script, config, cuts=[])
    held.render_frame(with_face, 0, 64, 64, 4)
    points = PointSet()
    assert held._hold_face(points) > 0
    assert any(points.origin(name) == "hold" for name in points)

    cut = EffectEngine(script, config, cuts=[1])
    cut.render_frame(with_face, 0, 64, 64, 4)
    cut.render_frame(None, 1, 64, 64, 4)
    assert cut._face_last == {}


def test_bright_spans_bridge_blinks_and_drop_flicker() -> None:
    from vfxglow.analysis.appearance import BRIGHT_GAP, BRIGHT_MIN, _merge_spans

    raw = [(f, f, "eyes") for f in (*range(14, 22), *range(25, 29), 37, *range(41, 48), 120)]
    spans = [s for s in _merge_spans(raw, BRIGHT_GAP) if s[1] - s[0] + 1 >= BRIGHT_MIN]
    # 22-24 y 38-40 son parpadeos y se puentean; 29-36 supera el hueco y separa; 120 suelto se descarta.
    assert spans == [(14, 28, "eyes"), (37, 47, "eyes")]
