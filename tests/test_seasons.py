"""Temporadas: sugerencia por fecha, aplicación sobre un catálogo y su decoración."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np

from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent, PersonPose
from vfxglow.config import EngineConfig
from vfxglow.director.choreography import load_catalog
from vfxglow.director.schema import Effect, EffectScript
from vfxglow.director.seasons import apply_to_catalog, find, load_seasons, suggest
from vfxglow.engine.engine import EffectEngine

SEASONS = load_seasons(Path("configs/seasons.yaml"))


def test_suggestion_follows_the_calendar() -> None:
    assert suggest(SEASONS, dt.date(2026, 10, 15)).id == "halloween"
    assert suggest(SEASONS, dt.date(2026, 11, 1)).id == "dia_de_muertos"
    assert suggest(SEASONS, dt.date(2026, 12, 30)).id == "ano_nuevo"
    assert suggest(SEASONS, dt.date(2026, 2, 10)).id == "san_valentin"
    assert suggest(SEASONS, dt.date(2026, 3, 5)) is None


def test_season_lives_inside_triggered_effects_not_as_a_frame() -> None:
    catalog = load_catalog(Path("configs/catalogs/baile.yaml"))
    halloween = find(SEASONS, "halloween")
    themed = apply_to_catalog(catalog, halloween)
    assert themed.defaults["style"]["palette"][0] == list(halloween.palette[0])
    # Nada siempre encendido de la temporada: solo como opciones de acciones.
    assert not any(effect.get("type") == "season_fx" for effect in themed.always)
    options = {(r.action, o.name): o for r in themed.reactions for o in r.options}
    assert ("still", "temporada_spider_drop") in options and ("frenzy", "temporada_bat_swarm") in options
    assert ("fast_swing", "temporada_particulas") in options
    hats = [e["style"]["shapes"] for r in themed.reactions for o in r.options for e in o.effects if e.get("type") == "adornment"]
    assert any("witch_hat" in shapes and "cowboy_hat" not in shapes for shapes in hats)
    closing = [e for e in themed.always if e.get("type") == "closing_stars"]
    assert closing and closing[0]["style"]["shapes"] == halloween.closing
    before = {o.name: o.weight for r in catalog.reactions for o in r.options}
    assert options[("spotlight", "rayos_x")].weight > before["rayos_x"]
    assert catalog.defaults["style"]["palette"] != themed.defaults["style"]["palette"]  # el original intacto


def test_every_season_moment_and_object_draws() -> None:
    from vfxglow.director.seasons import moment_effect
    from vfxglow.engine.season import MOMENTS, OBJECTS, object_outline

    for season in SEASONS:
        assert set(season.particles) <= set(OBJECTS) and set(season.closing) <= set(OBJECTS)
        for moment in season.moments:
            from vfxglow.engine.horror_masks import HORROR_MASKS

            assert moment.moment in MOMENTS or moment.moment in HORROR_MASKS
            raw = moment_effect(season, moment)
            trigger = raw.pop("trigger")
            effect = Effect.model_validate({"id": "m", **raw, "triggers": [{**trigger, "event": "still", "fade_in": 0}]})
            # El gesto de una mano (los murciélagos salen de ella, el zarpazo la sigue).
            event = MotionEvent(name="still", target="person_0:right_wrist", start_frame=0, end_frame=40, confidence=1.0)
            engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[event])
            pose = [Landmark(name=n, x=x, y=y, c=0.9) for n, (x, y) in {
                "nose": (0.5, 0.3), "left_eye": (0.53, 0.28), "right_eye": (0.47, 0.28), "left_ear": (0.56, 0.29), "right_ear": (0.44, 0.29),
                "right_wrist": (0.35, 0.45), "left_shoulder": (0.42, 0.4), "right_shoulder": (0.58, 0.4), "left_hip": (0.45, 0.6), "right_hip": (0.55, 0.6), "left_ankle": (0.45, 0.9), "right_ankle": (0.55, 0.9),
            }.items()]
            drawn = 0.0
            for i in range(30):
                # Con la persona en `people`, como sale del análisis (los adornos dibujan sobre el dueño del evento).
                record = FrameRecord(frame=i, time_s=i / 30, pose=pose, people=[PersonPose(person_id="person_0", pose=pose)])
                layer = engine.render_frame(record, i, 360, 640, 60)[0][2]
                drawn = max(drawn, float(layer[..., 3].max()))
            assert drawn > 0.3, (season.id, moment.moment)
    for name in OBJECTS:
        assert object_outline(name, np.array([100.0, 100.0]), 10.0)
