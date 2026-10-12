"""Colores según el tono de piel y opciones que ceden el paso a otra acción cercana."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.choreography import Option, _yields, build_chapters
from vfxglow.director.palette import skin_scores

PALETTE = [(0.35, 1.0, 0.2), (1.0, 0.25, 0.85), (0.2, 1.0, 0.85), (1.0, 0.92, 0.15), (0.55, 0.35, 1.0)]
GREEN, MAGENTA, CYAN, YELLOW, VIOLET = range(5)


def test_light_skin_prefers_deep_colors_and_dark_skin_bright_ones() -> None:
    light = skin_scores(PALETTE, 0.3)
    assert light[MAGENTA] > light[YELLOW] and light[VIOLET] > light[CYAN]
    dark = skin_scores(PALETTE, 0.06)
    assert dark[YELLOW] > dark[VIOLET] and dark[GREEN] > dark[MAGENTA]
    assert (light > 0).all() and (dark > 0).all()  # ninguno queda fuera


def test_chapter_colors_follow_the_weights() -> None:
    events = [MotionEvent(name="spotlight", target="person_0", start_frame=i * 40, end_frame=i * 40 + 30, confidence=1.0, kind=k) for i, k in enumerate(["legs", "torso"] * 60)]
    weights = skin_scores(PALETTE, 0.3) ** 2
    chapters = build_chapters(events, PALETTE, seed=1, fps=30.0, frame_count=4800, weights=weights)
    mains = [PALETTE.index(tuple(c.colors[0])) for c in chapters]
    deep = sum(m in (MAGENTA, VIOLET) for m in mains) / len(mains)
    assert deep > 0.55


def test_option_yields_to_a_nearby_action_most_of_the_time() -> None:
    from vfxglow.analysis.schema import MotionBrief, VideoMeta

    meta = VideoMeta(path="v.mp4", fps=30.0, width=720, height=1280, frame_count=3000, duration_s=100.0)
    option = Option(name="cabeza", yields_to=["prop_worn"], yield_chance=0.75)
    worn = [MotionEvent(name="prop_worn", target="p:prop", start_frame=f + 20, end_frame=f + 35, confidence=1.0) for f in range(0, 3000, 100)]
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=worn, summary="")
    near = [_yields(option, MotionEvent(name="spotlight", target="p", start_frame=f, end_frame=f + 30, confidence=1.0), brief, 7, 30.0) for f in range(0, 3000, 100)]
    assert 0.55 < np.mean(near) < 0.95  # al azar: casi siempre cede, a veces no
    far = MotionEvent(name="spotlight", target="p", start_frame=70, end_frame=90, confidence=1.0)
    lonely = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=[worn[-1]], summary="")
    assert not _yields(option, far, lonely, 7, 30.0)


def test_best_choreography_is_at_least_as_good_as_the_catalog_seed_and_takes_differ() -> None:
    from pathlib import Path

    from vfxglow.analysis.schema import Beat, MotionBrief, VideoMeta
    from vfxglow.director.choreography import best_choreography, choreograph, load_catalog, score_choreography

    meta = VideoMeta(path="v.mp4", fps=30.0, width=720, height=1280, frame_count=900, duration_s=30.0)
    events = [
        MotionEvent(name=name, target=target, start_frame=f, end_frame=f + 20, confidence=1.0, kind=kind)
        for f, name, target, kind in [
            (30, "prop_transfer", "person_0:prop", "left_to_right"),
            (120, "prop_spin", "person_0:prop", ""),
            (250, "face_touch", "person_0:face", "right"),
            (330, "throw", "person_0:right_wrist", "right"),
            (400, "neck_slash", "person_0:face", "right"),
        ]
    ] + [MotionEvent(name="spotlight", target="person_0", start_frame=f, end_frame=f + 35, confidence=1.0, kind=k) for f, k in zip(range(0, 900, 36), ["legs", "torso", "left_arm", "right_arm", "head"] * 6)]
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="", beats=[Beat(id=0, start_frame=0, end_frame=899, kind="steady")])
    catalog = load_catalog(Path("configs/catalogs/baile_neon.yaml"))
    best, best_choreo = best_choreography(catalog, brief, take=0)
    _, plain = choreograph(catalog, brief)
    assert best_choreo.score >= score_choreography(plain, brief) - 1e-9
    _, second = best_choreography(catalog, brief, take=1)
    assert second.seed != best_choreo.seed and second.score <= best_choreo.score
    assert best_choreo.take == 0 and second.take == 1 and best_choreo.candidates > 1


def _catalog(options_spot, extra_reactions=()):
    from vfxglow.director.choreography import Catalog

    defaults = {"target": {"kind": "joint", "id": "body"}}
    return Catalog.model_validate({"name": "t", "defaults": defaults, "reactions": [{"action": "spotlight", "options": options_spot}, *extra_reactions]})


def _brief(events):
    from vfxglow.analysis.schema import MotionBrief, VideoMeta

    meta = VideoMeta(path="v.mp4", fps=30.0, width=720, height=1280, frame_count=600, duration_s=20.0)
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="")


def test_exclusive_scene_effects_never_stack_and_silence_the_rest() -> None:
    from vfxglow.director.choreography import choreograph

    scene = {"name": "escena", "weight": 1.0, "exclusive": True, "effects": [{"type": "disco_fx", "trigger": {"hold": 30}}]}
    reactions = [{"action": "frenzy", "options": [scene]}, {"action": "fast_swing", "options": [{"name": "estela", "weight": 1.0, "effects": [{"type": "swoosh", "target": {"kind": "joint", "id": "left_wrist"}}]}]}]
    events = [MotionEvent(name="frenzy", target="person_0", start_frame=f, end_frame=f + 30, confidence=1.0) for f in (0, 40)]
    events += [MotionEvent(name="fast_swing", target="person_0:left_wrist", start_frame=20, end_frame=25, confidence=1.0)]
    _, choreo = choreograph(_catalog([{"name": "nada", "weight": 1.0}], reactions), _brief(events))
    choices = {(d.action, d.frame): d.choice for d in choreo.decisions}
    assert choices[("frenzy", 0)] == "escena"
    assert choices[("frenzy", 40)].startswith("nada")  # otra escena mientras sigue la primera
    assert choices[("fast_swing", 20)].startswith("nada")  # el resto calla durante la escena


def test_at_most_three_foci_counting_key_moments() -> None:
    from vfxglow.director.choreography import choreograph

    glow = {"name": "glow", "weight": 1.0, "effects": [{"type": "body_glow", "trigger": {"hold": 30}}]}
    kiss = {"action": "face_touch", "options": [{"name": "beso", "weight": 1.0, "effects": [{"type": "face_toon", "trigger": {"hold": 30}}]}]}
    events = [MotionEvent(name="spotlight", target="person_0", start_frame=0, end_frame=40, confidence=1.0, kind=k) for k in ("left_arm", "right_arm", "head")]
    events += [MotionEvent(name="face_touch", target="person_0:face", start_frame=5, end_frame=40, confidence=1.0, kind="right")]
    _, choreo = choreograph(_catalog([glow], [kiss]), _brief(events))
    lit = [d for d in choreo.decisions if not d.choice.startswith("nada")]
    assert len(lit) == 3 and any(d.action == "face_touch" for d in lit)


def test_legs_and_torso_yield_to_face_moments() -> None:
    from vfxglow.director.choreography import choreograph

    glow = {"name": "glow", "weight": 1.0, "effects": [{"type": "body_glow", "trigger": {"hold": 10}}]}
    kiss = {"action": "face_touch", "options": [{"name": "beso", "weight": 1.0, "effects": [{"type": "face_toon", "trigger": {"hold": 10}}]}]}
    events = [MotionEvent(name="spotlight", target="person_0", start_frame=10, end_frame=30, confidence=1.0, kind=k) for k in ("legs", "right_arm")]
    events += [MotionEvent(name="face_touch", target="person_0:face", start_frame=5, end_frame=40, confidence=1.0, kind="right")]
    _, choreo = choreograph(_catalog([glow], [kiss]), _brief(events))
    lit = sorted((d.action, d.choice) for d in choreo.decisions if not d.choice.startswith("nada"))
    assert lit == [("face_touch", "beso"), ("spotlight", "glow")]  # el brazo sí, las piernas no
