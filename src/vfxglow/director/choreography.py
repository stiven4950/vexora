"""Coreógrafo: decide, ocurrencia por ocurrencia, qué reacción visual dispara cada acción.

Un catálogo (configs/catalogs/<nombre>.yaml) asocia cada acción detectada en el análisis
(`body_bump`, `fast_swing`, `person_contact`, `fist_clash`...) con reacciones posibles y su
peso, incluida "nada". Cada vez que la acción ocurre se sortea una reacción con una semilla
derivada de la del catálogo, la acción y el fotograma: el mismo video da siempre el mismo
resultado, y otra semilla da otra coreografía.

El resultado es un Effect Script normal. Cada efecto de una reacción lleva un trigger con la
lista de fotogramas en los que esa reacción salió elegida (`EffectTrigger.frames`), así que el
motor no sabe nada de azar. Las decisiones se devuelven también como registro legible.
"""

from __future__ import annotations

import copy
import zlib
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from vfxglow.analysis.schema import MotionBrief, MotionEvent
from vfxglow.director.schema import EffectScript, resolve_timing


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Option(_Strict):
    name: str
    weight: float = 1.0
    # La acción debe venir de una persona identificada (person_N:...). Un rayo de los ojos
    # necesita saber quién dispara y hacia quién.
    requires_person: bool = False
    # Fotogramas mínimos entre dos usos de esta opción: un recurso dramático (un rayo) pierde
    # fuerza si se repite seguido. En enfriamiento se vuelve a sortear entre las demás.
    cooldown: int = 0
    # Si no está vacío, la opción solo entra en el sorteo cuando la acción es de una de estas
    # extremidades (un brazo musculoso no tiene sentido en una patada).
    limbs: list[str] = Field(default_factory=list)
    # Subtipos de la acción admitidos (MotionEvent.kind; p. ej. intent: hand_to_chest).
    kinds: list[str] = Field(default_factory=list)
    # La persona de la acción debe llevar uno de estos accesorios (gafas, máscara...). Si la
    # acción no es de una persona (una pausa), el efecto se dibuja en todos los que lo lleven.
    accessories: list[str] = Field(default_factory=list)
    effects: list[dict] = Field(default_factory=list)


class Reaction(_Strict):
    action: str
    # Fotogramas mínimos entre dos reacciones (no "nada") a la misma acción.
    cooldown: int = 0
    options: list[Option]


class Catalog(_Strict):
    name: str
    title: str = ""
    # Una línea para mostrar al elegir estilo (interfaz web).
    description: str = ""
    seed: int = 1
    colors: list[tuple[float, float, float]] = Field(default_factory=lambda: [(1.0, 0.55, 0.12), (0.18, 0.5, 1.0)])
    # Plantilla común de los efectos; cada efecto del catálogo solo escribe lo que cambia.
    defaults: dict = Field(default_factory=dict)
    # Efectos que no dependen de una elección (por ejemplo, partículas con su propia probabilidad).
    always: list[dict] = Field(default_factory=list)
    reactions: list[Reaction]
    # Lo que el análisis debe calcular para este catálogo (p. ej. [blades] para espadas).
    needs: list[str] = Field(default_factory=list)
    # Con needs: [props], el objeto protagonista que se sigue (en inglés, terminado en punto).
    prop: str = "a baseball cap. a hat."


class Decision(_Strict):
    frame: int
    second: float
    action: str
    target: str
    choice: str


class Choreography(_Strict):
    catalog: str
    seed: int
    decisions: list[Decision]


def load_catalog(path: Path) -> Catalog:
    return Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def choreograph(catalog: Catalog, brief: MotionBrief, seed: int | None = None) -> tuple[EffectScript, Choreography]:
    seed = catalog.seed if seed is None else seed
    fps = brief.video.fps or 30.0
    chosen: dict[tuple[str, str], list[tuple[int, str]]] = {}
    decisions: list[Decision] = []
    for reaction in catalog.reactions:
        last = -10_000
        used: dict[str, int] = {}
        for event in sorted((e for e in brief.events if e.name == reaction.action), key=lambda e: e.start_frame):
            resting = {name for name, frame in used.items() if event.start_frame - frame < _option(reaction, name).cooldown}
            option = _draw(reaction, event, seed, resting, brief)
            if option.effects and event.start_frame - last < reaction.cooldown:
                option = Option(name="nada (enfriamiento)")
            if option.effects:
                last = event.start_frame
                used[option.name] = event.start_frame
                chosen.setdefault((reaction.action, option.name), []).append((event.start_frame, event.target))
            decisions.append(
                Decision(
                    frame=event.start_frame,
                    second=round(event.start_frame / fps, 2),
                    action=reaction.action,
                    target=event.target,
                    choice=option.name,
                )
            )
    effects: list[dict] = [_effect(catalog, raw, f"always_{index}") for index, raw in enumerate(catalog.always)]
    for reaction in catalog.reactions:
        for option in reaction.options:
            picked = sorted(chosen.get((reaction.action, option.name), []))
            if not picked:
                continue
            for index, raw in enumerate(option.effects):
                effect = _effect(catalog, raw, f"{reaction.action}_{option.name}_{index}")
                trigger = dict(raw.get("trigger", {}))
                trigger.update(event=reaction.action, frames=[f for f, _t in picked], targets=[t for _f, t in picked])
                effect["triggers"] = [trigger]
                if option.accessories:
                    effect["style"]["people"] = sorted(
                        {a.person for a in brief.accessories if a.kind in option.accessories}
                    )
                effects.append(effect)
    script = EffectScript.model_validate(
        {"title": catalog.title or catalog.name, "theme": catalog.name, "seed": seed, "effects": effects}
    )
    decisions.sort(key=lambda d: (d.frame, d.action))
    return resolve_timing(script, brief.video.frame_count), Choreography(catalog=catalog.name, seed=seed, decisions=decisions)


def _option(reaction: Reaction, name: str) -> Option:
    return next(option for option in reaction.options if option.name == name)


def _wears(brief: MotionBrief | None, event: MotionEvent, kinds: list[str]) -> bool:
    """La persona del evento (o cualquiera, si el evento no es de una persona) lleva algo de `kinds`."""
    if brief is None:
        return False
    person = event.attacker or (event.target.split(":", 1)[0] if event.target.startswith("person_") else None)
    return any(
        a.kind in kinds and a.start_frame <= event.start_frame <= a.end_frame and (person is None or a.person == person)
        for a in brief.accessories
    )


def _draw(reaction: Reaction, event: MotionEvent, seed: int, resting: set[str] = frozenset(), brief: MotionBrief | None = None) -> Option:
    limb = event.target.rsplit(":", 1)[-1]
    options = [
        o
        for o in reaction.options
        if not (o.requires_person and not event.target.startswith("person_"))
        and (not o.limbs or limb in o.limbs)
        and (not o.kinds or event.kind in o.kinds)
        and (not o.accessories or _wears(brief, event, o.accessories))
        and o.name not in resting
    ]
    if not options:
        return Option(name="nada")
    weights = np.array([max(o.weight, 0.0) for o in options], dtype=np.float64)
    if weights.sum() <= 0:
        return Option(name="nada")
    rng = np.random.default_rng(zlib.crc32(f"{seed}:{reaction.action}:{event.start_frame}:{event.target}".encode()) & 0xFFFFFFFF)
    return options[int(rng.choice(len(options), p=weights / weights.sum()))]


def _effect(catalog: Catalog, raw: dict, effect_id: str) -> dict:
    effect = copy.deepcopy(catalog.defaults)
    for key, value in raw.items():
        if key == "trigger":
            continue
        if isinstance(value, dict) and isinstance(effect.get(key), dict):
            effect[key] = {**effect[key], **value}
        else:
            effect[key] = copy.deepcopy(value)
    effect["id"] = effect_id
    style = effect.setdefault("style", {})
    style.setdefault("colors", [list(color) for color in catalog.colors])
    return effect
