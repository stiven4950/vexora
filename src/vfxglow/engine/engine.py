"""Motor procedural. Lee tracks, eventos y el guion; no toca el video original."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.names import FACE_ANCHORS
from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.config import EngineConfig
from vfxglow.director.schema import EffectScript, effect_group, envelope
from vfxglow.analysis.appearance import Appearance
from vfxglow.engine.anchors import PointSet, collect_points, joint_velocity
from vfxglow.engine.constraints import FrameState, gain_for
from vfxglow.engine.effects import EffectRuntime, render_effect
from vfxglow.engine.raster import directional_blur, soften_alpha
from vfxglow.engine.timeline import ActivationTimeline
from vfxglow.io.store import read_jsonl


class EffectEngine:
    def __init__(
        self,
        script: EffectScript,
        config: EngineConfig,
        events: list[MotionEvent] | None = None,
        cuts: list[int] | None = None,
        fps: float = 30.0,
    ) -> None:
        self.script = script
        self.config = config
        self.events = events or []
        self.cuts = set(cuts or [])
        self.runtimes = [EffectRuntime(effect, script.seed, config.history) for effect in script.effects]
        for runtime in self.runtimes:
            runtime.fps = fps
        self.timelines = [ActivationTimeline(effect, self.events) for effect in script.effects]
        self.appearance: Appearance | None = None
        self._appearance_dir: Path | None = None
        self._face_last: dict[str, np.ndarray] = {}
        self._face_age = 0

    def _hold_face(self, points: PointSet) -> float:
        """Si la malla se pierde unos fotogramas, reutiliza la última y la desvanece."""
        face = {name: value for name, value in points.items() if _is_face(name)}
        if any(name[5:].isdigit() for name in face if name.startswith("face_")):
            self._face_last = face
            self._face_age = 0
            return 1.0
        hold = max(self.config.face_hold, 0)
        if not self._face_last or self._face_age >= hold:
            self._face_last = {}
            return 1.0 if "face_center" in points else 0.0
        self._face_age += 1
        fade = 1.0 - self._face_age / (hold + 1)
        for name, value in self._face_last.items():
            if name not in points:
                points.put(name, value, fade, "hold")
        return fade

    def render_frame(
        self,
        track: FrameRecord | None,
        frame_index: int,
        width: int,
        height: int,
        frame_count: int,
        run_dir: Path | None = None,
    ) -> list[tuple[str, str, np.ndarray]]:
        points = collect_points(track, width, height)
        cut = frame_index in self.cuts
        if cut:
            # Otro plano: la última malla pertenece a una cara que ya no está.
            self._face_last = {}
            self._face_age = 0
        face_fade = self._hold_face(points)
        self._attach_appearance(run_dir, frame_index, width, height)
        state = FrameState(face_fade=face_fade, bright=self._bright(frame_index))
        for name in list(points):
            if name.startswith("vel:") or _is_face(name):
                continue
            vx, vy = joint_velocity(track, name)
            points[f"vel:{name}"] = np.array([vx * width, vy * height], dtype=np.float64)
        mask = _load_mask(run_dir, track, width, height)
        layers: list[tuple[str, str, np.ndarray]] = []
        for runtime, timeline in zip(self.runtimes, self.timelines, strict=True):
            effect = runtime.effect
            event_gain, event = timeline.at(frame_index)
            if effect.triggers:
                gain = event_gain
            else:
                gain = envelope(frame_index, effect.time, frame_count)
            gain *= effect.style.intensity
            gain *= gain_for(effect, state, points, self.config.min_point_confidence)
            if cut or gain <= 0:
                runtime.active_frames = 0
            if gain > 0:
                runtime.active_frames += 1
            if event is not None and event.position is not None:
                runtime.anchor_point = np.array(
                    [event.position[0] * width, event.position[1] * height],
                    dtype=np.float64,
                )
            runtime.contour_px = None
            runtime.tool_tip = None
            if self.appearance is not None:
                poly = self.appearance.contours.get(frame_index)
                if poly:
                    runtime.contour_px = np.array([[x * width, y * height] for x, y in poly], dtype=np.float64)
                tip = self.appearance.tips.get(frame_index)
                if tip is not None:
                    runtime.tool_tip = np.array([tip[0] * width, tip[1] * height], dtype=np.float64)
            layer = render_effect(
                runtime,
                track,
                points,
                frame_index,
                width,
                height,
                gain,
                mask,
                self.config.max_particles,
                event,
            )
            decay = effect.render.persistence
            if decay > 0:
                if runtime.persist is None or runtime.persist.shape != layer.shape:
                    runtime.persist = np.zeros_like(layer)
                runtime.persist = layer + runtime.persist * np.float32(decay)
                runtime.persist[..., 3] = np.clip(runtime.persist[..., 3], 0.0, 1.0)
                layer = runtime.persist.copy()
            if effect.render.motion_blur > 0 and gain > 0:
                vx, vy = joint_velocity(track, effect.target.id)
                directional_blur(layer, vx * width, vy * height, effect.render.motion_blur)
            soften_alpha(layer)
            layers.append((effect.id, effect_group(effect), layer))
        return layers


    def _bright(self, frame_index: int) -> frozenset[str]:
        if self.appearance is None:
            return frozenset()
        return frozenset(
            region for start, end, region in self.appearance.bright_spans if start <= frame_index <= end
        )

    def _attach_appearance(self, run_dir: Path | None, frame_index: int, width: int, height: int) -> None:
        if run_dir is None or self.appearance is not None or self._appearance_dir == run_dir:
            return
        self._appearance_dir = run_dir
        path = run_dir / "analysis" / "appearance.json"
        self.appearance = Appearance.load(path) if path.exists() else Appearance()


_FACE_ANCHOR_SET = set(FACE_ANCHORS)


def _is_face(name: str) -> bool:
    return name.startswith("face_") or name in _FACE_ANCHOR_SET


def load_tracks(path: Path) -> list[FrameRecord]:
    return read_jsonl(path, FrameRecord)


def load_events(path: Path) -> list[MotionEvent]:
    if not path.exists():
        return []
    return read_jsonl(path, MotionEvent)


def save_layer(path: Path, layer: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, layer.astype(np.float16))


def load_layer(path: Path) -> np.ndarray:
    return np.load(path).astype(np.float32)


def _load_mask(run_dir: Path | None, track: FrameRecord | None, width: int, height: int) -> np.ndarray | None:
    if run_dir is None or track is None or not track.mask_path:
        return None
    path = run_dir / track.mask_path
    if not path.exists():
        return None
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        return None
    if mask.shape[:2] != (height, width):
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    return mask.astype(np.float32) / 255.0
