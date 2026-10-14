"""Guion de prueba: lo fijado a mano manda sobre el sorteo y sale en el video."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.schema import FrameRecord, JointMotion, Landmark, MotionBrief, MotionEvent, PersonPose, VideoMeta
from vfxglow.config import EngineConfig
from vfxglow.director.choreography import choreograph, load_catalog
from vfxglow.director.pins import Pin, PinFile, load_pins, pins_from_choreography, save_pins
from vfxglow.engine.engine import EffectEngine

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS, N = 400, 600, 30.0, 120
POSE = {
    "nose": (0.0, -0.36), "left_eye": (-0.015, -0.375), "right_eye": (0.015, -0.375), "left_ear": (-0.035, -0.36), "right_ear": (0.035, -0.36),
    "left_shoulder": (-0.07, -0.27), "right_shoulder": (0.07, -0.27), "left_hip": (-0.05, 0.0), "right_hip": (0.05, 0.0),
    "left_elbow": (-0.11, -0.16), "right_elbow": (0.11, -0.16), "left_wrist": (-0.13, -0.05), "right_wrist": (0.13, -0.05),
    "left_knee": (-0.05, 0.17), "right_knee": (0.05, 0.17), "left_ankle": (-0.05, 0.34), "right_ankle": (0.05, 0.34),
    "left_heel": (-0.05, 0.35), "right_heel": (0.05, 0.35), "left_foot_index": (-0.07, 0.36), "right_foot_index": (0.07, 0.36),
}


def _person(pid: str, cx: float, i: int) -> PersonPose:
    """Baila: brazos que suben y bajan deprisa y una rodilla que se abre."""
    lms = []
    for name, (x, y) in POSE.items():
        dx = dy = 0.0
        if "wrist" in name or "elbow" in name:
            dy = -0.12 * np.sin(i * 0.6) * (1.0 if "wrist" in name else 0.5)
        if name.startswith("left_") and any(k in name for k in ("knee", "ankle", "heel", "foot")):
            dx = -0.04 * abs(np.sin(i * 0.4))
        lms.append(Landmark(name=name, x=cx + x + dx, y=0.5 + y + dy, c=0.95))
    # La velocidad la calcula el análisis: aquí, golpes rápidos de muñeca (pico 0,3; en video_34 el
    # 1% más rápido pasa de 0,35).
    speed = 0.3 * abs(np.cos(i * 0.6))
    motion = [JointMotion(name=n, speed=speed, direction_deg=-90.0, vx=0.0, vy=-speed) for n in ("left_wrist", "right_wrist")]
    return PersonPose(person_id=pid, pose=lms, motion=motion)


def _frames() -> list[FrameRecord]:
    out = []
    for i in range(N):
        people = [_person("person_0", 0.3, i), _person("person_1", 0.7, i)]
        out.append(FrameRecord(frame=i, time_s=i / FPS, person_id="person_0", pose=people[0].pose, motion=people[0].motion, people=people))
    return out


def _brief(events: list[MotionEvent] | None = None) -> MotionBrief:
    meta = VideoMeta(path="x", fps=FPS, width=W, height=H, frame_count=N, duration_s=N / FPS)
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events or [], summary="", people=["person_0", "person_1"])


def _spot(person: str, frame: int, kind: str) -> MotionEvent:
    return MotionEvent(name="spotlight", target=person, start_frame=frame, end_frame=frame + 20, confidence=1.0, kind=kind)


def test_a_pinned_moment_wins_over_the_draw() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/baile_duo.yaml")
    pins = PinFile(momentos=[Pin(seg=1.0, opcion="rodillas", persona="person_1")])
    _, choreo = choreograph(catalog, _brief([_spot("person_1", 30, "legs")]), 1, pins)
    assert [d.choice for d in choreo.decisions if d.frame == 30 and d.target == "person_1"] == ["rodillas (fijado)"]


def test_without_a_detected_event_the_moment_is_created() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/baile_duo.yaml")
    script, choreo = choreograph(catalog, _brief(), 1, PinFile(solo_estos=True, momentos=[Pin(seg=2.0, opcion="bola_espejos")]))
    assert [d.choice for d in choreo.decisions] == ["bola_espejos (fijado)"]
    assert [e.start_frame for e in script.extra_events if e.name == "frenzy"] == [60]
    assert [e.id for e in script.effects] == ["frenzy_bola_espejos_0_fijado_0"]


def test_only_these_leaves_out_everything_else_and_mirror_copies_to_the_partner() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/baile_duo.yaml")
    events = [_spot("person_0", 10, "legs"), _spot("person_1", 40, "left_arm")]
    pins = PinFile(solo_estos=True, momentos=[Pin(seg=10 / FPS, opcion="rodillas", persona="person_0", espejo=True)])
    script, choreo = choreograph(catalog, _brief(events), 1, pins)
    assert {e.id for e in script.effects} == {"spotlight_rodillas_0_fijado_0", "spotlight_rodillas_0_fijado_1"}
    assert {e.triggers[0].targets[0] for e in script.effects} == {"person_0", "person_1"}
    assert all(not e.style.focus for e in script.effects)
    assert {d.target for d in choreo.decisions} == {"person_0", "person_1"}


def test_impossible_moments_are_errors() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/baile_duo.yaml")
    with pytest.raises(ValueError, match="no existe"):
        choreograph(catalog, _brief(), 1, PinFile(momentos=[Pin(seg=1.0, opcion="dragon")]))
    with pytest.raises(ValueError, match="person_7"):
        choreograph(catalog, _brief(), 1, PinFile(momentos=[Pin(seg=1.0, opcion="rodillas", persona="person_7")]))
    with pytest.raises(ValueError, match="fuera del video"):
        choreograph(catalog, _brief(), 1, PinFile(momentos=[Pin(seg=99.0, opcion="rodillas")]))


def test_a_choreography_exported_as_pins_comes_out_the_same(tmp_path: Path) -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/baile_duo.yaml")
    events = [_spot(p, f, k) for f in (0, 36, 72) for p, k in (("person_0", "legs"), ("person_1", "left_arm"))]
    _, original = choreograph(catalog, _brief(events), 5)
    path = tmp_path / "fijado.yaml"
    save_pins(pins_from_choreography(original), path)
    _, again = choreograph(catalog, _brief(events), 99, load_pins(path))

    def lit(choreo):
        return sorted((d.frame, d.target, d.choice.removesuffix(" (fijado)")) for d in choreo.decisions if not d.choice.startswith("nada"))

    assert lit(again) == lit(original)


def test_every_effect_of_the_duo_catalog_draws_where_it_is_pinned() -> None:
    """Cada opción, fijada sola en el cuadro 30 sobre una pareja que baila, dibuja algo."""
    catalog = load_catalog(ROOT / "configs/catalogs/baile_duo.yaml")
    frames = _frames()
    silent = []
    for reaction in catalog.reactions:
        for option in reaction.options:
            if not option.effects:
                continue
            pins = PinFile(solo_estos=True, momentos=[Pin(seg=1.0, accion=reaction.action, opcion=option.name, persona="person_1")])
            script, _ = choreograph(catalog, _brief(), 1, pins)
            engine = EffectEngine(script, EngineConfig(), events=[], fps=FPS)
            drawn = 0.0
            for i in range(20, 60):
                layers = engine.render_frame(frames[i], i, W, H, N)
                drawn = max([drawn, *(float(layer[..., 3].max()) for _, _, layer in layers)])
            if drawn < 0.05:
                silent.append(f"{reaction.action}:{option.name}")
    assert not silent, f"No dibujan nada al fijarlos: {silent}"
