"""Catálogos de un solo elemento (fuego, agua, rayo, tierra, viento), sacados de avatar.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vfxglow.analysis.schema import MotionBrief, MotionEvent, VideoMeta
from vfxglow.director.choreography import choreograph, load_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "configs" / "catalogs"
# nombre del catálogo → elemento de avatar.yaml que se queda
ELEMENTS = {"fuego": "fuego", "agua": "agua", "rayo": "rayo", "tierra": "tierra", "viento": "aire"}


def _brief() -> MotionBrief:
    meta = VideoMeta(path="x", fps=30.0, width=720, height=1280, frame_count=900, duration_s=30.0)
    names = ["fast_swing", "throw", "point", "finger_gun", "jump", "landing", "stomp", "spin_body", "flip", "arms_up", "lunge", "raise_hand", "impact"]
    events = [MotionEvent(name=names[i % len(names)], target="person_0", start_frame=30 * i, end_frame=30 * i + 4, confidence=1.0) for i in range(1, 29)]
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="")


@pytest.mark.parametrize("name,element", ELEMENTS.items())
def test_each_catalog_only_has_options_of_its_element(name: str, element: str) -> None:
    catalog = load_catalog(CATALOGS / f"{name}.yaml")
    assert catalog.name == name and catalog.element == element and catalog.title and catalog.description and catalog.tags
    assert catalog.element_mix == {} and catalog.always == []  # sin capítulos ni la luz del fuego en el agua
    options = [option for reaction in catalog.reactions for option in reaction.options]
    assert options and {option.element for option in options} == {element}


@pytest.mark.parametrize("name", ELEMENTS)
def test_each_catalog_draws_effects_for_a_busy_video(name: str) -> None:
    catalog = load_catalog(CATALOGS / f"{name}.yaml")
    script, log = choreograph(catalog, _brief(), seed=3)
    assert script.effects, f"{name}: no dibujó nada"
    assert any(not decision.choice.startswith("nada") for decision in log.decisions)


def test_avatar_keeps_all_its_elements_and_the_base_is_not_changed_by_extending() -> None:
    avatar = load_catalog(CATALOGS / "avatar.yaml")
    assert set(avatar.element_mix) == {"fuego", "rayo", "aire", "agua", "tierra"} and avatar.always
    raw = yaml.safe_load((CATALOGS / "avatar.yaml").read_text(encoding="utf-8"))
    total = sum(len(reaction["options"]) for reaction in raw["reactions"])
    assert sum(len(reaction.options) for reaction in avatar.reactions) == total


def test_extends_needs_the_element_to_keep(tmp_path: Path) -> None:
    (tmp_path / "base.yaml").write_text(yaml.safe_dump({"name": "base", "element": "fuego", "reactions": [{"action": "fast_swing", "options": [{"name": "x", "weight": 1.0}]}]}), encoding="utf-8")
    (tmp_path / "hijo.yaml").write_text("name: hijo\nextends: base\n", encoding="utf-8")
    with pytest.raises(ValueError, match="only_element"):
        load_catalog(tmp_path / "hijo.yaml")
    (tmp_path / "hijo.yaml").write_text("name: hijo\nextends: base\nonly_element: agua\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no tiene opciones"):
        load_catalog(tmp_path / "hijo.yaml")


def test_every_catalog_has_a_short_subtitle_for_its_card() -> None:
    for path in sorted(CATALOGS.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        catalog = load_catalog(path)
        assert 0 < len(catalog.subtitle) <= 28, f"{path.name}: subtítulo de {len(catalog.subtitle)} letras"
