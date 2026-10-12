"""Temporadas (configs/seasons.yaml): un estilo de época encima de cualquier catálogo o preset.

- `suggest(date)`: la temporada que toca en una fecha (los días exactos, si los tiene, ganan a
  los meses), para que la interfaz la proponga.
- `apply_to_catalog`: cambia la paleta del catálogo por la de la temporada, añade la decoración
  (season_fx) a lo que siempre está y hace salir más las opciones de `boost`.
- `decor_effect`: la decoración como efecto suelto (para los presets).
"""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

BOOST_FACTOR = 2.5


class Season(BaseModel):
    id: str
    title: str
    emoji: str = ""
    months: list[int] = Field(default_factory=list)
    days: list[str] = Field(default_factory=list)  # ["MM-DD", "MM-DD"]
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    palette: list[tuple[float, float, float]] = Field(default_factory=list)
    decor: list[str] = Field(default_factory=list)
    boost: list[str] = Field(default_factory=list)

    def active(self, date: dt.date) -> int:
        """0 = no toca; 2 = cae en sus días exactos; 1 = solo en su mes."""
        if self.days and len(self.days) == 2:
            today = date.strftime("%m-%d")
            start, end = self.days
            inside = start <= today <= end if start <= end else (today >= start or today <= end)
            if inside:
                return 2
        return 1 if date.month in self.months and not self.days else 0


def load_seasons(path: Path) -> list[Season]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Season.model_validate(item) for item in raw.get("seasons", [])]


def find(seasons: list[Season], season_id: str | None) -> Season | None:
    return next((s for s in seasons if s.id == season_id), None) if season_id else None


def suggest(seasons: list[Season], date: dt.date | None = None) -> Season | None:
    date = date or dt.date.today()
    ranked = sorted(((s.active(date), s) for s in seasons), key=lambda item: -item[0])
    return ranked[0][1] if ranked and ranked[0][0] > 0 else None


def decor_effect(season: Season) -> dict:
    return {
        "type": "season_fx",
        "target": {"kind": "joint", "id": "nose"},
        "style": {"shapes": season.decor, "colors": season.palette[:4] or [(1.0, 1.0, 1.0)], "thickness": 0.05, "hdr_gain": 1.5, "focus": False},
        "render": {"blend": "add", "motion_blur": 0.0, "persistence": 0.0, "group": "glow"},
    }


def apply_to_catalog(catalog, season: Season):
    """Copia del catálogo con la paleta, la decoración y los pesos de la temporada."""
    out = catalog.model_copy(deep=True)
    defaults = copy.deepcopy(out.defaults)
    if season.palette:
        defaults.setdefault("style", {})["palette"] = [list(c) for c in season.palette]
        out.colors = [tuple(c) for c in season.palette[:2]]
    out.defaults = defaults
    if season.decor:
        out.always = [*out.always, decor_effect(season)]
    boosted = set(season.boost)
    for reaction in out.reactions:
        for option in reaction.options:
            if option.name in boosted:
                option.weight *= BOOST_FACTOR
    out.tags = sorted(set(out.tags) | set(season.tags))
    return out
