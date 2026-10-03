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
