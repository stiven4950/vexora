"""Pruebas de configuración, color, suavizado y brief."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.kinematics import add_motion, build_brief
from vfxglow.analysis.postprocess import smooth_tracks
from vfxglow.analysis.schema import FrameRecord, Landmark, VideoMeta
from vfxglow.analysis.smoothing import catmull_uniform, fill_short_gaps, smooth_series
from vfxglow.composite.color import shoulder
from vfxglow.composite.composite import composite_frame
from vfxglow.config import AppConfig, OneEuroConfig, load_config
from vfxglow.device import require_cuda, resolve_device
from vfxglow.director.schema import Effect, EffectScript
from vfxglow.geom import catmull_rom, rdp

ROOT = Path(__file__).resolve().parents[1]


def test_config_yaml_loads() -> None:
    cfg = load_config(ROOT / "configs" / "default.yaml")
    assert cfg.analysis.level == "fast"
    assert cfg.refiner.enabled is False
    assert cfg.director.preset == "avatar_fire"


def test_device_auto_is_known() -> None:
    assert resolve_device("auto") in {"cpu", "mps", "cuda"}
    assert resolve_device("cpu") == "cpu"


def test_require_cuda_fails_on_cpu() -> None:
    with pytest.raises(RuntimeError, match="CUDA"):
        require_cuda("SAM 2.1", "cpu")


def test_shoulder_is_identity_below_threshold() -> None:
    values = np.array([0.2, 0.85, 2.5], dtype=np.float32)
    out = shoulder(values, 0.85)
    assert out[0] == pytest.approx(0.2)
    assert out[1] == pytest.approx(0.85)
    assert out[2] < values[2]


def test_zero_layer_keeps_plate() -> None:
    plate = np.full((24, 32, 3), 90, dtype=np.uint8)
    plate[0, 0] = (10, 20, 30)
    script = EffectScript(
        title="vacío",
        theme="none",
        effects=[
            Effect.model_validate(
                {
                    "id": "nada",
                    "type": "particles",
                    "target": {"kind": "joint", "id": "right_wrist"},
                }
            )
        ],
    )
    layer = np.zeros((24, 32, 4), dtype=np.float32)
    out = composite_frame(plate, [(script.effects[0], layer)], script.grade)
    rgb = plate[..., ::-1]
    assert np.abs(out.astype(np.int16) - rgb.astype(np.int16)).max() <= 1


def test_gap_fill_and_long_gap() -> None:
    values = np.array([0.0, np.nan, np.nan, np.nan, 1.0, 1.0], dtype=np.float64)
    valid = np.array([True, False, False, False, True, True])
    filled, mask = fill_short_gaps(values, valid, max_gap=3)
    assert mask[1:4].all()
    assert filled[2] == pytest.approx(catmull_uniform(0, 0, 1, 1, 0.5), abs=0.15)
    long_values = np.array([0.0, *([np.nan] * 8), 1.0])
    long_valid = np.array([True, *([False] * 8), True])
    _, long_mask = fill_short_gaps(long_values, long_valid, max_gap=3)
    assert not long_mask[1]


def test_one_euro_holds_a_constant() -> None:
    signal = np.ones(12)
    out, valid = smooth_series(signal, np.ones(12), 30, 0.3, 4, OneEuroConfig())
    assert valid.all()
    assert np.allclose(out, 1.0)


def test_rdp_and_catmull_pass_through_controls() -> None:
    line = np.stack([np.linspace(0, 10, 20), np.zeros(20)], axis=1)
    reduced = rdp(line, epsilon=0.1)
    assert len(reduced) == 2
    controls = np.array([[0.0, 0.0], [1.0, 2.0], [3.0, 0.5], [4.0, 1.0]])
    curve = catmull_rom(controls, samples_per_seg=8)
    assert curve[0] == pytest.approx(controls[0])
    assert curve[-1] == pytest.approx(controls[-1])


def _person(n: int = 12) -> tuple[list[FrameRecord], VideoMeta]:
    frames = []
    for i in range(n):
        t = i / max(n - 1, 1)
        cx = 0.35 + 0.3 * t
        jitter = 0.0 if i % 5 else 0.0

        def lm(name: str, x: float, y: float, c: float = 0.95) -> Landmark:
            return Landmark(name=name, x=x + jitter, y=y, z=0.0, c=c)

        pose = [
            lm("nose", cx, 0.22),
            lm("left_shoulder", cx - 0.1, 0.35),
            lm("right_shoulder", cx + 0.1, 0.35),
            lm("left_elbow", cx - 0.16, 0.5),
            lm("right_elbow", cx + 0.16, 0.48),
            lm("left_wrist", cx - 0.18, 0.62),
            lm("right_wrist", cx + 0.2, 0.42 - 0.12 * t),
            lm("left_hip", cx - 0.08, 0.62),
            lm("right_hip", cx + 0.08, 0.62),
            lm("left_knee", cx - 0.08, 0.78),
            lm("right_knee", cx + 0.08, 0.78),
            lm("left_ankle", cx - 0.08, 0.92),
            lm("right_ankle", cx + 0.08, 0.92),
        ]
        if 4 <= i <= 6:
            pose = [item for item in pose if item.name != "right_wrist"]
        frames.append(FrameRecord(frame=i, time_s=i / 30, pose=pose))
    meta = VideoMeta(path="person.mp4", fps=30, width=200, height=200, frame_count=n, duration_s=n / 30)
    return frames, meta


def test_smoothing_fills_short_wrist_gap_and_brief_has_path() -> None:
    frames, meta = _person()
    cfg = AppConfig()
    smooth_tracks(frames, meta.fps, cfg.analysis)
    wrists = []
    for frame in frames:
        found = next(lm for lm in frame.pose if lm.name == "right_wrist")
        wrists.append(found.c)
    assert all(c > 0 for c in wrists[3:8])
    add_motion(frames, meta)
    brief = build_brief(frames, meta)
    assert brief.summary
    hand = next(limb for limb in brief.limbs if limb.name == "right_hand")
    assert hand.path
    assert hand.peak_speed >= 0


def test_encoder_publishes_only_complete_video(tmp_path: Path) -> None:
    from vfxglow.composite.encode import FrameEncoder

    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    dest = tmp_path / "out.mp4"
    short = FrameEncoder(dest, 16, 16, 30.0, frames=3)
    short.write(frame)
    with pytest.raises(RuntimeError):
        short.close()
    assert not dest.exists() and not short.partial.exists()

    aborted = FrameEncoder(dest, 16, 16, 30.0)
    aborted.write(frame)
    aborted.abort()
    assert not dest.exists() and not aborted.partial.exists()

    full = FrameEncoder(dest, 16, 16, 30.0, frames=2)
    full.write(frame)
    full.write(frame)
    full.close()
    assert dest.exists() and not full.partial.exists()


def test_code_fingerprint_is_stable_and_scoped() -> None:
    from vfxglow.io.store import code_fingerprint

    assert code_fingerprint("engine") == code_fingerprint("engine")
    assert code_fingerprint("engine") != code_fingerprint("composite")
    assert code_fingerprint("geom.py") != code_fingerprint("engine", "geom.py")


def test_env_file_loads_without_overriding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow.cli import load_env_file

    env = tmp_path / ".env"
    env.write_text('# comentario\nVFX_TEST_A="uno"\nexport VFX_TEST_B=dos\nVFX_TEST_C=nuevo\n', encoding="utf-8")
    monkeypatch.delenv("VFX_TEST_A", raising=False)
    monkeypatch.delenv("VFX_TEST_B", raising=False)
    monkeypatch.setenv("VFX_TEST_C", "existente")
    load_env_file(env)
    import os

    assert os.environ["VFX_TEST_A"] == "uno"
    assert os.environ["VFX_TEST_B"] == "dos"
    assert os.environ["VFX_TEST_C"] == "existente"


def test_write_only_window_writes_just_those_frames_and_scales(tmp_path: Path) -> None:
    from types import SimpleNamespace

    import cv2

    from vfxglow.pipeline import Pipeline

    video = tmp_path / "clip.mp4"
    out = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48))
    for i in range(30):
        out.write(np.full((48, 64, 3), i * 8, np.uint8))
    out.release()

    drawn: list[int] = []

    class Engine:
        def render_frame(self, track, index, *args):
            drawn.append(index)
            return []

    pipeline = Pipeline.__new__(Pipeline)
    pipeline.video, pipeline.run_dir, pipeline.config = video, tmp_path, AppConfig()
    pipeline._meta = lambda: SimpleNamespace(fps=10.0, frame_count=30, width=64, height=48, has_audio=False)
    pipeline._engine = lambda script, events=None, tracks=None: (Engine(), {})
    script = EffectScript.model_validate({"title": "t", "theme": "x", "effects": []})
    dest = tmp_path / "vista.mp4"
    written = pipeline.render_preview(script, dest, (12, 20), max_side=32)
    assert written == 9
    assert drawn == list(range(0, 21))  # calentamiento (2 s = 20 fotogramas, aquí desde el 0) y tramo; nada después
    cap = cv2.VideoCapture(str(dest))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 9 and (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (32, 24)
    cap.release()


def test_window_extras_works_on_copies_of_the_window_and_swaps_blade_and_prop_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import vfxglow.analysis.extras as extras
    from vfxglow.analysis.analyzer import DERIVED
    from vfxglow.analysis.schema import AnalysisHeader, MotionBrief, MotionEvent
    from vfxglow.io.store import write_jsonl, write_model
    from vfxglow.pipeline import Pipeline

    meta = VideoMeta(path="v.mp4", fps=10.0, width=64, height=48, frame_count=60, duration_s=6.0)
    folder = tmp_path / "analysis"
    frames = [FrameRecord(frame=i, time_s=i / 10) for i in range(60)]
    old_events = [
        MotionEvent(name="fast_swing", target="person_0:right_wrist", start_frame=5, end_frame=8, confidence=0.9),
        MotionEvent(name="blade_swing", target="person_0:blade_right_tip", start_frame=40, end_frame=42, confidence=0.8),
    ]
    write_model(folder / "header.json", AnalysisHeader(video=meta, device="cpu", level="fast", models={}, store_face=False))
    write_jsonl(folder / "tracks.jsonl", frames)
    write_jsonl(folder / "events.jsonl", old_events)
    write_model(folder / "motion_brief.json", MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=old_events, summary="", derived=list(DERIVED)))
    seen: list[int] = []

    def fake(video, window_frames, meta, config):
        seen.extend(f.frame for f in window_frames)
        for f in window_frames:
            f.person_id = "con_hoja"
        return [MotionEvent(name="blade_swing", target="person_0:blade_left_tip", start_frame=35, end_frame=37, confidence=0.8)]

    monkeypatch.setattr(extras, "window_extras", fake)
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.video, pipeline.run_dir, pipeline.config = tmp_path / "v.mp4", tmp_path, AppConfig()
    assert pipeline.window_extras((30, 39)) is None  # sin `needs`: nada que calcular
    pipeline.config.analysis.blades.mode = "always"
    brief, tracks, events = pipeline.window_extras((30, 39))
    assert seen == list(range(10, 40))  # 2 s de calentamiento (20 fotogramas) y el tramo
    assert tracks[12].person_id == "con_hoja" and tracks[45].person_id == "person_0"
    assert [(e.name, e.start_frame) for e in events] == [("fast_swing", 5), ("blade_swing", 35)]
    assert [(e.name, e.start_frame) for e in brief.events] == [("fast_swing", 5), ("blade_swing", 35)]
    assert "con_hoja" not in (folder / "tracks.jsonl").read_text()  # el análisis guardado no cambia
