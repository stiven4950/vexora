"""sprite_fx: animaciones ya renderizadas, ancladas al evento y escaladas con el cuerpo."""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine
from vfxglow.engine.sprite import load_sprite

W, H = 400, 800
POSE = [Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in {"left_shoulder": (0.58, 0.3), "right_shoulder": (0.42, 0.3), "left_hip": (0.56, 0.55), "right_hip": (0.44, 0.55), "right_wrist": (0.3, 0.5)}.items()]


def _render(style: EffectStyle, event: MotionEvent | None, frames: int = 6) -> np.ndarray:
    target = EffectTarget(kind="event_point", id="hit") if event else EffectTarget(kind="joint", id="right_wrist")
    triggers = [{"event": event.name, "hold": 20, "fade_in": 0, "fade_out": 0}] if event else []
    effect = Effect(id="s", type="sprite_fx", target=target, style=style, triggers=triggers)
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[event] if event else [])
    layer = None
    for i in range(frames):
        layer = engine.render_frame(FrameRecord(frame=i, time_s=i / 30, pose=POSE), i, W, H, 60)[0][2]
    return layer


def test_png_sequence_is_anchored_to_the_event_and_scaled_with_the_body(tmp_path) -> None:
    folder = tmp_path / "dot"
    folder.mkdir()
    for k in range(4):
        image = np.zeros((64, 64, 4), np.uint8)
        cv2.circle(image, (32, 32), 10 + 5 * k, (255, 255, 255, 255), -1)
        cv2.imwrite(str(folder / f"{k:04d}.png"), image)
    event = MotionEvent(name="impact", target="person_0", start_frame=0, end_frame=10, confidence=1.0, position=(0.7, 0.4))
    layer = _render(EffectStyle(sprite=str(folder), size=0.5), event)
    ys, xs = np.nonzero(layer[..., 3] > 0.5)
    assert abs(xs.mean() - 0.7 * W) < 4 and abs(ys.mean() - 0.4 * H) < 4
    torso = 0.25 * H  # hombro-cadera
    assert np.ptp(ys) > 0.25 * 0.5 * torso  # creció con la animación y la escala del cuerpo


def test_video_without_alpha_makes_black_transparent(tmp_path) -> None:
    path = tmp_path / "flash.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (64, 64))
    for _ in range(5):
        frame = np.zeros((64, 64, 3), np.uint8)
        cv2.circle(frame, (32, 32), 12, (255, 255, 255), -1)
        writer.write(frame)
    writer.release()
    frames, fps = load_sprite(str(path))
    assert fps > 0 and frames[0][0, 0, 3] < 0.05 and frames[0][32, 32, 3] > 0.9
    layer = _render(EffectStyle(sprite=str(path), size=0.5), None)
    ys, xs = np.nonzero(layer[..., 3] > 0.5)
    assert xs.size and abs(xs.mean() - 0.3 * W) < 4  # pegado a la muñeca (target)


def test_demo_sprite_loads() -> None:
    frames, _ = load_sprite("demo_burst")
    assert len(frames) == 16 and frames[0].shape[2] == 4


def _object(flags: list[str], frames: int, tmp_path, event_frames: int = 30) -> np.ndarray:
    path = tmp_path / "obj.png"
    image = np.zeros((40, 40, 3), np.uint8)
    cv2.rectangle(image, (8, 8), (32, 32), (255, 255, 255), -1)  # luz sobre negro, como los de halloween/
    cv2.imwrite(str(path), image)
    event = MotionEvent(name="impact", target="person_0", start_frame=0, end_frame=event_frames, confidence=1.0, position=(0.5, 0.5))
    return _render(EffectStyle(sprite=str(path), size=0.4, shapes=flags), event, frames)


def test_pop_grows_in_and_rise_floats_up(tmp_path) -> None:
    early = (_object(["pop"], 2, tmp_path)[..., 3] > 0.5).sum()
    later = (_object(["pop"], 12, tmp_path)[..., 3] > 0.5).sum()
    assert 0 < early < later  # aparece creciendo
    start = np.nonzero(_object(["rise"], 2, tmp_path)[..., 3] > 0.5)[0].mean()
    end = np.nonzero(_object(["rise"], 30, tmp_path)[..., 3] > 0.5)[0].mean()
    assert end < start - 0.1 * H  # sube


def test_fade_goes_out_at_the_end(tmp_path) -> None:
    assert _object(["fade"], 5, tmp_path)[..., 3].max() > 0.5
    assert _object(["fade"], 49, tmp_path)[..., 3].max() < 0.2  # en el último tramo de su momento


def test_flat_lies_on_the_floor_squashed(tmp_path) -> None:
    ys, xs = np.nonzero(_object(["flat"], 10, tmp_path)[..., 3] > 0.5)
    assert np.ptp(xs) > 2 * np.ptp(ys)  # un cuadrado acostado: ancho y bajo


def test_corner_goes_to_the_nearest_top_corner(tmp_path) -> None:
    ys, xs = np.nonzero(_object(["corner"], 10, tmp_path)[..., 3] > 0.5)
    assert ys.min() < 20 and (xs.min() < 20 or xs.max() > W - 20)  # pegado a la esquina (con el borde negro de la imagen)
