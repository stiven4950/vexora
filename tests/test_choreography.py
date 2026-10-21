"""Coreógrafo: sorteo determinista de reacciones por ocurrencia."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from vfxglow.analysis.schema import MotionBrief, MotionEvent, VideoMeta
from vfxglow.director.choreography import Catalog, choreograph, load_catalog
from vfxglow.director.schema import Effect, EffectTarget, EffectTrigger
from vfxglow.director.validator import validate_script
from vfxglow.engine.timeline import ActivationTimeline

ROOT = Path(__file__).resolve().parents[1]


def _brief(events: list[MotionEvent]) -> MotionBrief:
    meta = VideoMeta(path="x", fps=30.0, width=100, height=100, frame_count=900, duration_s=30.0)
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="")


def _swing(frame: int, target: str = "person_1:right_wrist") -> MotionEvent:
    return MotionEvent(name="fast_swing", target=target, start_frame=frame, end_frame=frame + 2, confidence=1.0)


def _catalog(**option_extra) -> Catalog:
    return Catalog.model_validate(
        {
            "name": "t",
            "seed": 3,
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {
                    "action": "fast_swing",
                    "options": [
                        {"name": "swoosh", "weight": 1.0, "effects": [{"trigger": {"hold": 4}}], **option_extra},
                        {"name": "nada", "weight": 1.0},
                    ],
                }
            ],
        }
    )


def test_same_seed_same_choreography_other_seed_differs() -> None:
    brief = _brief([_swing(f) for f in range(0, 800, 20)])
    catalog = _catalog()
    first = choreograph(catalog, brief)[1].decisions
    again = choreograph(catalog, brief)[1].decisions
    other = choreograph(catalog, brief, seed=99)[1].decisions
    assert [d.choice for d in first] == [d.choice for d in again]
    assert [d.choice for d in first] != [d.choice for d in other]
    assert set(Counter(d.choice for d in first)) == {"swoosh", "nada"}


def test_chosen_frames_reach_the_trigger_and_only_they_fire() -> None:
    events = [_swing(f) for f in range(0, 400, 20)]
    script, log = choreograph(_catalog(), _brief(events))
    chosen = [d.frame for d in log.decisions if d.choice == "swoosh"]
    trigger = script.effects[0].triggers[0]
    assert trigger.frames == chosen and trigger.hold == 4
    windows = ActivationTimeline(script.effects[0], events).windows
    assert [w.start for w in windows] == chosen


def test_limbs_and_cooldown_restrict_the_draw() -> None:
    kicks = [_swing(f, "person_1:left_ankle") for f in range(0, 200, 20)]
    _, log = choreograph(_catalog(limbs=["right_wrist"]), _brief(kicks))
    assert {d.choice for d in log.decisions} == {"nada"}
    _, log = choreograph(_catalog(cooldown=100), _brief([_swing(f) for f in range(0, 400, 10)]))
    used = [d.frame for d in log.decisions if d.choice == "swoosh"]
    assert all(b - a >= 100 for a, b in zip(used, used[1:]))


def test_trigger_frames_filter_events() -> None:
    effect = Effect(id="e", type="stars", target=EffectTarget(kind="event_point", id="contact"),
                    triggers=[EffectTrigger(event="fast_swing", frames=[40])])
    windows = ActivationTimeline(effect, [_swing(20), _swing(40), _swing(60)]).windows
    assert [w.start for w in windows] == [40]


def test_fight_catalog_is_valid() -> None:
    catalog = load_catalog(ROOT / "configs" / "catalogs" / "pelea.yaml")
    events = [_swing(f) for f in range(0, 600, 15)] + [
        MotionEvent(name="person_contact", target="person_1:left_wrist", start_frame=100, end_frame=100, confidence=1.0, position=(0.5, 0.5)),
        MotionEvent(name="fist_clash", target="person_0:right_wrist", start_frame=200, end_frame=200, confidence=1.0, position=(0.5, 0.5)),
        MotionEvent(name="body_bump", target="body", start_frame=30, end_frame=30, confidence=1.0, position=(0.5, 0.5)),
    ]
    script, _ = choreograph(catalog, _brief(events))
    validate_script(script, max_effects=40)


def test_kind_and_accessory_filters_and_same_frame_targets() -> None:
    from vfxglow.analysis.schema import Accessory

    catalog = Catalog.model_validate(
        {
            "name": "t",
            "defaults": {"type": "intent_mark", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {
                    "action": "intent",
                    "options": [
                        {"name": "pecho", "kinds": ["hand_to_chest"], "effects": [{"style": {"shapes": ["rune"]}}]},
                        {"name": "gafas", "accessories": ["sunglasses"], "effects": [{"type": "eyewear", "style": {"shapes": ["stars"]}}]},
                    ],
                }
            ],
        }
    )
    intents = [
        MotionEvent(name="intent", target="person_0:right_wrist", start_frame=10, end_frame=12, confidence=1.0, attacker="person_0", kind="stir"),
        MotionEvent(name="intent", target="person_1:left_wrist", start_frame=10, end_frame=12, confidence=1.0, attacker="person_1", kind="hand_to_chest"),
    ]
    brief = _brief(intents).model_copy(update={"accessories": [Accessory(person="person_0", kind="sunglasses", start_frame=0, end_frame=899)]})
    script, log = choreograph(catalog, brief)
    choices = {d.target: d.choice for d in log.decisions}
    # person_0 se agita y lleva gafas: solo puede salir "gafas"; person_1 sin gafas lleva la mano al pecho.
    assert choices == {"person_0:right_wrist": "gafas", "person_1:left_wrist": "pecho"}
    by_id = {e.id: e for e in script.effects}
    assert by_id["intent_gafas_0"].style.people == ["person_0"]
    pecho = by_id["intent_pecho_0"]
    # Mismo fotograma, otra persona: el trigger distingue por target.
    assert [w.event.target for w in ActivationTimeline(pecho, intents).windows] == ["person_1:left_wrist"]


def test_include_adds_shared_options_with_scaled_weight(tmp_path: Path) -> None:
    (tmp_path / "_comun.yaml").write_text(
        "reactions:\n"
        "- action: fast_swing\n  options:\n  - {name: rayo, weight: 0.4, effects: [{trigger: {hold: 2}}]}\n"
        "- action: stomp\n  options:\n  - {name: chispa, weight: 1.0}\n"
    )
    (tmp_path / "solo.yaml").write_text(
        "name: solo\ninclude: [{name: _comun, weight: 0.5}]\n"
        "defaults: {type: swoosh, target: {kind: joint, id: right_wrist}}\n"
        "reactions:\n- action: fast_swing\n  options:\n  - {name: swoosh, weight: 1.0}\n"
    )
    catalog = load_catalog(tmp_path / "solo.yaml")
    swing = next(r for r in catalog.reactions if r.action == "fast_swing")
    assert [(o.name, o.weight) for o in swing.options] == [("swoosh", 1.0), ("rayo", 0.2)]
    assert any(r.action == "stomp" for r in catalog.reactions)


def test_include_rejects_repeated_option_names(tmp_path: Path) -> None:
    import pytest

    (tmp_path / "_comun.yaml").write_text("reactions:\n- action: fast_swing\n  options:\n  - {name: swoosh}\n")
    (tmp_path / "solo.yaml").write_text(
        "name: solo\ninclude: [_comun]\nreactions:\n- action: fast_swing\n  options:\n  - {name: swoosh}\n"
    )
    with pytest.raises(ValueError, match="swoosh"):
        load_catalog(tmp_path / "solo.yaml")


def test_one_dance_style_for_solo_and_pair() -> None:
    from vfxglow.config import catalog_file

    names = lambda c: {o.name for r in c.reactions for o in r.options}  # noqa: E731
    dance = load_catalog(ROOT / "configs/catalogs/baile.yaml")
    for effect in ("cinta", "alma", "aro_orbita", "cresta_punk", "discos", "notas", "brazo", "sombrero_cinturon", "aureola"):
        assert effect in names(dance)
    assert dance.duet and dance.chapters
    # Los nombres de antes siguen llevando al mismo catálogo.
    config = ROOT / "configs/default.yaml"
    assert catalog_file(config, "baile_duo") == catalog_file(config, "baile_neon") == catalog_file(config, "baile")


def test_pair_gets_one_color_per_person_and_solo_gets_color_chapters() -> None:
    from vfxglow.analysis.schema import DuetSpan

    dance = load_catalog(ROOT / "configs/catalogs/baile.yaml")
    spot = MotionEvent(name="spotlight", target="person_0", start_frame=30, end_frame=60, confidence=1.0, kind="legs")
    solo_script, _ = choreograph(dance, _brief([spot]), 3)
    assert solo_script.chapters
    pair = _brief([spot]).model_copy(update={"duet": [DuetSpan(start_frame=0, end_frame=899, mode="unison", leader="person_0", partner="person_1")]})
    pair_script, _ = choreograph(dance, pair, 3)
    assert not pair_script.chapters
    assert all(e.style.by_person and not e.style.palette and e.style.colors[:2] == [tuple(c) for c in dance.colors] for e in pair_script.effects)


def test_options_for_strong_or_long_moves_only() -> None:
    catalog = Catalog.model_validate(
        {
            "name": "t",
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {"action": "fast_swing", "options": [{"name": "fuerte", "min_speed": 0.4, "effects": [{"trigger": {"hold": 4}}]}]},
                {"action": "frenzy", "options": [{"name": "furia", "min_duration_s": 1.0, "effects": [{"trigger": {"hold": 4}}]}]},
            ],
        }
    )
    events = [
        MotionEvent(name="fast_swing", target="person_0:right_wrist", start_frame=10, end_frame=12, confidence=1.0, peak_speed=0.2),
        MotionEvent(name="fast_swing", target="person_0:right_wrist", start_frame=100, end_frame=102, confidence=1.0, peak_speed=0.5),
        MotionEvent(name="frenzy", target="person_0", start_frame=200, end_frame=215, confidence=1.0),
        MotionEvent(name="frenzy", target="person_0", start_frame=400, end_frame=440, confidence=1.0),
    ]
    _, choreo = choreograph(catalog, _brief(events), 1)
    lit = {(d.action, d.frame) for d in choreo.decisions if not d.choice.startswith("nada")}
    assert lit == {("fast_swing", 100), ("frenzy", 400)}


def test_no_stretch_of_the_video_without_an_effect() -> None:
    import numpy as np

    catalog = Catalog.model_validate(
        {
            "name": "t",
            "max_gap_s": 1.0,
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [{"action": "spotlight", "options": [{"name": "brillo", "effects": [{"trigger": {"hold": 10}}]}, {"name": "nada", "weight": 50}]}],
        }
    )
    spots = [MotionEvent(name="spotlight", target="person_0", start_frame=f, end_frame=f + 30, confidence=1.0, kind="legs") for f in range(0, 870, 36)]
    _, choreo = choreograph(catalog, _brief(spots), 1)
    covered = np.zeros(901, dtype=bool)
    for d in choreo.decisions:
        if not d.choice.startswith("nada"):
            covered[d.frame : d.until + 1] = True
    run = longest = 0
    for lit in covered[:900]:
        run = 0 if lit else run + 1
        longest = max(longest, run)
    assert longest <= 30


def test_garments_follow_the_wardrobe_each_person_chose() -> None:
    from vfxglow.director.choreography import Option, wardrobe_allows

    jacket, dress = Option(name="chaqueta", wardrobe="chaqueta"), Option(name="vestido", wardrobe="vestido")
    plain = Option(name="collar")
    choice = {"person_0": "chaqueta", "person_1": "vestido"}
    assert wardrobe_allows(jacket, "person_0", choice) and not wardrobe_allows(jacket, "person_1", choice)
    assert wardrobe_allows(dress, "person_1", choice) and not wardrobe_allows(dress, "person_0", choice)
    # Sin elegir, ninguna prenda; "ambos", las dos; lo que no es prenda sale siempre.
    assert not wardrobe_allows(jacket, "person_0", {}) and not wardrobe_allows(dress, "person_0", {})
    assert wardrobe_allows(jacket, "person_0", {"*": "ambos"}) and wardrobe_allows(dress, "person_0", {"*": "ambos"})
    assert wardrobe_allows(plain, "person_0", {})


def test_max_uses_caps_an_option_for_the_whole_video() -> None:
    brief = _brief([_swing(f) for f in range(0, 800, 20)])
    log = choreograph(_catalog(max_uses=1), brief)[1]
    assert Counter(d.choice for d in log.decisions)["swoosh"] == 1  # el ave de fuego: una vez por video


def test_always_chance_is_a_fixed_draw_per_video() -> None:
    from vfxglow.director.choreography import always_effects

    catalog = Catalog.model_validate(
        {
            "name": "t",
            "defaults": {"type": "adornment", "target": {"kind": "joint", "id": "nose"}},
            "always": [{"chance": 0.4, "style": {"shapes": ["fire_wall"]}}],
            "reactions": [],
        }
    )
    picks = [bool(always_effects(catalog, [], frames, 30.0, 18)) for frames in range(300, 700)]
    assert 0.25 < sum(picks) / len(picks) < 0.55  # de vez en cuando
    assert picks == [bool(always_effects(catalog, [], frames, 30.0, 18)) for frames in range(300, 700)]  # fijo
    assert "chance" not in always_effects(Catalog.model_validate({**catalog.model_dump(), "always": [{"chance": 1.0}]}), [], 300, 30.0, 18)[0]


def test_element_chapters_do_not_mix_fire_and_lightning() -> None:
    catalog = Catalog.model_validate(
        {
            "name": "t",
            "seed": 3,
            "element": "fuego",
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {
                    "action": "fast_swing",
                    "options": [
                        {"name": "latigo", "weight": 1.0, "effects": [{"trigger": {"hold": 30}}]},
                        {"name": "rayo", "element": "rayo", "weight": 1.0, "effects": [{"trigger": {"hold": 30}}]},
                    ],
                }
            ],
        }
    )
    bursts = [f for start in range(0, 800, 120) for f in range(start, start + 40, 10)]  # golpes en ráfagas
    log = choreograph(catalog, _brief([_swing(f) for f in bursts]))[1]
    picks = [(d.frame, d.choice) for d in log.decisions if d.choice in ("latigo", "rayo")]
    assert {c for _f, c in picks} == {"latigo", "rayo"}  # salen los dos elementos...
    for (f1, c1), (f2, c2) in zip(picks, picks[1:]):
        if c1 != c2:
            assert f2 - f1 >= 30 + 24  # ...pero nunca encimados: el anterior termina y pasan 0,8 s


def _chain_catalog() -> Catalog:
    return Catalog.model_validate(
        {
            "name": "t",
            "seed": 3,
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {"action": "flip", "options": [{"name": "estelas", "weight": 1.0, "effects": [{"trigger": {"hold": 4}}]}]},
                {
                    "action": "landing",
                    "options": [
                        {"name": "desbarate", "weight": 0.5, "follows": [{"after": "flip:estelas", "within_s": 1.0, "boost": 10}],
                         "requires_follow": True, "effects": [{"trigger": {"hold": 4}}]},
                        {"name": "piso", "weight": 0.5, "effects": [{"trigger": {"hold": 4}}]},
                    ],
                },
            ],
        }
    )


def _ev(name: str, frame: int, target: str = "person_0") -> MotionEvent:
    return MotionEvent(name=name, target=target, start_frame=frame, end_frame=frame + 3, confidence=1.0)


def test_a_consequence_follows_its_cause_and_never_comes_alone() -> None:
    catalog = _chain_catalog()
    after = Counter()
    alone = Counter()
    for seed in range(40):
        log = choreograph(catalog, _brief([_ev("flip", 100), _ev("landing", 115)]), seed)[1]
        after[next(d.choice for d in log.decisions if d.action == "landing")] += 1
        log = choreograph(catalog, _brief([_ev("landing", 115)]), seed)[1]
        alone[next(d.choice for d in log.decisions if d.action == "landing")] += 1
    assert after["desbarate"] >= 32  # tras la voltereta, casi siempre (10:1 contra el golpe de piso)
    assert alone["desbarate"] == 0  # sin la voltereta, nunca


def test_an_option_that_earns_needs_the_strike_that_uses_it() -> None:
    catalog = Catalog.model_validate(
        {
            "name": "t",
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {"action": "throw", "options": [{"name": "fenix", "weight": 1.0, "effects": [{"trigger": {"hold": 4}}],
                                                 "earns": {"actions": ["fast_swing"], "within_s": [0.5, 2.0]}}]},
            ],
        }
    )
    used = choreograph(catalog, _brief([_ev("throw", 100, "person_0:right_wrist"), _ev("fast_swing", 130, "person_0:right_wrist")]))[1]
    unused = choreograph(catalog, _brief([_ev("throw", 100, "person_0:right_wrist"), _ev("fast_swing", 130, "person_0:left_wrist")]))[1]
    assert any(d.choice == "fenix" for d in used.decisions)  # el golpe con la misma mano la usa
    assert not any(d.choice == "fenix" for d in unused.decisions)  # sin golpe de esa mano, no sale


def test_a_group_limit_caps_options_across_actions() -> None:
    catalog = Catalog.model_validate(
        {
            "name": "t",
            "group_limits": {"bestia": 2},
            "defaults": {"type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"}},
            "reactions": [
                {"action": action, "options": [{"name": f"b_{action}", "group": "bestia", "weight": 1.0, "effects": [{"trigger": {"hold": 2}}]}]}
                for action in ("throw", "lunge", "spin_body", "fast_swing")
            ],
        }
    )
    events = [_ev(a, 100 + 60 * i) for i, a in enumerate(("throw", "lunge", "spin_body", "fast_swing"))]
    log = choreograph(catalog, _brief(events))[1]
    assert sum(d.choice.startswith("b_") for d in log.decisions) == 2  # dos bestias por video, no cuatro
