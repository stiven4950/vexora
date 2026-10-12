"""Temporadas: sugerencia por fecha, aplicación sobre un catálogo y su decoración."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np

from vfxglow.analysis.schema import FrameRecord, Landmark
from vfxglow.config import EngineConfig
from vfxglow.director.choreography import load_catalog
from vfxglow.director.schema import Effect, EffectScript
from vfxglow.director.seasons import apply_to_catalog, decor_effect, find, load_seasons, suggest
from vfxglow.engine.season import SHAPES
from vfxglow.engine.engine import EffectEngine

SEASONS = load_seasons(Path("configs/seasons.yaml"))


def test_suggestion_follows_the_calendar() -> None:
    assert suggest(SEASONS, dt.date(2026, 10, 15)).id == "halloween"
    assert suggest(SEASONS, dt.date(2026, 11, 1)).id == "dia_de_muertos"
    assert suggest(SEASONS, dt.date(2026, 12, 30)).id == "ano_nuevo"
    assert suggest(SEASONS, dt.date(2026, 2, 10)).id == "san_valentin"
    assert suggest(SEASONS, dt.date(2026, 3, 5)) is None


def test_season_changes_palette_adds_decor_and_boosts() -> None:
    catalog = load_catalog(Path("configs/catalogs/baile_neon.yaml"))
    halloween = find(SEASONS, "halloween")
    themed = apply_to_catalog(catalog, halloween)
    assert themed.defaults["style"]["palette"][0] == list(halloween.palette[0])
    assert any(effect.get("type") == "season_fx" for effect in themed.always)
    before = {o.name: o.weight for r in catalog.reactions for o in r.options}
    after = {o.name: o.weight for r in themed.reactions for o in r.options}
    assert after["rayos_x"] > before["rayos_x"] and "halloween" in themed.tags
    assert catalog.defaults["style"]["palette"] != themed.defaults["style"]["palette"]  # el original intacto


def test_every_season_decoration_draws() -> None:
    for season in SEASONS:
        assert set(season.decor) <= set(SHAPES)
        effect = Effect.model_validate({"id": "d", **decor_effect(season)})
        engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[])
        record = FrameRecord(frame=0, time_s=0.0, pose=[Landmark(name="nose", x=0.5, y=0.3, c=0.9)])
        layer = None
        for i in range(30):
            layer = engine.render_frame(record.model_copy(update={"frame": i}), i, 360, 640, 60)[0][2]
        assert layer[..., 3].max() > 0.3, season.id
