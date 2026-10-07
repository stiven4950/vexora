"""Orquesta el nivel de análisis elegido y escribe tracks, eventos, brief y overlay."""

from __future__ import annotations

import logging
from pathlib import Path

from vfxglow.analysis.appearance import analyze_appearance, retag_paint_beats, tip_touch_events
from vfxglow.analysis.beats import segment_beats
from vfxglow.analysis.events import EventDetector
from vfxglow.analysis.scene_reader import read_scenes
from vfxglow.analysis.flow import FlowEstimator, flow_stats
from vfxglow.analysis.kinematics import add_motion, build_brief
from vfxglow.analysis.objects import ObjectTracker
from vfxglow.analysis.overlay import write_debug_overlay
from vfxglow.analysis.postprocess import smooth_tracks
from vfxglow.analysis.schema import AnalysisHeader, FrameRecord, VideoMeta
from vfxglow.config import AppConfig
from vfxglow.device import require_cuda
from vfxglow.io.store import write_jsonl, write_model
from vfxglow.io.video import VideoReader

log = logging.getLogger("vfxglow.analysis")

# Una malla con menos puntos que esto es una detección parcial (p. ej. sobre una máscara) y no cuenta.
MIN_FACE_POINTS = 60


def analyze_video(video_path: Path, run_dir: Path, config: AppConfig, device: str) -> VideoMeta:
    if config.analysis.level == "masks":
        require_cuda("Las máscaras SAM 2.1", device)
    models_dir = Path(config.paths.models_dir)
    if not models_dir.is_absolute():
        models_dir = Path.cwd() / models_dir
    raw: list[FrameRecord] = []
    model_names: dict[str, str] = {}
    objects = ObjectTracker(config.analysis.objects, device)
    stride = max(config.analysis.objects.stride, 1)
    with VideoReader(video_path) as reader:
        meta = reader.meta
        flow = FlowEstimator(config.analysis.flow.method, device) if config.analysis.flow.enabled else None
        previous = None
        detector = _open_detector(config, device, models_dir)
        fallback = _open_fallback(config, models_dir)
        blades = None
        if config.analysis.blades.mode != "off":
            from vfxglow.analysis.blades import BladeFinder

            blades = BladeFinder(config.analysis.blades)
        try:
            model_names = dict(getattr(detector, "models", {}))
            if objects.enabled:
                model_names["objects"] = config.analysis.objects.model
            for index, frame in reader:
                record = _detect(detector, config, index, frame, meta.fps)
                needs_face = fallback is not None and config.analysis.face_fallback and len(record.face or []) < MIN_FACE_POINTS
                mask = fallback.mask(frame) if fallback is not None and (needs_face or config.analysis.body_contour) else None
                if needs_face:
                    fallback.apply(record, frame, mask)
                if mask is not None and config.analysis.body_contour:
                    from vfxglow.analysis.fallback import body_outline

                    record.body_contour = body_outline(mask)
                if blades is not None:
                    record.blades = blades.detect(record, frame)
                if objects.enabled:
                    if index % stride == 0:
                        record.objects = objects.update(objects.detect(frame))
                    else:
                        record.objects = objects.carry()
                if flow is not None and previous is not None:
                    record.flow = flow_stats(flow.between(previous, frame))
                previous = frame
                raw.append(record)
                if (index + 1) % 25 == 0:
                    log.info("Analizados %d/%d fotogramas", index + 1, meta.frame_count)
        finally:
            closer = getattr(detector, "close", None)
            if closer:
                closer()
            if fallback is not None:
                fallback.close()
        meta = meta.model_copy(update={"frame_count": len(raw), "duration_s": len(raw) / meta.fps})
    if config.analysis.level == "masks":
        from vfxglow.analysis.sam2_backend import Sam2Masker

        # La caja del prompt sale de la pose ya detectada, antes del suavizado fino.
        for record in raw:
            if record.pose and record.box is None:
                xs = [lm.x for lm in record.pose]
                ys = [lm.y for lm in record.pose]
                record.box = (min(xs), min(ys), max(xs), max(ys))
        Sam2Masker(
            config.analysis.masks.sam2_model_cfg,
            config.analysis.masks.sam2_checkpoint,
            device,
        ).apply(video_path, raw, run_dir)
    if config.analysis.face_fallback:
        from vfxglow.analysis.fallback import stabilize_heads

        stabilize_heads(raw, meta.width, meta.height)
    if config.analysis.blades.mode != "off":
        from vfxglow.analysis.blades import finalize_blades

        finalize_blades(raw, config.analysis.blades, meta.width, meta.height)
    frames = smooth_tracks(raw, meta.fps, config.analysis)
    add_motion(frames, meta, config.analysis.events.glitch_speed)
    events = EventDetector(config.analysis.events).detect(frames, meta)
    beats, onsets = segment_beats(frames, video_path, meta, config.analysis.beats)
    appearance = analyze_appearance(video_path, frames, meta)
    beats = retag_paint_beats(beats, appearance)
    events.extend(tip_touch_events(appearance))
    events.sort(key=lambda event: (event.start_frame, event.name))
    analysis = run_dir / "analysis"
    scenes = read_scenes(video_path, beats, analysis / "scene_cache", config.analysis.scene)
    brief = build_brief(frames, meta, events=events, beats=beats, scene=scenes, audio_onsets=onsets)
    from vfxglow.analysis.accessories import detect_accessories

    accessories = detect_accessories(video_path, frames, analysis / "scene_cache", config.analysis.accessories, config.analysis.scene)
    brief = brief.model_copy(update={"accessories": accessories})
    header = AnalysisHeader(
        video=meta,
        device=device,
        level=config.analysis.level,
        models=model_names,
        store_face=config.analysis.store_face,
    )
    write_model(analysis / "header.json", header)
    write_jsonl(analysis / "tracks.jsonl", frames)
    write_jsonl(analysis / "events.jsonl", events)
    write_model(analysis / "motion_brief.json", brief)
    appearance.save(analysis / "appearance.json")
    log.info("%d eventos detectados", len(events))
    log.info("Escribiendo overlay de depuración")
    write_debug_overlay(video_path, frames, meta, analysis / "debug_overlay.mp4", events)
    return meta


def _open_detector(config: AppConfig, device: str, models_dir: Path):
    level = config.analysis.level
    if level == "hq":
        from vfxglow.analysis.hq_backend import HQDetector

        hq = config.analysis.hq
        return HQDetector(hq.pose_mode, device)
    from vfxglow.analysis.mediapipe_backend import MediaPipeDetector

    return MediaPipeDetector(models_dir, config.analysis.mediapipe, config.analysis.store_face)


def _open_fallback(config: AppConfig, models_dir: Path):
    if not (config.analysis.face_fallback or config.analysis.body_contour) or config.analysis.level != "fast":
        return None
    from vfxglow.analysis.fallback import FaceFallback
    from vfxglow.analysis.models_store import ensure_model

    return FaceFallback(str(ensure_model(models_dir, "selfie_segmenter.tflite")))


def _detect(detector, config: AppConfig, index: int, frame, fps: float) -> FrameRecord:
    if config.analysis.level == "hq":
        return detector.detect(index, frame, fps, config.analysis.store_face)
    return detector.detect(index, frame, fps)
