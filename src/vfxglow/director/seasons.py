"""Temporadas (configs/seasons.yaml): la época dentro de los efectos que ya se disparan.

No hay decoración fija. Una temporada, sobre un catálogo:
- cambia la paleta;
- cambia las partículas de los efectos por objetos de la época (murciélagos, copos, corazones);
- cambia los sombreros de los accesorios de cabeza;
- el cierre se disipa en objetos de la época;
- añade momentos de temporada (season_fx) como una opción más de ciertas acciones, que compiten
  con las demás y respetan al protagonista y el tope de efectos;
- y hace salir más las opciones de `boost`.
`suggest(date)` dice qué temporada toca para que la interfaz la proponga.
"""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

BOOST_FACTOR = 2.5


class Moment(BaseModel):
    action: str
    moment: str
    weight: float = 0.5
    size: float = 1.5  # duración en segundos
    max_uses: int = 0  # veces por video (0 = sin tope): la cabeza de calabaza, una vez


class Season(BaseModel):
    id: str
    title: str
    emoji: str = ""
    months: list[int] = Field(default_factory=list)
    days: list[str] = Field(default_factory=list)  # ["MM-DD", "MM-DD"]
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    palette: list[tuple[float, float, float]] = Field(default_factory=list)
    particles: list[str] = Field(default_factory=list)
    hats: list[str] = Field(default_factory=list)
    closing: list[str] = Field(default_factory=list)
    moments: list[Moment] = Field(default_factory=list)
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


HEAD_HATS = {"cap", "cowboy_hat", "top_hat", "fedora", "party_hat", "headphones", "crown", "halo"}


def moment_effect(season: Season, moment: Moment) -> dict:
    return {
        "type": "season_fx",
        "target": {"kind": "joint", "id": "nose"},
        "style": {"shapes": [moment.moment], "colors": season.palette[:4] or [(1.0, 1.0, 1.0)], "size": moment.size, "thickness": 0.05, "hdr_gain": 1.6},
        "render": {"blend": "add", "motion_blur": 0.0, "persistence": 0.0, "group": "glow"},
        "trigger": {"hold": int(moment.size * 30), "fade_in": 3, "fade_out": 8},
    }


def _theme_effect(effect: dict, season: Season) -> dict:
    """Cambia en un efecto lo que la temporada reemplaza (partículas, sombreros, cierre)."""
    kind = effect.get("type")
    style = effect.setdefault("style", {})
    if kind == "droplets" and season.particles:
        style["shapes"] = list(season.particles)
    elif kind == "adornment" and season.hats:
        shapes = style.get("shapes", [])
        if any(shape in HEAD_HATS for shape in shapes):
            style["shapes"] = [s for s in shapes if s not in HEAD_HATS] + list(season.hats)
    elif kind in ("throw_fx", "pop_fx", "disco_fx") and season.particles:
        style["objects"] = list(season.particles)
    elif kind == "closing_stars" and season.closing:
        style["shapes"] = list(season.closing)
    return effect


def apply_to_catalog(catalog, season: Season):
    """Copia del catálogo con la época dentro de sus efectos (el original no se toca)."""
    from vfxglow.director.choreography import Option, Reaction

    out = catalog.model_copy(deep=True)
    defaults = copy.deepcopy(out.defaults)
    if season.palette:
        defaults.setdefault("style", {})["palette"] = [list(c) for c in season.palette]
        out.colors = [tuple(c) for c in season.palette[:2]]
    out.defaults = defaults
    out.always = [_theme_effect(copy.deepcopy(effect), season) for effect in out.always]
    boosted = set(season.boost)
    for reaction in out.reactions:
        for option in reaction.options:
            option.effects = [_theme_effect(copy.deepcopy(effect), season) for effect in option.effects]
            if option.name in boosted:
                option.weight *= BOOST_FACTOR
    # Partículas de temporada en los gestos rápidos, aunque el catálogo no tuviera.
    moments = list(season.moments)
    if season.particles:
        # El protagonista (o un gesto rápido) suelta objetos de la época al moverse deprisa.
        moments.append(Moment(action="fast_swing", moment="", weight=0.35))
        moments.append(Moment(action="spotlight", moment="", weight=0.3))
    for moment in moments:
        if moment.moment:
            # Neutro para los capítulos de elemento (no es fuego ni rayo).
            option = Option(name=f"temporada_{moment.moment}", weight=moment.weight, effects=[moment_effect(season, moment)], element="", max_uses=moment.max_uses)
        else:
            option = Option(
                name="temporada_particulas",
                weight=moment.weight,
                effects=[{
                    "type": "droplets",
                    "target": {"kind": "joint", "id": "left_wrist,right_wrist,left_ankle,right_ankle"},
                    "style": {"shapes": list(season.particles), "size": 0.5, "min_speed": 0.18, "chance": 0.5, "thickness": 0.01, "hdr_gain": 1.7},
                    "trigger": {"hold": 12, "fade_in": 1, "fade_out": 6},
                }],
            )
        reaction = next((r for r in out.reactions if r.action == moment.action), None)
        if reaction is None:
            out.reactions.append(Reaction(action=moment.action, options=[option, Option(name="nada", weight=max(1.0 - moment.weight, 0.1))]))
        else:
            reaction.options.append(option)
    out.tags = sorted(set(out.tags) | set(season.tags))
    return out


def preset_effects(season: Season) -> list[dict]:
    """Para un preset (sin coreógrafo): los momentos como efectos disparados por su acción, pocas
    veces y con enfriamiento."""
    out = []
    for index, moment in enumerate(season.moments):
        effect = moment_effect(season, moment)
        trigger = effect.pop("trigger")
        trigger.update(event=moment.action, cooldown=90, max_activations=3)
        out.append({"id": f"season_{season.id}_{index}", **effect, "triggers": [trigger]})
    return out
