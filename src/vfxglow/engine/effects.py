"""Traduce un efecto del guion a una capa HDR premultiplicada."""

from __future__ import annotations

import zlib
from collections import deque

import cv2
import numpy as np

from vfxglow.analysis.names import CHEEKS, FACE68_BROWS, FACE68_JAW, FACE_OVAL, FOREHEAD
from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.director.schema import Effect
from vfxglow.engine.anchors import chain_points, joint_speed, resolve_anchor, torso_pixels
from vfxglow.engine.interaction import draw_charge, draw_cracks, draw_ripples, draw_sparks
from vfxglow.engine.lightning import BoltTree, draw_lightning
from vfxglow.engine.noise import ValueNoise
from vfxglow.engine.particles import Particle, draw_particles, spawn_particles, step_particles
from vfxglow.engine.raster import empty_layer, sample_gradient, splat, stroke_gradient, stroke_polyline
from vfxglow.geom import catmull_rom, normals


class EffectRuntime:
    def __init__(self, effect: Effect, seed: int, history: int) -> None:
        self.effect = effect
        self.noise = ValueNoise(seed + effect.style.seed_offset * 997)
        self.rng = np.random.default_rng((seed + effect.style.seed_offset * 131) & 0xFFFFFFFF)
        self.history: deque[np.ndarray] = deque(maxlen=history)
        self.particles: list[Particle] = []
        self.kernels: dict[int, np.ndarray] = {}
        self.bolt_slot = -1
        self.bolt_prev: BoltTree | None = None
        self.bolt_curr: BoltTree | None = None
        self.persist: np.ndarray | None = None
        self.anchor_point: np.ndarray | None = None
        self.crack_key: object = None
        self.crack_lines: list[np.ndarray] = []
        self.active_frames = 0
        self.fps = 30.0
        self.swoosh: dict[str, deque] = {}
        self.swoosh_activity: dict[str, float] = {}
        self.swoosh_stroke: dict[str, int] = {}
        self.swoosh_paint: set[str] = set()
        self.palette_key: object = None
        self.micro: list = []
        self.micro_key: object = None
        self.burst_key: object = None
        self.burst_seed = 0
        self.bits: list = []
        self.limb_frames: dict[str, int] = {}
        self.chapter_colors: list | None = None
        self.chapter_frame = 0
        self.focus_level = 1.0


def render_effect(
    runtime: EffectRuntime,
    track: FrameRecord | None,
    points: dict[str, np.ndarray],
    frame_index: int,
    width: int,
    height: int,
    envelope: float,
    mask: np.ndarray | None,
    particle_limit: int,
    event: MotionEvent | None = None,
) -> np.ndarray:
    effect = runtime.effect
    if effect.style.palette:
        _pick_colors(runtime, frame_index, event)
    if runtime.anchor_point is not None:
        points = dict(points)
        points["event_point"] = runtime.anchor_point
    layer = empty_layer(height, width)
    kind = effect.type
    if kind == "particles":
        _particles(runtime, track, points, envelope, particle_limit, layer)
    elif kind == "trail":
        _trail(runtime, points, frame_index, envelope, layer)
    elif kind in {"ribbon", "stroke"}:
        _ribbon(runtime, points, frame_index, height, envelope, layer, noisy=kind == "ribbon")
    elif kind == "aura":
        _aura(runtime, points, frame_index, height, envelope, mask, layer)
    elif kind == "lightning":
        draw_lightning(runtime, track, points, frame_index, height, envelope, layer)
    elif kind == "decal":
        _decal(runtime, points, frame_index, height, envelope, layer)
    elif kind == "distortion":
        _ribbon(runtime, points, frame_index, height, envelope, layer, noisy=True)
        _distort(layer, runtime.noise, frame_index, effect)
    elif kind == "cracks":
        draw_cracks(runtime, points, frame_index, height, envelope, layer, event)
    elif kind == "ripples":
        draw_ripples(runtime, points, frame_index, height, envelope, layer, event)
    elif kind == "charge":
        draw_charge(runtime, points, frame_index, height, envelope, layer, event)
    elif kind == "sparks":
        draw_sparks(runtime, points, frame_index, height, envelope, layer, event)
    elif kind == "swoosh":
        from vfxglow.engine.swoosh import draw_swoosh

        draw_swoosh(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind in {"flame_burst", "spark_dashes", "clash", "stars"}:
        from vfxglow.engine.burst import draw_clash, draw_flame_burst, draw_spark_dashes, draw_stars

        draw = {"flame_burst": draw_flame_burst, "spark_dashes": draw_spark_dashes, "clash": draw_clash, "stars": draw_stars}[kind]
        draw(runtime, points, frame_index, height, envelope, layer, event)
    elif kind in {"blade_glow", "blade_echo"}:
        from vfxglow.engine.sword import draw_blade_echo, draw_blade_glow

        if kind == "blade_glow":
            draw_blade_glow(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
        else:
            draw_blade_echo(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind in {"body_outline", "ground_burst", "ground_cloud", "floor_streak"}:
        from vfxglow.engine import sword

        if kind == "body_outline":
            sword.draw_body_outline(runtime, track, points, frame_index, height, envelope, layer, event)
        else:
            draw = {"ground_burst": sword.draw_ground_burst, "ground_cloud": sword.draw_ground_cloud, "floor_streak": sword.draw_floor_streak}[kind]
            draw(runtime, points, frame_index, height, envelope, layer, event)
    elif kind in {"prop_outline", "prop_spring", "prop_rings", "prop_doodle"}:
        from vfxglow.engine.prop import draw_prop_doodle, draw_prop_outline, draw_prop_rings, draw_prop_spring

        draw = {"prop_outline": draw_prop_outline, "prop_spring": draw_prop_spring, "prop_rings": draw_prop_rings, "prop_doodle": draw_prop_doodle}[kind]
        draw(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind == "limb_rings":
        from vfxglow.engine.flow import draw_limb_rings

        draw_limb_rings(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind == "throw_fx":
        from vfxglow.engine.gesture_fx import draw_throw_fx

        draw_throw_fx(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind == "face_toon":
        from vfxglow.engine.face_toon import draw_face_toon

        draw_face_toon(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind in {"body_glow", "adornment"}:
        from vfxglow.engine.bodyglow import draw_adornment, draw_body_glow

        (draw_body_glow if kind == "body_glow" else draw_adornment)(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind == "intent_mark":
        from vfxglow.engine.marks import draw_intent_mark

        draw_intent_mark(runtime, track, points, frame_index, height, envelope, layer, event)
    elif kind == "eyewear":
        from vfxglow.engine.eyewear import draw_eyewear

        draw_eyewear(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind == "beam":
        from vfxglow.engine.burst import draw_beam

        draw_beam(runtime, track, points, frame_index, height, envelope, layer, event)
    elif kind == "arm_outline":
        from vfxglow.engine.limb import draw_arm_outline

        draw_arm_outline(runtime, track, points, frame_index, height, envelope, layer, event if effect.triggers else None)
    elif kind == "droplets":
        from vfxglow.engine.burst import draw_droplets

        draw_droplets(runtime, track, points, frame_index, height, envelope, layer)
    elif kind in {"eye_rings", "face_linework", "drawing"}:
        from vfxglow.engine.face_fx import draw_drawing, draw_eye_rings, draw_face_linework

        draw = {"eye_rings": draw_eye_rings, "face_linework": draw_face_linework, "drawing": draw_drawing}[kind]
        draw(runtime, points, frame_index, layer, envelope)
    elif kind in {"glyph", "impact_accent", "smear", "silhouette", "grade", "contour", "tip_flame", "feature_light"}:
        from vfxglow.engine.accents import (
            draw_anchored_glyph,
            draw_contour,
            draw_feature_light,
            draw_grade,
            draw_impact,
            draw_silhouette,
            draw_smear,
            draw_tip_flame,
        )

        _draw_strategy(
            kind,
            runtime,
            track,
            points,
            width,
            height,
            envelope,
            layer,
            draw_anchored_glyph,
            draw_contour,
            draw_feature_light,
            draw_grade,
            draw_impact,
            draw_silhouette,
            draw_smear,
            draw_tip_flame,
        )
    if effect.render.occlude and mask is not None:
        occ = cv2.erode((mask > 0.5).astype(np.uint8), np.ones((5, 5), np.uint8))
        keep = 1.0 - occ.astype(np.float32)
        layer[..., :3] *= keep[..., None]
        layer[..., 3] *= keep
    return layer


def _pick_colors(runtime: EffectRuntime, frame_index: int, event: MotionEvent | None) -> None:
    """Sortea dos colores distintos de la paleta por activación (o por tramo, sin evento).

    Con capítulos en el guion, toma los dos colores del capítulo: todo lo que se enciende en
    ese tramo comparte color."""
    style = runtime.effect.style
    if runtime.chapter_colors:
        style.colors = [tuple(color) for color in runtime.chapter_colors]
        return
    key = (event.start_frame, event.target) if event is not None else frame_index // max(style.palette_every, 1)
    if runtime.palette_key == key:
        return
    runtime.palette_key = key
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:{runtime.effect.id}:{key}".encode()) & 0xFFFFFFFF)
    count = min(2, len(style.palette))
    weights = None
    if len(style.palette_weights) == len(style.palette) and sum(style.palette_weights) > 0:
        weights = np.asarray(style.palette_weights, dtype=np.float64)
        weights = weights / weights.sum()
    picks = rng.choice(len(style.palette), size=count, replace=False, p=weights)
    style.colors = [style.palette[int(i)] for i in picks]


def _width(effect: Effect, points: dict[str, np.ndarray], height: int, envelope: float) -> float:
    return max(1.5, effect.style.thickness * torso_pixels(points, height) * max(envelope, 0.15))


def _displace(points: np.ndarray, noise: ValueNoise, frame_index: int, effect: Effect, amount: float) -> np.ndarray:
    if amount <= 0 or len(points) < 2:
        return points
    nrm = normals(points)
    shifted = points.copy()
    scale = max(effect.style.noise.scale, 1.0)
    z = frame_index * effect.style.noise.speed * 0.15
    for i, (point, normal) in enumerate(zip(points, nrm, strict=True)):
        sample = noise.scalar(float(point[0] / scale), float(point[1] / scale), z, effect.style.noise.octaves)
        shifted[i] = point + normal * sample * amount
    return shifted


def _particles(runtime: EffectRuntime, track, points, envelope, limit, layer) -> None:
    effect = runtime.effect
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    step_particles(runtime.particles)
    if origin is not None and envelope > 0:
        spawn_particles(
            runtime.particles,
            runtime.rng,
            origin,
            effect,
            envelope,
            _width(effect, points, layer.shape[0], 1.0),
            joint_speed(track, effect.target.id),
            limit,
        )
    draw_particles(layer, runtime.particles, effect, max(envelope, 0.0), runtime.kernels)


def _trail(runtime: EffectRuntime, points, frame_index, envelope, layer) -> None:
    effect = runtime.effect
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if origin is not None and envelope > 0:
        runtime.history.append(origin.copy())
    if len(runtime.history) < 2 or envelope <= 0:
        return
    curve = catmull_rom(np.stack(runtime.history), samples_per_seg=6)
    amount = effect.style.noise.amplitude * _width(effect, points, layer.shape[0], envelope)
    curve = _displace(curve, runtime.noise, frame_index, effect, amount)
    width = _width(effect, points, layer.shape[0], envelope)
    stroke_gradient(layer, curve, effect.style, width, envelope)
    stroke_gradient(layer, curve, effect.style, max(1.0, width * 0.35), envelope)


def _ribbon(runtime, points, frame_index, height, envelope, layer, noisy: bool) -> None:
    effect = runtime.effect
    if envelope <= 0:
        return
    if effect.target.kind == "chain":
        raw = chain_points(points, effect.target.id)
    else:
        origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
        raw = None if origin is None else np.stack([origin, origin + np.array([0.0, -_width(effect, points, height, 1.0) * 2])])
    if raw is None:
        return
    curve = catmull_rom(raw, samples_per_seg=8)
    if noisy:
        curve = _displace(curve, runtime.noise, frame_index, effect, effect.style.noise.amplitude * _width(effect, points, height, envelope))
    width = _width(effect, points, height, envelope)
    stroke_gradient(layer, curve, effect.style, width, envelope)
    hot = sample_gradient(effect.style.colors, 0.0)
    stroke_polyline(layer, curve, hot, max(1.0, width * 0.33), effect.style.hdr_gain * envelope, envelope)


def _aura(runtime, points, frame_index, height, envelope, mask, layer) -> None:
    effect = runtime.effect
    if envelope <= 0:
        return
    width = _width(effect, points, height, envelope)
    if mask is not None and mask.any():
        contours, _ = cv2.findContours((mask > 0.4).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if contours:
            contour = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
            if len(contour) > 8:
                step = max(1, len(contour) // 80)
                curve = _displace(contour[::step], runtime.noise, frame_index, effect, width * effect.style.noise.amplitude)
                for scale, fade in ((1.0, 0.35), (1.8, 0.22), (2.8, 0.12)):
                    stroke_gradient(layer, curve, effect.style, width * scale, envelope * fade)
                return
    loop = chain_points(points, "torso")
    if loop is not None:
        curve = catmull_rom(loop, samples_per_seg=6)
        curve = _displace(curve, runtime.noise, frame_index, effect, width * 0.4)
        for scale, fade in ((1.0, 0.45), (2.2, 0.25), (3.6, 0.12)):
            stroke_gradient(layer, curve, effect.style, width * scale, envelope * fade)
    color = sample_gradient(effect.style.colors, 0.35) * effect.style.hdr_gain * envelope
    for name in ("nose", "left_shoulder", "right_shoulder", "mid_hip"):
        if name in points:
            splat(layer, float(points[name][0]), float(points[name][1]), width * 2.2, color, 0.35 * envelope, runtime.kernels)


def _decal(runtime, points, frame_index, height, envelope, layer) -> None:
    effect = runtime.effect
    if envelope <= 0:
        return
    width = max(1.0, _width(effect, points, height, envelope) * 0.45)
    polylines = _face_polylines(points, effect.target.id)
    if not polylines and "nose" in points:
        center = points["nose"]
        radius = torso_pixels(points, height) * 0.18
        angles = np.linspace(0, 2 * np.pi, 36, endpoint=False)
        ring = np.stack([center[0] + np.cos(angles) * radius, center[1] + np.sin(angles) * radius * 1.25], axis=1)
        ring = np.vstack([ring, ring[0]])
        polylines = [ring]
    for line in polylines:
        curve = _displace(line, runtime.noise, frame_index, effect, width * effect.style.noise.amplitude * 2)
        stroke_gradient(layer, curve, effect.style, width, envelope)


def _face_polylines(points: dict[str, np.ndarray], region: str) -> list[np.ndarray]:
    if any(name.startswith("face_") and not name.startswith("face68_") for name in points):
        groups = {
            "face_oval": (FACE_OVAL,),
            "forehead": (FOREHEAD,),
            "cheeks": CHEEKS,
        }.get(region, (FACE_OVAL,))
        return [line for line in (_indexed(points, "face_", group) for group in groups) if line is not None]
    if any(name.startswith("face68_") for name in points):
        groups = (FACE68_JAW, FACE68_BROWS) if region != "forehead" else (FACE68_BROWS,)
        return [line for line in (_indexed(points, "face68_", group) for group in groups) if line is not None]
    return []


def _indexed(points: dict[str, np.ndarray], prefix: str, indices: tuple[int, ...]) -> np.ndarray | None:
    found = [points[f"{prefix}{i}"] for i in indices if f"{prefix}{i}" in points]
    if len(found) < 2:
        return None
    return np.stack(found)


def _distort(layer: np.ndarray, noise: ValueNoise, frame_index: int, effect: Effect) -> None:
    height, width = layer.shape[:2]
    step = 12
    ys = np.arange(0, height, step, dtype=np.float32)
    xs = np.arange(0, width, step, dtype=np.float32)
    grid_x, grid_y = np.meshgrid(xs, ys)
    scale = max(effect.style.noise.scale, 1.0)
    z = frame_index * effect.style.noise.speed * 0.2
    amp = effect.style.noise.amplitude * max(effect.style.thickness * height, 4.0)
    dx = noise.fbm(grid_x / scale, grid_y / scale, z, effect.style.noise.octaves) * np.float32(amp)
    dy = noise.fbm(grid_x / scale + 17, grid_y / scale, z + 3, effect.style.noise.octaves) * np.float32(amp)
    dx = cv2.resize(dx, (width, height), interpolation=cv2.INTER_LINEAR)
    dy = cv2.resize(dy, (width, height), interpolation=cv2.INTER_LINEAR)
    map_x, map_y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    src_x = np.ascontiguousarray((map_x + dx).astype(np.float32))
    src_y = np.ascontiguousarray((map_y + dy).astype(np.float32))
    warped = cv2.remap(layer, src_x, src_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    layer[:] = warped


def _draw_strategy(kind, runtime, track, points, width, height, envelope, layer, glyph, contour, feature, grade, impact, silhouette, smear, flame) -> None:
    effect = runtime.effect
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if kind == "impact_accent" and origin is not None:
        impact(runtime, layer, origin, envelope)
    elif kind == "smear":
        smear(runtime, points, layer, envelope)
    elif kind == "silhouette":
        silhouette(runtime, track, width, height, layer, envelope)
    elif kind == "grade":
        grade(effect, layer, envelope)
    elif kind == "contour":
        # El contorno de cabeza del respaldo es una curva abierta: cerrarla cruzaría el cuello.
        contour(runtime, getattr(runtime, "contour_px", None), layer, envelope, effect.target.id != "head")
    elif kind == "tip_flame":
        flame(runtime, getattr(runtime, "tool_tip", None) if getattr(runtime, "tool_tip", None) is not None else origin, layer, envelope)
    elif kind == "feature_light":
        feature(runtime, points, layer, envelope)
    elif kind == "glyph":
        glyph(runtime, points, layer, envelope)
