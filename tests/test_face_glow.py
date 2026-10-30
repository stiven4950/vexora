"""Catálogo `cara` (engine/face_glow.py): cada efecto dibuja sobre la cara, de la malla o sin ella."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.names import FACE_FEATURES, FACE_NAMED
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionBrief, MotionEvent, PersonPose, VideoMeta
from vfxglow.config import EngineConfig
from vfxglow.director.choreography import choreograph, load_catalog
from vfxglow.director.pins import Pin, PinFile
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.engine import EffectEngine
from vfxglow.engine.face_glow import FACE_GLOW, Face

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS, N = 400, 600, 30.0, 60


def _mesh(cx: float = 0.5, cy: float = 0.3, size: float = 0.12, squash_right: float = 1.0) -> list[Landmark]:
    """Una malla facial sintética: cada rasgo en su lugar sobre una elipse; `squash_right` < 1
    angosta el ojo derecho (la cara girando hacia ese lado)."""
    marks = {}
    places = {"right_eye": (-0.35, -0.1, 0.16, 0.06), "left_eye": (0.35, -0.1, 0.16, 0.06), "right_brow": (-0.35, -0.3, 0.2, 0.03),
              "left_brow": (0.35, -0.3, 0.2, 0.03), "lips_outer": (0.0, 0.55, 0.25, 0.08), "lips_inner": (0.0, 0.55, 0.18, 0.03),
              "nose_bridge": (0.0, 0.15, 0.02, 0.2), "nose_base": (0.0, 0.32, 0.1, 0.02), "face_oval": (0.0, 0.15, 0.75, 0.95)}
    for feature, chain in FACE_FEATURES.items():
        x0, y0, rx, ry = places[feature]
        if feature == "right_eye":
            rx *= squash_right
        for k, index in enumerate(chain):
            t = 2 * np.pi * k / max(len(chain) - 1, 1)
            marks[index] = (cx + (x0 + rx * np.cos(t)) * size, cy + (y0 + ry * np.sin(t)) * size)
    for name, index in FACE_NAMED.items():
        if index not in marks:
            x, y = {"right_iris": (-0.35, -0.1), "left_iris": (0.35, -0.1), "nose_tip": (0.0, 0.3), "chin": (0.0, 1.05), "forehead_top": (0.0, -0.75), "upper_lip": (0.0, 0.5), "lower_lip": (0.0, 0.6)}[name]
            marks[index] = (cx + x * size, cy + y * size)
    return [Landmark(name=f"face_{i}", x=x, y=y, c=0.95) for i, (x, y) in marks.items()]


POSE = {"nose": (0.5, 0.33), "left_eye": (0.54, 0.31), "right_eye": (0.46, 0.31), "left_ear": (0.58, 0.32), "right_ear": (0.42, 0.32),
        "left_shoulder": (0.62, 0.45), "right_shoulder": (0.38, 0.45), "left_hip": (0.6, 0.8), "right_hip": (0.4, 0.8),
        "left_elbow": (0.68, 0.6), "right_elbow": (0.32, 0.6), "left_wrist": (0.7, 0.75), "right_wrist": (0.3, 0.75)}


def _body(mesh: bool = True, **mesh_kwargs) -> Body:
    from vfxglow.engine.anchors import collect_points

    record = FrameRecord(frame=0, time_s=0.0, pose=[Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in POSE.items()], face=_mesh(**mesh_kwargs) if mesh else None)
    return Body(collect_points(record, W, H), None)


def _draw(shape: str, body: Body, frames=range(0, 30, 3)) -> float:
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "x", "hold": 10}])
    event = MotionEvent(name="x", target="person_0", start_frame=0, end_frame=19, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    runtime.frame_shape = (H, W)
    drawn = 0.0
    for f in frames:
        runtime.active_frames = f
        layer = np.zeros((H, W, 4), np.float32)
        lines = adornment(shape, body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        drawn = max(drawn, float(layer[..., 3].max()), 1.0 if lines else 0.0)
    return drawn


@pytest.mark.parametrize("shape", FACE_GLOW)
def test_every_face_effect_draws_with_and_without_the_mesh(shape: str) -> None:
    assert _draw(shape, _body()) > 0.3
    if shape not in ("face_mesh_live", "face_crystal", "face_scan"):  # sin malla: plantillas de la pose
        assert _draw(shape, _body(mesh=False)) > 0.3


def test_the_far_side_of_a_turned_face_is_hidden() -> None:
    assert Face(_body(), 100.0).far_side() is None
    turned = Face(_body(squash_right=0.3), 100.0)
    assert turned.far_side() == "right" and not turned.visible("right_eye") and turned.visible("left_eye")


def test_every_option_of_the_face_catalog_draws_where_it_is_pinned() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    pose = [Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in POSE.items()]
    frames = [FrameRecord(frame=i, time_s=i / FPS, pose=pose, face=_mesh(), people=[PersonPose(person_id="person_0", pose=pose, face=_mesh())]) for i in range(N)]
    meta = VideoMeta(path="x", fps=FPS, width=W, height=H, frame_count=N, duration_s=N / FPS)
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=[], summary="", people=["person_0"])
    needs_more = {"llama_pincel", "beso"}  # la punta del pincel y la mano en la cara: se prueban con video
    silent = []
    for reaction in catalog.reactions:
        for option in reaction.options:
            if not option.effects or option.name in needs_more:
                continue
            pins = PinFile(solo_estos=True, momentos=[Pin(seg=0.5, accion=reaction.action, opcion=option.name, persona="person_0", dur=1.0)])
            script, _ = choreograph(catalog, brief, 1, pins)
            engine = EffectEngine(script, EngineConfig(), events=[], fps=FPS)
            drawn = 0.0
            for i in range(14, 50):
                layers = engine.render_frame(frames[i], i, W, H, N)
                drawn = max([drawn, *(float(layer[..., 3].max()) for _, _, layer in layers)])
            if drawn < 0.05:
                silent.append(f"{reaction.action}:{option.name}")
    assert not silent, f"No dibujan nada al fijarlos: {silent}"
