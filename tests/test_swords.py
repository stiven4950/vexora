"""Hojas, eventos de acrobacia y efectos de espadas."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.analysis.blades import _drop_jumps, _score_segment, finalize_blades
from vfxglow.analysis.events import EventDetector
from vfxglow.analysis.schema import Blade, FrameRecord, Landmark, MotionEvent, PersonPose, VideoMeta
from vfxglow.config import BladesConfig, EngineConfig, EventsConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget, EffectTrigger
from vfxglow.engine.engine import EffectEngine


def _lm(name: str, x: float, y: float) -> Landmark:
    return Landmark(name=name, x=x, y=y, c=0.95)


def test_segment_scoring_rejects_forearm_and_background() -> None:
    grip, elbow, torso = np.array([100.0, 100.0]), np.array([100.0, 160.0]), 60.0
    blade = _score_segment(np.array([102.0, 96.0]), np.array([102.0, 0.0]), grip, np.array([0.0, -1.0]), elbow, torso)
    assert blade is not None and blade[1][1] == pytest.approx(0.0)
    assert _score_segment(np.array([100.0, 104.0]), np.array([100.0, 170.0]), grip, None, elbow, torso) is None  # antebrazo
    assert _score_segment(np.array([300.0, 300.0]), np.array([400.0, 300.0]), grip, None, elbow, torso) is None  # fondo lejos


def test_finalize_fills_gaps_and_drops_jumps() -> None:
    def blade(frame: int, angle: float) -> Blade:
        tip = (0.5 + 0.1 * np.cos(angle), 0.5 + 0.1 * np.sin(angle) * 720 / 1280)
        return Blade(person="person_0", hand="right", hilt=(0.5, 0.5), tip=tip, source="line")

    pose = [_lm("nose", 0.5, 0.2)]
    frames = [FrameRecord(frame=i, time_s=0.0, pose=pose) for i in range(12)]
    for i in (0, 1, 2, 3, 6, 7, 8):
        frames[i].blades = [blade(i, -np.pi / 2)]
    frames[7].blades = [blade(7, np.pi / 2)]  # salto de 180°: ruido
    finalize_blades(frames, BladesConfig(mode="always", fill_gap=4, smooth=1.0), 720, 1280)
    sources = [f.blades[0].source if f.blades else None for f in frames]
    assert sources[4] == sources[5] == "prior"  # hueco corto rellenado
    assert frames[7].blades and frames[7].blades[0].tip[1] < 0.5  # el salto se descartó y se rellenó hacia arriba
    assert not frames[11].blades


def test_drop_jumps_keeps_consistent_blades() -> None:
    hits = {i: Blade(person="p", hand="left", hilt=(0, 0), tip=(10, 0)) for i in range(6)}
    hits[3] = Blade(person="p", hand="left", hilt=(0, 0), tip=(0, 10))
    _drop_jumps(hits)
    assert 3 not in hits and len(hits) == 5


def test_flip_landing_entrance_and_blade_swing() -> None:
    def frame(i: int) -> FrameRecord:
        inverted = 10 <= i < 16
        hip_y = 0.5
        nose_y = 0.7 if inverted else 0.3
        ankle_y = 0.4 if 8 <= i < 18 else 0.9
        pose = [_lm("nose", 0.5, nose_y), _lm("left_hip", 0.45, hip_y), _lm("right_hip", 0.55, hip_y),
                _lm("left_shoulder", 0.45, 0.35), _lm("left_ankle", 0.45, ankle_y), _lm("right_ankle", 0.55, ankle_y)]
        angle = -np.pi / 2 + (0.6 * (i - 20) if 20 <= i < 26 else 0.0)
        tip = (0.5 + 0.2 * np.cos(angle), 0.5 + 0.2 * np.sin(angle))
        record = FrameRecord(frame=i, time_s=i / 30, pose=pose, people=[PersonPose(person_id="person_0", pose=pose)])
        record.blades = [Blade(person="person_0", hand="right", hilt=(0.5, 0.5), tip=tip)]
        return record

    meta = VideoMeta(path="x", fps=30.0, width=100, height=100, frame_count=40, duration_s=1.3)
    events = EventDetector(EventsConfig()).detect([frame(i) for i in range(40)], meta)
    names = {e.name for e in events}
    assert {"flip", "landing", "entrance", "blade_swing"} <= names
    swing = next(e for e in events if e.name == "blade_swing")
    assert swing.target == "person_0:blade_right_tip"


def _render(effect: Effect, track: FrameRecord, events: list[MotionEvent] | None = None, frames: int = 6) -> np.ndarray:
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=events or [])
    layer = None
    for i in range(frames):
        layer = engine.render_frame(track.model_copy(update={"frame": i}), i, 200, 200, 40)[0][2]
    return layer


def _track() -> FrameRecord:
    pose = [_lm("left_shoulder", 0.4, 0.3), _lm("right_shoulder", 0.6, 0.3), _lm("left_hip", 0.42, 0.55), _lm("right_hip", 0.58, 0.55), _lm("nose", 0.5, 0.2)]
    contour = [(0.5 + 0.2 * np.cos(t), 0.5 + 0.3 * np.sin(t)) for t in np.linspace(0, 2 * np.pi, 40)]
    return FrameRecord(frame=0, time_s=0.0, pose=pose, blades=[Blade(person="person_0", hand="right", hilt=(0.6, 0.5), tip=(0.9, 0.3))], body_contour=contour)


def test_sword_effects_draw() -> None:
    track = _track()
    glow = Effect(id="g", type="blade_glow", target=EffectTarget(kind="joint", id="blade_right_tip"), style=EffectStyle(colors=[(0, 1, 1), (1, 1, 0)], thickness=0.05))
    alpha = _render(glow, track)[..., 3]
    assert alpha[int(0.4 * 200), int(0.75 * 200)] > 0.3  # sobre la hoja
    assert alpha[10, 10] == 0
    outline = Effect(id="o", type="body_outline", target=EffectTarget(kind="mask", id="person"), style=EffectStyle(shapes=["outline"]))
    assert _render(outline, track)[..., 3].max() > 0.3
    event = MotionEvent(name="landing", target="feet", start_frame=1, end_frame=1, confidence=1.0, position=(0.5, 0.8))
    for kind in ("ground_burst", "ground_cloud", "floor_streak"):
        effect = Effect(id=kind, type=kind, target=EffectTarget(kind="event_point", id="landing"), style=EffectStyle(size=0.6),
                        triggers=[EffectTrigger(event="landing", hold=8)])
        assert _render(effect, track, [event])[..., 3].max() > 0.2, kind


def test_eyewear_band_and_cross_mark_shapes() -> None:
    from vfxglow.engine.eyewear import figure
    from vfxglow.engine.marks import mark

    band = figure("band", np.array([100.0, 100.0]), np.array([140.0, 100.0]))
    assert len(band) == 1 and np.ptp(band[0][:, 0]) > 40
    rng = np.random.default_rng(0)
    assert len(mark("cross", np.array([50.0, 50.0]), None, 30.0, 0, rng, rng)) == 2


def test_blade_glow_triggered_by_a_cut_lights_only_that_blade() -> None:
    track = _track().model_copy(update={"blades": [
        Blade(person="person_0", hand="right", hilt=(0.6, 0.5), tip=(0.9, 0.3)),
        Blade(person="person_0", hand="left", hilt=(0.4, 0.5), tip=(0.1, 0.3)),
    ]})
    cut = MotionEvent(name="blade_swing", target="person_0:blade_right_tip", start_frame=1, end_frame=2, confidence=1.0)
    glow = Effect(id="g", type="blade_glow", target=EffectTarget(kind="joint", id="blade_right_tip"),
                  style=EffectStyle(colors=[(0, 1, 1), (1, 1, 0)], thickness=0.05),
                  triggers=[EffectTrigger(event="blade_swing", hold=6)])
    alpha = _render(glow, track, [cut], frames=3)[..., 3]
    assert alpha[int(0.4 * 200), int(0.75 * 200)] > 0.3  # la hoja del tajo
    assert alpha[int(0.4 * 200), int(0.25 * 200)] == 0  # la otra no
    assert _render(glow, track, [], frames=3)[..., 3].max() == 0  # sin tajo, nada


@pytest.mark.parametrize("material", ["neon", "lightning", "fire", "chainsaw"])
def test_blade_materials_draw_along_the_blade(material: str) -> None:
    glow = Effect(id="g", type="blade_glow", target=EffectTarget(kind="joint", id="blade_right_tip"),
                  style=EffectStyle(colors=[(1, 0.4, 0.1), (0.3, 0.7, 1)], thickness=0.04, shapes=[material]))
    alpha = _render(glow, _track(), frames=8)[..., 3]  # pasado el fundido de entrada (6 fotogramas)
    # Banda alrededor de la mitad de la hoja: la motosierra es un contorno y su eje queda vacío.
    y, x = int(0.4 * 200), int(0.75 * 200)
    assert alpha[y - 8 : y + 9, x - 8 : x + 9].max() > 0.2
    assert alpha[190, 10] == 0
