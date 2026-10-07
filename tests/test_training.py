"""Sistema de entrenamiento: geometría OBB, alineación, extractor, store y dataset."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from vfxglow.training.geometry import obb_to_segment, segment_to_obb, yolo_obb_line


def test_obb_roundtrip_and_yolo_line() -> None:
    a, b = np.array([10.0, 20.0]), np.array([110.0, 70.0])
    corners = segment_to_obb(a, b, width=8)
    p, q = obb_to_segment(corners)
    assert {tuple(np.round(p, 6)), tuple(np.round(q, 6))} == {tuple(a), tuple(b)}
    line = yolo_obb_line(0, corners, 200, 100).split()
    assert line[0] == "0" and len(line) == 9 and all(0 <= float(v) <= 1 for v in line[1:])


def test_aligner_undoes_zoom() -> None:
    from vfxglow.training.pairs import Aligner

    rng = np.random.default_rng(0)
    frame = cv2.GaussianBlur((rng.random((320, 180, 3)) * 255).astype(np.uint8), (0, 0), 3)
    zoom = cv2.warpAffine(frame, cv2.getRotationMatrix2D((90, 160), 0, 1.15), (180, 320))
    aligned = Aligner()(frame, zoom)
    assert aligned is not None
    inner = (slice(60, 260), slice(40, 140))
    before = np.abs(zoom.astype(int) - frame.astype(int))[inner].mean()
    after = np.abs(aligned.astype(int) - frame.astype(int))[inner].mean()
    assert after < before * 0.5


def test_store_sheets_rejections_and_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow.training import store
    from vfxglow.training.dataset import build, motion_blur
    from vfxglow.training.pairs import Labeled
    from vfxglow.training.task import Task

    monkeypatch.chdir(tmp_path)
    task = Task(name="t", classes=["blade"], holdout=["held"])
    image = np.full((100, 80, 3), 120, np.uint8)
    box = segment_to_obb(np.array([10.0, 10.0]), np.array([60.0, 80.0]))
    for source in ("src", "held"):
        items = [Labeled(source=source, frame=i, image=image, boxes=[box]) for i in range(3)]
        store.save(items, task.data_dir / "labels" / "t" / source)
        assert store.write_sheets(task.data_dir / "labels" / "t" / source, task.review_dir / source) == 1
    (task.review_dir / "src" / "rejected.txt").write_text("# x\nsrc_f000001\n")
    counts = build(task)
    assert counts[("src", "train")] == 2 and counts[("src", "rechazada")] == 1
    assert counts[("held", "val")] == 3 and counts[("src", "train_blur")] == 2
    assert (task.dataset_dir / "data.yaml").exists()
    assert len(list((task.dataset_dir / "labels" / "train").glob("*.txt"))) == 4
    blurred = motion_blur(np.eye(31, dtype=np.uint8)[..., None].repeat(3, 2) * 255, np.random.default_rng(1), (9, 9))
    assert blurred.shape == (31, 31, 3)


def test_blade_task_file_loads() -> None:
    from vfxglow.training.task import load_task

    task = load_task(Path(__file__).resolve().parents[1] / "training" / "tasks" / "blade.yaml")
    assert task.classes == ["blade"] and "video_39" in task.holdout
    assert task.weights == Path("models/blade-obb.pt")
