"""Composición en paralelo (composite/parallel.py) y capas vacías compartidas del motor."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from vfxglow.analysis.schema import FrameRecord, Landmark
from vfxglow.composite.parallel import OrderedFrames
from vfxglow.config import AppConfig, CompositeConfig, EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget, EffectTime
from vfxglow.engine.effects import EffectRuntime, render_effect
from vfxglow.engine.engine import EffectEngine


def _job(value: int, delay: float = 0.0) -> np.ndarray:
    time.sleep(delay)
    return np.full((1,), value, dtype=np.int32)


@pytest.mark.parametrize("threads", [1, 4])
def test_frames_are_written_in_submission_order(threads: int) -> None:
    written: list[int] = []
    n = 12
    with OrderedFrames(threads, lambda frame: written.append(int(frame[0]))) as ordered:
        for i in range(n):
            ordered.submit(_job, i, (n - i) * 0.005)  # los últimos terminan antes
        ordered.drain()
    assert written == list(range(n))


def test_in_flight_frames_are_bounded() -> None:
    threads, lock = 4, threading.Lock()
    started, written = [], []
    peak = 0

    def job(i: int) -> np.ndarray:
        with lock:
            started.append(i)
        time.sleep(0.01)
        return np.array([i])

    def write(frame: np.ndarray) -> None:
        nonlocal peak
        with lock:
            peak = max(peak, len(started) - len(written))
            written.append(int(frame[0]))

    with OrderedFrames(threads, write) as ordered:
        for i in range(40):
            ordered.submit(job, i)
            with lock:
                peak = max(peak, len(started) - len(written))
        ordered.drain()
    assert written == list(range(40))
    assert peak <= threads + 3


def test_worker_error_surfaces_in_submit_or_drain() -> None:
    def boom() -> np.ndarray:
        raise ValueError("falló")

    written: list[int] = []
    with pytest.raises(ValueError, match="falló"):
        with OrderedFrames(3, lambda frame: written.append(int(frame[0]))) as ordered:
            ordered.submit(_job, 0)
            ordered.submit(boom)
            ordered.submit(_job, 2)
            ordered.drain()
    assert written == [0]


def test_nothing_is_written_when_the_block_exits_with_an_error() -> None:
    written: list[int] = []
    with pytest.raises(RuntimeError, match="cancelado"):
        with OrderedFrames(3, lambda frame: written.append(int(frame[0]))) as ordered:
            for i in range(3):
                ordered.submit(_job, i, 0.01)
            raise RuntimeError("cancelado")
    assert written == []


def test_one_thread_runs_inline_on_the_caller() -> None:
    seen: list[int] = []
    wrote: list[int] = []

    def job() -> np.ndarray:
        seen.append(threading.get_ident())
        return np.zeros(1)

    with OrderedFrames(1, lambda frame: wrote.append(threading.get_ident())) as ordered:
        ordered.submit(job)
        assert wrote == [threading.get_ident()]  # ya escrito, sin esperar al drain
    assert seen == [threading.get_ident()]


def test_threads_must_be_positive() -> None:
    assert CompositeConfig().threads == 1
    with pytest.raises(ValidationError):
        CompositeConfig(threads=0)


W, H = 96, 64


def _track(i: int) -> FrameRecord:
    def lm(name: str, x: float, y: float) -> Landmark:
        return Landmark(name=name, x=x, y=y, z=0.0, c=0.99)

    return FrameRecord(frame=i, time_s=i / 30, pose=[lm("nose", 0.5, 0.2), lm("right_wrist", 0.6 + 0.01 * i, 0.5), lm("left_wrist", 0.3, 0.5)])


def _effect(id_: str, start: int, end: int) -> Effect:
    return Effect(
        id=id_,
        type="particles",
        target=EffectTarget(kind="joint", id="right_wrist"),
        time=EffectTime(start_frame=start, end_frame=end, fade_in=0, fade_out=0),
        style=EffectStyle(intensity=1.0, thickness=0.05, hdr_gain=2.0, colors=[(1.0, 0.4, 0.05), (1.0, 0.9, 0.4)]),
    )


def _script() -> EffectScript:
    return EffectScript(title="t", theme="t", seed=5, effects=[_effect("live", 0, 20), _effect("later", 15, 20)])


def test_engine_shares_a_read_only_blank_layer_for_idle_effects() -> None:
    engine = EffectEngine(_script(), EngineConfig(history=8, max_particles=40))
    layers = {effect_id: layer for effect_id, _group, layer in engine.render_frame(_track(2), 2, W, H, 20)}
    assert layers["later"] is engine.blank
    assert not engine.blank.flags.writeable and not engine.blank.any()
    assert layers["live"] is not engine.blank and layers["live"].flags.writeable and layers["live"].any()
    # Un cambio de tamaño rehace la capa vacía.
    engine.render_frame(_track(3), 3, W // 2, H // 2, 20)
    assert engine.blank.shape == (H // 2, W // 2, 4)


def test_scratch_buffer_gives_the_same_layer_as_a_fresh_one() -> None:
    script = _script()
    plain = [EffectRuntime(effect, script.seed, 8) for effect in script.effects]
    with_scratch = [EffectRuntime(effect, script.seed, 8) for effect in script.effects]
    scratch = np.zeros((H, W, 4), dtype=np.float32)
    for i in range(5):
        for a, b in zip(plain, with_scratch, strict=True):
            kwargs = dict(frame_index=i, width=W, height=H, envelope=1.0, mask=None, particle_limit=40)
            expected = render_effect(a, _track(i), {"right_wrist": np.array([60.0, 30.0])}, **kwargs)
            got = render_effect(b, _track(i), {"right_wrist": np.array([60.0, 30.0])}, scratch=scratch, **kwargs)
            assert got is scratch
            assert np.array_equal(expected, got)
            scratch[...] = 0.0


def test_pipeline_output_is_identical_with_several_threads(tmp_path: Path) -> None:
    import cv2

    from vfxglow.io.video import write_silent_video
    from vfxglow.pipeline import Pipeline

    n = 12
    frames = [np.full((H, W, 3), 30 + i, dtype=np.uint8) for i in range(n)]
    video = tmp_path / "plate.mp4"
    write_silent_video(video, frames, 30)
    script = _script()
    tracks = {i: _track(i) for i in range(n)}

    def render(threads: int) -> list[np.ndarray]:
        config = AppConfig()
        config.composite.threads = threads
        pipeline = Pipeline.__new__(Pipeline)
        pipeline.video, pipeline.run_dir, pipeline.config = video, tmp_path, config
        pipeline._meta = lambda: SimpleNamespace(fps=30.0, frame_count=n, width=W, height=H, has_audio=False)
        pipeline._engine = lambda script, events=None, tracks_=None: (EffectEngine(script, EngineConfig(history=8, max_particles=40)), tracks)
        dest = tmp_path / f"out{threads}.mp4"
        pipeline._write(script, dest, stream=True)
        cap = cv2.VideoCapture(str(dest))
        out = []
        while True:
            ok, image = cap.read()
            if not ok:
                break
            out.append(image)
        cap.release()
        return out

    one, three = render(1), render(3)
    assert len(one) == len(three) == n
    assert all(np.array_equal(a, b) for a, b in zip(one, three, strict=True))
