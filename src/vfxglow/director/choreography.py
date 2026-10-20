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

from vfxglow.analysis.duet import duet_at
from vfxglow.analysis.schema import MotionBrief, MotionEvent
from vfxglow.director.palette import skin_luma, skin_scores
from vfxglow.director.schema import Chapter, EffectScript, resolve_timing


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Option(_Strict):
    name: str
    weight: float = 1.0
    # Cede el paso: si cerca (yield_window_s) hay una de estas acciones, con probabilidad
    # yield_chance la opción no sale (un accesorio de cabeza no tapa la gorra recién puesta).
    # Al azar, para que a veces sí coincidan.
    yields_to: list[str] = Field(default_factory=list)
    # Efecto de escena o disfraz (discoteca, bola de espejos, sombrero y cinturón, rayos X...): no
    # se enciende sobre otro exclusivo ni sobre un momento clave, y mientras dura cede el resto.
    exclusive: bool = False
    yield_chance: float = 0.75
    yield_window_s: float = 1.5
    # La acción debe venir de una persona identificada (person_N:...). Un rayo de los ojos
    # necesita saber quién dispara y hacia quién.
    requires_person: bool = False
    # Fotogramas mínimos entre dos usos de esta opción: un recurso dramático (un rayo) pierde
    # fuerza si se repite seguido. En enfriamiento se vuelve a sortear entre las demás.
    cooldown: int = 0
    # Si no está vacío, la opción solo entra en el sorteo cuando la acción es de una de estas
    # extremidades (un brazo musculoso no tiene sentido en una patada).
    limbs: list[str] = Field(default_factory=list)
    # Veces que la opción puede salir en todo el video (0 = sin tope). Cuenta por nombre: la misma
    # opción en varias acciones (el ave al levantar la mano o los brazos) comparte el tope.
    max_uses: int = 0
    # Elemento de la opción (fuego, rayo...). Sin dar, el del catálogo; "" = neutra (la mirada, las
    # chispas). Con capítulos de elemento, no se mezclan elementos en el mismo tramo.
    element: str | None = None
    # Subtipos de la acción admitidos (MotionEvent.kind; p. ej. intent: hand_to_chest).
    kinds: list[str] = Field(default_factory=list)
    # La persona de la acción debe llevar uno de estos accesorios (gafas, máscara...). Si la
    # acción no es de una persona (una pausa), el efecto se dibuja en todos los que lo lleven.
    accessories: list[str] = Field(default_factory=list)
    # Solo con movimiento fuerte o largo: velocidad pico mínima del evento (fracción del cuadro
    # por fotograma) y duración mínima (s). Así un estilo toma efectos de otro (de pelea en un
    # baile) solo cuando el movimiento lo pide.
    min_speed: float = 0.0
    min_duration_s: float = 0.0
    # Prenda de cuerpo entero ("chaqueta", "vestido"): solo sale en las personas cuyo vestuario
    # (Catalog.wardrobe, que elige el usuario) la permite.
    wardrobe: str = ""
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
    # Capítulos de elemento (glowing/video_51): el elemento de las opciones que no dicen el suyo
    # ("" = sin capítulos). Mientras un elemento está encendido, y `element_pad_s` antes y
    # después, no sale otro (nada de rayo cian en medio del fuego).
    element: str = ""
    element_pad_s: float = 0.8
    # Reparto del video en capítulos de un elemento (glowing/video_51): peso de cada elemento
    # ({fuego: 1, rayo: 0.35, aire: 0.35}); vacío = sin reparto (solo el bloqueo de arriba). El
    # primero y el último son del elemento del catálogo; los gestos del tramo inclinan la elección
    # (lanzar y señalar, rayo; girar, saltar y voltear, aire).
    element_mix: dict[str, float] = Field(default_factory=dict)
    element_chapter_s: float = 3.5
    reactions: list[Reaction]
    # Lo que el análisis debe calcular para este catálogo (p. ej. [blades] para espadas).
    needs: list[str] = Field(default_factory=list)
    # Con needs: [props], el objeto protagonista que se sigue (en inglés, terminado en punto).
    prop: str = "a baseball cap. a hat."
    # Color por capítulo: el color solo cambia cuando cambia el foco (otra parte del cuerpo
    # encendida, el objeto protagonista entra o llega a la cabeza). Sin esto, cada efecto sortea
    # su color por activación.
    chapters: bool = False
    # Etiquetas para buscar el estilo (las temporadas añaden las suyas).
    tags: list[str] = Field(default_factory=list)
    # Nada compite con el protagonista: los efectos se apagan fuera del foco de la línea de
    # atención del análisis (engine/focus.py).
    attention: bool = False
    chapter_min_s: float = 0.8
    # Ningún tramo sin efecto: un hueco más largo que esto (s) se rellena con un efecto del foco de
    # ese momento (0 = no se rellena). Ver fill_gaps.
    max_gap_s: float = 0.0
    # Acciones que se reparten primero los lugares (antes que el resto, en todo el video), sin
    # saltarse el tope de focos: en avatar, los golpes y saltos ganan a las pisadas.
    priority: list[str] = Field(default_factory=list)
    # Vestuario por persona, que elige el usuario: {"person_0": "vestido", "*": "chaqueta"}.
    # Valores: chaqueta, vestido, ambos, ninguno. Sin dato para una persona, "*"; sin "*", ninguno.
    wardrobe: dict[str, str] = Field(default_factory=dict)
    # Pareja (analysis/duet.py): al unísono, el efecto elegido para uno se copia al otro (cada
    # uno con su color); en un solo, solo se enciende quien lleva el turno.
    duet: bool = False


class Decision(_Strict):
    frame: int
    second: float
    action: str
    target: str
    choice: str
    # Último fotograma en que su efecto sigue encendido (para contar efectos simultáneos).
    until: int = -1
    # La intención del gesto, cuando el momento viene del análisis profundo.
    note: str = ""


class Choreography(_Strict):
    catalog: str
    seed: int
    decisions: list[Decision]
    # Elección automática (best_choreography): puesto en el ranking (0 = la mejor), puntuación y
    # cuántas candidatas se probaron. Con semilla explícita, take = -1.
    take: int = -1
    score: float = 0.0
    candidates: int = 1


def load_catalog(path: Path) -> Catalog:
    """Lee un catálogo y le suma sus `include`: fragmentos (`configs/catalogs/_<nombre>.yaml`, solo
    con `reactions`) cuyas opciones se agregan a las de la misma acción, con el peso multiplicado
    por el `weight` del include (1 si se da solo el nombre). Una acción que el catálogo no tiene se
    agrega entera. Dos opciones con el mismo nombre en la misma acción son un error."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for item in raw.pop("include", None) or []:
        name, scale = (item, 1.0) if isinstance(item, str) else (item["name"], float(item.get("weight", 1.0)))
        fragment = yaml.safe_load((path.parent / f"{name}.yaml").read_text(encoding="utf-8")) or {}
        for extra in fragment.get("reactions", []):
            options = [{**option, "weight": float(option.get("weight", 1.0)) * scale} for option in extra.get("options", [])]
            reaction = next((r for r in raw["reactions"] if r["action"] == extra["action"]), None)
            if reaction is None:
                raw["reactions"].append({**extra, "options": options})
                continue
            names = {option["name"] for option in reaction["options"]}
            clash = names & {option["name"] for option in options}
            if clash:
                raise ValueError(f"{path.name}: {name} repite opciones de {extra['action']}: {', '.join(sorted(clash))}")
            reaction["options"] += options
    return Catalog.model_validate(raw)


def choreograph(catalog: Catalog, brief: MotionBrief, seed: int | None = None, pins=None) -> tuple[EffectScript, Choreography]:
    """`pins` (director/pins.py, PinFile): momentos fijados a mano que van antes que todo y no
    ceden ante ninguna regla; con `solo_estos`, no hay sorteo."""
    seed = catalog.seed if seed is None else seed
    fps = brief.video.fps or 30.0
    chosen: dict[tuple[str, str], list[tuple[int, str]]] = {}
    decisions: list[Decision] = []
    events = list(brief.events)
    # Golpes de la música como eventos (beat_pulse, ecualizador).
    extra: list[MotionEvent] = [
        MotionEvent(name="beat", target="music", start_frame=int(f), end_frame=int(f), confidence=1.0, detail="Golpe de la música.")
        for f in brief.audio_onsets
    ]
    events += extra
    if catalog.attention and brief.attention:
        # Lo que se enciende por "la parte que más se mueve" sale de la línea de atención, para
        # que coincida con lo que el motor deja ver (engine/focus.py).
        spots = attention_spotlights(brief.attention, fps)
        events = [e for e in events if e.name != "spotlight"] + spots
        extra += spots
    # Dos pasadas: primero los momentos clave (gestos, objeto, beso), que siempre mandan; después
    # el resto en orden de tiempo, para que una opción exclusiva (un efecto de escena) no se
    # encienda encima de otra ni encima de un momento clave, y mientras dure los efectos de
    # protagonista y de ambiente cedan.
    state = {id(reaction): {"last": -10_000, "used": {}} for reaction in catalog.reactions}
    key_windows: list[tuple[int, int]] = []
    face_windows: list[tuple[int, int]] = []
    # Ventanas encendidas que no son momentos clave ni ambiente. Un efecto nuevo cuenta estas
    # (al empezar) y los momentos clave que se crucen con su ventana: como mucho MAX_TOGETHER.
    lit: list[tuple[int, int]] = []
    exclusive_until = -1
    duet = brief.duet if catalog.duet else []
    mirrored: dict[tuple[str, str], list[tuple[int, str]]] = {}
    # Último fotograma de un efecto copiado en cada persona (por grupo: el movimiento, o cada
    # gesto): mientras dura, esa persona no enciende otro (lleva el mismo momento que su pareja).
    busy: dict[tuple[str, str], int] = {}
    forced: dict[tuple[int, int], tuple[Option, object]] = {}
    pinned_out: list[tuple[Reaction, Option, list[tuple[int, str]], object]] = []
    pinned: list[tuple[MotionEvent, Reaction]] = []
    if pins is not None:
        from vfxglow.director.pins import resolve_pins

        for event, reaction, option, pin, made in resolve_pins(pins, catalog, events, brief, fps):
            if made:
                events.append(event)
                extra.append(event)
            forced[(id(event), id(reaction))] = (option, pin)
            pinned.append((event, reaction))
    passes = [
        [(e, r) for r in catalog.reactions if r.action in KEY_ACTIONS for e in events if e.name == r.action],
        [(e, r) for r in catalog.reactions if r.action not in KEY_ACTIONS and r.action in catalog.priority for e in events if e.name == r.action],
        [(e, r) for r in catalog.reactions if r.action not in KEY_ACTIONS and r.action not in catalog.priority for e in events if e.name == r.action],
    ]
    if pins is not None:
        rest = [] if pins.solo_estos else [[pair for pair in pairs if (id(pair[0]), id(pair[1])) not in forced] for pairs in passes]
        passes = [pinned, *rest]
    spent: dict[str, int] = {}  # usos de cada opción en el video (para max_uses)
    plan = element_plan(catalog, events, brief.video.frame_count, fps, seed)
    elements: list[tuple[int, int, str]] = []  # tramos encendidos de cada elemento (capítulos)
    pad = int(round(catalog.element_pad_s * fps))
    closings = {"fire_wall", "fire_carpet_end"}
    if catalog.element and any(closings & set(raw.get("style", {}).get("shapes", [])) for raw in catalog.always):
        # El cierre de fuego en el piso (pared o alfombra) ocupa el tramo final: es de fuego, así
        # que el rayo no sale ahí (se veía un rayo cian sobre la alfombra).
        from vfxglow.engine.firebend import closing_frames

        total = brief.video.frame_count
        elements.append((total - closing_frames(total, fps), total, catalog.element))
    for pairs in passes:
        for event, reaction in sorted(pairs, key=lambda pair: (pair[0].start_frame, catalog.reactions.index(pair[1]))):
            memo = state[id(reaction)]
            fixed = forced.get((id(event), id(reaction)))
            if fixed is not None:
                # Fijado a mano: sin sorteo ni cesiones.
                option, pin = fixed
                start, end = _window(option, event)
                person = _person(event)
                span = duet_at(duet, event.start_frame) if person else None
                group = "motion" if reaction.action in TURN_ACTIONS else reaction.action
                # Cada momento fijado es su propio efecto: dos que coinciden (la entrada de cada
                # uno, el pie de los dos) se dibujan a la vez.
                pinned_out.append((reaction, option, [(event.start_frame, event.target)], pin))
                memo["last"] = event.start_frame
                memo["used"][option.name] = event.start_frame
                spent[option.name] = spent.get(option.name, 0) + 1
                if element_of(catalog, option):
                    elements.append((start, end, element_of(catalog, option)))
                if option.exclusive:
                    exclusive_until = max(exclusive_until, end)
                if reaction.action in KEY_ACTIONS:
                    key_windows.append((start, end))
                if reaction.action in FACE_ACTIONS:
                    face_windows.append((start, end))
                if reaction.action not in AMBIENT_ACTIONS and reaction.action not in KEY_ACTIONS:
                    lit.append((start, end))
                whole_scene = all(raw.get("type") in SCENE_TYPES for raw in option.effects)
                partner = _partner(person, span, brief)
                mirror = pin.espejo if pin.espejo is not None else (span is not None and span.mode == "unison")
                # Exacto: la pareja recibe la misma copia (mismo instante y duración).
                twin = _twin(event, person, partner, [] if pin.exacto else events, fps, True) if mirror and partner and not whole_scene else None
                if twin is not None:
                    if twin not in events:
                        extra.append(twin)
                    pinned_out.append((reaction, option, [(twin.start_frame, twin.target)], pin))
                    busy[(partner, group)] = max(busy.get((partner, group), -1), end)
                    decisions.append(
                        Decision(frame=twin.start_frame, second=round(twin.start_frame / fps, 2), action=reaction.action, target=twin.target, choice=f"{option.name} (espejo)", until=end)
                    )
                decisions.append(
                    Decision(frame=event.start_frame, second=round(event.start_frame / fps, 2), action=reaction.action, target=event.target, choice=f"{option.name} (fijado)", until=end, note=pin.nota or "")
                )
                continue
            resting = {name for name, frame in memo["used"].items() if event.start_frame - frame < _option(reaction, name).cooldown}
            resting |= {o.name for o in reaction.options if o.max_uses and spent.get(o.name, 0) >= o.max_uses}
            resting |= other_elements(catalog, reaction.options, elements, event, pad)
            chapter = chapter_element(plan, event.start_frame)
            if chapter:  # solo el elemento del capítulo (y lo neutro)
                resting |= {o.name for o in reaction.options if element_of(catalog, o) and element_of(catalog, o) != chapter}
            option = _draw(reaction, event, seed, resting, brief, catalog.wardrobe)
            if option.yields_to and _yields(option, event, brief, seed, fps):
                option = Option(name=f"nada (cede a {', '.join(option.yields_to)})")
            if option.effects and event.start_frame - memo["last"] < reaction.cooldown:
                option = Option(name="nada (enfriamiento)")
            start, end = _window(option, event)
            if option.effects and option.exclusive:
                # Un efecto de escena cede ante otro y ante los momentos de cara (no ante el objeto,
                # que puede estar en juego mucho tiempo).
                if start <= exclusive_until or any(fs <= end and start <= fe for fs, fe in face_windows):
                    option = Option(name="nada (cede: ya hay un efecto de escena o un momento clave)")
            elif option.effects and reaction.action in YIELD_TO_EXCLUSIVE and start <= exclusive_until and not _earned(option):
                option = Option(name="nada (cede al efecto de escena)")
            elif (
                option.effects
                and reaction.action == "spotlight"
                and event.kind in BODY_KINDS
                and any(fs <= end and start <= fe for fs, fe in face_windows)
            ):
                option = Option(name="nada (cede a la cara)")
            person = _person(event) if duet else None
            span = duet_at(duet, event.start_frame) if person else None
            group = "motion" if reaction.action in TURN_ACTIONS else reaction.action
            if option.effects and span is not None:
                if start <= busy.get((person, group), -1):
                    option = Option(name="nada (lleva el mismo momento que su pareja)")
                elif event.name == "spotlight" and event.confidence < 1.0:
                    # En pareja, un foco por persona: el segundo foco duplicaría lo encendido.
                    option = Option(name="nada (un foco por persona)")
                elif span.mode == "solo" and person != span.leader and reaction.action in TURN_ACTIONS:
                    option = Option(name="nada (turno de la pareja)")
            if (
                option.effects
                and reaction.action not in KEY_ACTIONS
                and reaction.action not in AMBIENT_ACTIONS
                and not _earned(option)
                and sum(1 for ls, le in lit if ls <= start <= le) + sum(1 for ks, ke in key_windows if ks <= end and start <= ke) >= MAX_TOGETHER
            ):
                option = Option(name="nada (ya hay dos focos encendidos)")
            if option.effects:
                memo["last"] = event.start_frame
                memo["used"][option.name] = event.start_frame
                spent[option.name] = spent.get(option.name, 0) + 1
                if element_of(catalog, option):
                    elements.append((start, end, element_of(catalog, option)))
                chosen.setdefault((reaction.action, option.name), []).append((event.start_frame, event.target))
                if option.exclusive:
                    exclusive_until = end
                if reaction.action in KEY_ACTIONS:
                    key_windows.append((start, end))
                if reaction.action in FACE_ACTIONS:
                    face_windows.append((start, end))
                if reaction.action not in AMBIENT_ACTIONS and reaction.action not in KEY_ACTIONS:
                    lit.append((start, end))
                partner = _partner(person, span, brief)
                whole_scene = all(raw.get("type") in SCENE_TYPES for raw in option.effects)
                twin = (
                    _twin(event, person, partner, events, fps, reaction.action in MIRROR_ALWAYS)
                    if span is not None and span.mode == "unison" and not whole_scene
                    else None
                )
                twin_option = option
                if twin is not None and not wardrobe_allows(option, partner, catalog.wardrobe):
                    # La pareja lleva otro vestuario: su propia prenda (vestido en vez de chaqueta).
                    twin_option = next((o for o in reaction.options if o.wardrobe and o.effects and wardrobe_allows(o, partner, catalog.wardrobe)), None)
                    if twin_option is None:
                        twin = None
                if twin is not None:
                    if twin not in events:
                        extra.append(twin)
                    mirrored.setdefault((reaction.action, twin_option.name), []).append((twin.start_frame, twin.target))
                    busy[(partner, group)] = max(busy.get((partner, group), -1), end)
                    decisions.append(
                        Decision(
                            frame=twin.start_frame,
                            second=round(twin.start_frame / fps, 2),
                            action=reaction.action,
                            target=twin.target,
                            choice=f"{twin_option.name} (espejo)",
                            until=end,
                        )
                    )
            decisions.append(
                Decision(
                    frame=event.start_frame,
                    second=round(event.start_frame / fps, 2),
                    action=reaction.action,
                    target=event.target,
                    choice=option.name,
                    until=end if option.effects else event.start_frame,
                )
            )
    if catalog.max_gap_s > 0 and not (pins is not None and pins.solo_estos):
        fill_gaps(catalog, brief, events, extra, chosen, decisions, seed, fps, elements, plan)
    always = [] if pins is not None and pins.solo_estos else always_effects(catalog, events, brief.video.frame_count, fps, seed)
    effects: list[dict] = list(always)
    for number, (reaction, option, picked, pin) in enumerate(pinned_out):
        for index, raw in enumerate(option.effects):
            effect = _effect(catalog, raw, f"{reaction.action}_{option.name}_{index}_fijado_{number}")
            if pin.figura and pin.figura in effect["style"].get("shapes", []):
                effect["style"]["shapes"] = [pin.figura]
            # Lo fijado se ve aunque la línea de atención mire a otro lado, lo que dura su momento
            # (`dur`), sin la retención ni el enfriamiento del catálogo.
            effect["style"]["focus"] = False
            trigger = dict(raw.get("trigger", {}))
            trigger.update(event=reaction.action, frames=[f for f, _t in picked], targets=[t for _f, t in picked], hold=0, cooldown=0)
            effect["triggers"] = [trigger]
            effects.append(effect)
    for reaction in catalog.reactions:
        for option in reaction.options:
            name = option.name
            tag = ""
            picked = sorted(chosen.get((reaction.action, name), []))
            for index, raw in enumerate(option.effects if picked else []):
                effect = _effect(catalog, raw, f"{reaction.action}_{option.name}_{index}{tag}")
                trigger = dict(raw.get("trigger", {}))
                trigger.update(event=reaction.action, frames=[f for f, _t in picked], targets=[t for _f, t in picked])
                effect["triggers"] = [trigger]
                if option.accessories:
                    effect["style"]["people"] = sorted(
                        {a.person for a in brief.accessories if a.kind in option.accessories}
                    )
                effects.append(effect)
            twins = sorted(mirrored.get((reaction.action, name), []))
            for index, raw in enumerate(option.effects if twins else []):
                # La copia para la pareja: su propio efecto (su estela, su estado) en sus fotogramas.
                effect = _effect(catalog, raw, f"{reaction.action}_{option.name}_{index}{tag}_pareja")
                trigger = dict(raw.get("trigger", {}))
                trigger.update(event=reaction.action, frames=[f for f, _t in twins], targets=[t for _f, t in twins])
                effect["triggers"] = [trigger]
                effects.append(effect)
    pair = bool(duet)
    if pair:
        # Pareja: cada persona con su color fijo (catalog.colors), sin el sorteo de la paleta ni
        # los capítulos de color del solista.
        for effect in effects:
            effect["style"].pop("palette", None)
            effect["style"]["colors"] = [list(color) for color in catalog.colors]
            effect["style"].setdefault("by_person", True)
    script = EffectScript.model_validate(
        {"title": catalog.title or catalog.name, "theme": catalog.name, "seed": seed, "effects": effects}
    )
    script.extra_events = extra
    if catalog.attention:
        script.attention = list(brief.attention)
    luma = skin_luma(brief)
    if luma is not None:
        # Colores que contrastan con esta piel salen más seguido (ninguno queda fuera).
        for effect in script.effects:
            if effect.style.palette:
                effect.style.palette_weights = [round(float(w), 4) for w in skin_scores(effect.style.palette, luma) ** 2]
    if catalog.chapters and not pair:
        palette = catalog.defaults.get("style", {}).get("palette") or catalog.colors
        weights = skin_scores(palette, luma) ** 2 if luma is not None else None
        script.chapters = build_chapters(events, palette, seed, fps, brief.video.frame_count, catalog.chapter_min_s, weights)
    if pins is not None and not pair:
        acts = pin_chapters(pins, fps, brief.video.frame_count)
        if acts:
            script.chapters = acts
    decisions.sort(key=lambda d: (d.frame, d.action))
    return resolve_timing(script, brief.video.frame_count), Choreography(catalog=catalog.name, seed=seed, decisions=decisions)


def _partner(person: str | None, span, brief: MotionBrief) -> str | None:
    """La pareja: la del tramo de dúo o, sin él, la otra persona del video."""
    if span is not None:
        return span.partner if person == span.leader else span.leader
    others = [p for p in brief.people if p != person]
    return others[0] if person and others else None


def _earned(option: Option) -> bool:
    """La opción exige movimiento fuerte o largo: ese movimiento manda, no cede ante el tope de
    focos ni ante un efecto de escena ya encendido (sí ante otro exclusivo y la cara)."""
    return option.min_speed > 0 or option.min_duration_s > 0


ELEMENT_CUES = {
    "rayo": ("throw", "point", "finger_gun", "arms_open"),
    "aire": ("spin_body", "jump", "flip"),
}


def element_plan(catalog: Catalog, events: list[MotionEvent], total: int, fps: float, seed: int) -> list[tuple[int, int, str]]:
    """Capítulos de elemento: [(inicio, fin, elemento)] que cubren el video. Cortes cada
    `element_chapter_s` aproximadamente, corridos a la pausa más cercana si la hay. Nunca dos
    capítulos seguidos de otro elemento que el del catálogo."""
    if not catalog.element_mix or total <= 0:
        return []
    length = max(int(catalog.element_chapter_s * fps), 1)
    count = max(int(round(total / length)), 1)
    pauses = sorted(e.start_frame for e in events if e.name in ("lull", "still"))
    cuts = [0]
    for k in range(1, count):
        guess = int(k * total / count)
        near = [p for p in pauses if abs(p - guess) <= fps and p > cuts[-1] + fps]
        cuts.append(min(near, key=lambda p: abs(p - guess)) if near else guess)
    cuts.append(total)
    rng = np.random.default_rng(zlib.crc32(f"{seed}:elements:{total}".encode()) & 0xFFFFFFFF)
    plan = []
    for k, (a, b) in enumerate(zip(cuts, cuts[1:])):
        previous = plan[-1][2] if plan else ""
        if k == 0 or k == len(cuts) - 2 or previous != catalog.element:
            # Abre y cierra el elemento del catálogo, y vuelve a él después de cada capítulo de
            # otro elemento (el fuego es el protagonista: fuego, rayo, fuego, aire, fuego...).
            plan.append((a, b - 1, catalog.element))
            continue
        names = list(catalog.element_mix)
        scores = []
        for name in names:
            cues = sum(1 for e in events if e.name in ELEMENT_CUES.get(name, ()) and a <= e.start_frame < b)
            scores.append(catalog.element_mix[name] * (1.0 + 2.0 * cues))
        weights = np.array(scores) / sum(scores)
        plan.append((a, b - 1, names[int(rng.choice(len(names), p=weights))]))
    return plan


def chapter_element(plan: list[tuple[int, int, str]], frame: int) -> str:
    return next((el for s, e, el in plan if s <= frame <= e), "")


def element_of(catalog: Catalog, option: Option) -> str:
    return catalog.element if option.element is None else option.element


def other_elements(catalog: Catalog, options: list[Option], elements: list[tuple[int, int, str]], event: MotionEvent, pad: int) -> set[str]:
    """Las opciones cuyo tramo (con `pad` de margen) se encima con uno de otro elemento ya
    encendido (capítulos de elemento)."""
    out = set()
    for o in options:
        mine = element_of(catalog, o)
        if not mine or not o.effects:
            continue
        start, end = _window(o, event)
        if any(el != mine and s - pad <= end and start <= e + pad for s, e, el in elements):
            out.add(o.name)
    return out


def fill_gaps(catalog: Catalog, brief: MotionBrief, events, extra, chosen, decisions, seed: int, fps: float, elements: list | None = None, plan: list | None = None) -> None:
    """Rellena los tramos sin ningún efecto más largos que `catalog.max_gap_s`: en cada hueco, un
    efecto del foco de ese momento (un `spotlight`), sorteado entre las opciones que dibujan algo y
    no son de escena. Si en el hueco no hay foco, se crea uno con la región de la línea de
    atención (o el cuerpo entero). Se repite hasta que no queden huecos o no haya qué poner."""
    spot = next((r for r in catalog.reactions if r.action == "spotlight"), None)
    if spot is None:
        return
    total = brief.video.frame_count
    longest = int(round(catalog.max_gap_s * fps))
    covered = np.zeros(total + 1, dtype=bool)
    for d in decisions:
        if not d.choice.startswith("nada") and d.action not in AMBIENT_ACTIONS and d.until >= d.frame:
            covered[max(d.frame, 0) : min(d.until, total) + 1] = True
    people = brief.people or [brief.person_id]
    for attempt in range(200):
        gap = _first_gap(covered, longest)
        if gap is None:
            return
        start, end = gap
        # Un foco que empiece justo al abrirse el hueco (si empieza más tarde, el tramo de antes
        # quedaría vacío): si no lo hay, se crea uno ahí mismo.
        candidates = [e for e in events if e.name == "spotlight" and start <= e.start_frame <= start + 3]
        event = min(candidates, key=lambda e: (e.start_frame, -e.confidence)) if candidates else None
        if event is None:
            region = next((a.primary for a in brief.attention if a.start_frame <= start <= a.end_frame and a.primary != "prop"), "")
            event = MotionEvent(name="spotlight", target=people[attempt % len(people)], start_frame=start, end_frame=min(start + int(fps), total - 1),
                                confidence=1.0, detail="Relleno: ningún tramo sin efecto.", kind=region)
            events.append(event)
            extra.append(event)
        blocked = other_elements(catalog, spot.options, elements or [], event, int(round(catalog.element_pad_s * fps)))
        chapter = chapter_element(plan or [], event.start_frame)
        if chapter:
            blocked |= {o.name for o in spot.options if element_of(catalog, o) and element_of(catalog, o) != chapter}
        pool = Reaction(action="spotlight", options=[o for o in spot.options if o.effects and not o.exclusive and o.name not in blocked])
        option = _draw(pool, event, seed + 7919 * (attempt + 1), frozenset(), brief, catalog.wardrobe)
        if not option.effects:
            # Sin opción para esa región: el cuerpo entero sí admite casi todas.
            option = _draw(pool, event.model_copy(update={"kind": ""}), seed + 7919 * (attempt + 1), frozenset(), brief, catalog.wardrobe)
        if not option.effects:
            covered[start : end + 1] = True  # nada que poner aquí: no insistir
            continue
        first, last = _window(option, event)
        if elements is not None and element_of(catalog, option):
            elements.append((first, last, element_of(catalog, option)))
        chosen.setdefault(("spotlight", option.name), []).append((event.start_frame, event.target))
        decisions.append(
            Decision(frame=event.start_frame, second=round(event.start_frame / fps, 2), action="spotlight", target=event.target, choice=option.name, until=last)
        )
        covered[max(first, 0) : min(last, total) + 1] = True


def _first_gap(covered: np.ndarray, longest: int) -> tuple[int, int] | None:
    run = 0
    for index, lit in enumerate(covered):
        run = 0 if lit else run + 1
        if run > longest:
            begin = index - run + 1
            stop = begin
            while stop + 1 < len(covered) and not covered[stop + 1]:
                stop += 1
            return begin, stop
    return None


def _person(event: MotionEvent) -> str | None:
    if event.attacker:
        return event.attacker
    return event.target.split(":", 1)[0] if event.target.startswith("person_") else None


# Un gesto de la pareja a menos de esto cuenta como el mismo momento (no van sincronizados al cuadro).
TWIN_S = 0.4


def _twin(event: MotionEvent, person: str, partner: str, events: list[MotionEvent], fps: float, copy_if_missing: bool) -> MotionEvent | None:
    """El mismo momento en la pareja: su propio evento si hizo lo mismo (mismo gesto y misma parte)
    casi a la vez; si no y `copy_if_missing`, una copia del evento en su cuerpo, sin posición (cada
    efecto la toma de sus articulaciones)."""
    window = TWIN_S * fps
    same = [
        e for e in events
        if e.name == event.name and _person(e) == partner and e.kind == event.kind and abs(e.start_frame - event.start_frame) <= window
    ]
    if same:
        return min(same, key=lambda e: abs(e.start_frame - event.start_frame))
    if not copy_if_missing:
        return None
    # Un objetivo sin persona (la nariz de la entrada) se le pone a la pareja: si no, el motor
    # no distingue la copia del original.
    target = f"{partner}{event.target[len(person):]}" if event.target.startswith(person) else f"{partner}:{event.target}"
    return event.model_copy(
        update={
            "target": target,
            "attacker": partner if event.attacker == person else event.attacker,
            "position": None,
            "detail": f"Espejo de {person} (bailan al unísono).",
        }
    )


# Spotlight desde la atención: trozos de esta duración, y regiones que no son una parte del
# cuerpo (el objeto tiene sus propias reacciones).
SPOT_CHUNK_S = 1.2


def attention_spotlights(spans, fps: float) -> list[MotionEvent]:
    """Un `spotlight` por trozo de tramo de atención (primer foco y segundo), con kind = región."""
    chunk = max(int(SPOT_CHUNK_S * fps), 1)
    out: list[MotionEvent] = []
    for span in spans:
        for region in (span.primary, span.secondary):
            if region is None or region == "prop":
                continue
            length = span.end_frame - span.start_frame + 1
            pieces = max(1, round(length / chunk))
            bounds = np.linspace(span.start_frame, span.end_frame + 1, pieces + 1).astype(int)
            for start, stop in zip(bounds[:-1], bounds[1:]):
                out.append(
                    MotionEvent(
                        name="spotlight",
                        target=span.person,
                        start_frame=int(start),
                        end_frame=int(stop) - 1,
                        confidence=1.0 if region == span.primary else 0.7,
                        detail="Protagonista según la línea de atención.",
                        kind=region,
                    )
                )
    return out


# Eventos que cambian el foco y cómo se nombra ese foco.
FOCUS_EVENTS = {
    "spotlight": lambda e: f"{e.target.split(':')[0]}:{e.kind}",
    "prop_transfer": lambda e: "prop",
    "prop_worn": lambda e: "prop_worn",
}
# El traspaso se ve antes del evento (el resorte aparece antes de soltar): su foco se adelanta.
FOCUS_LEAD_S = {"prop_transfer": 0.35}


def pin_chapters(pins, fps: float, frame_count: int) -> list[Chapter]:
    """Capítulos de color de los momentos fijados con `color`: cada uno manda desde su segundo
    hasta el siguiente con color (el primero, desde el inicio). Sin colores, ninguno."""
    from vfxglow.director.pins import hex_color

    marks = sorted(
        (int(round(pin.seg * fps)), color) for pin in pins.momentos if (color := hex_color(pin.color)) is not None
    )
    chapters: list[Chapter] = []
    for k, (frame, color) in enumerate(marks):
        start = 0 if k == 0 else frame
        stop = marks[k + 1][0] if k + 1 < len(marks) else frame_count
        if stop <= start:
            continue
        accent = marks[k + 1][1] if k + 1 < len(marks) else color
        chapters.append(Chapter(start_frame=start, end_frame=stop - 1, focus="guion", colors=[color, accent]))
    return chapters


def build_chapters(events: list[MotionEvent], palette, seed: int, fps: float, frame_count: int, min_s: float = 0.8, weights=None) -> list[Chapter]:
    """Capítulos de foco estable con dos colores cada uno (principal y acento).

    Un capítulo nuevo empieza cuando un evento de foco nombra otro foco. Un capítulo dura al
    menos `min_s`: un foco que llega antes se ignora, salvo que sea del objeto protagonista,
    que se queda con el capítulo (llegar a la cabeza pesa más que un brazo que se mueve). Dos
    capítulos seguidos nunca repiten color principal. `weights` (uno por color) hace que unos
    colores salgan más que otros (los que contrastan con la piel, ver director/palette.py).
    """
    shortest = min_s * fps
    marks: list[tuple[int, str]] = []
    for event in sorted((e for e in events if e.name in FOCUS_EVENTS), key=lambda e: e.start_frame):
        focus = FOCUS_EVENTS[event.name](event)
        start = max(event.start_frame - int(round(FOCUS_LEAD_S.get(event.name, 0.0) * fps)), 0)
        if not marks and start < shortest:
            start = 0
        if marks and marks[-1][1] == focus:
            continue
        if marks and start - marks[-1][0] < shortest:
            if event.name.startswith("prop_") and not marks[-1][1].startswith("prop"):
                marks[-1] = (marks[-1][0], focus)
                if len(marks) > 1 and marks[-2][1] == focus:
                    marks.pop()  # sigue el mismo capítulo del objeto
            continue
        marks.append((start, focus))
    if not marks or marks[0][0] > 0:
        marks.insert(0, (0, "inicio"))
    end = max(frame_count, marks[-1][0] + 1)
    spans = [(start, nxt, focus) for (start, focus), nxt in zip(marks, [m[0] for m in marks[1:]] + [end])]
    rng = np.random.default_rng(seed * 7919 + 17)
    colors = [tuple(float(v) for v in c) for c in palette]
    chapters: list[Chapter] = []
    previous = -1
    weight = np.ones(len(colors)) if weights is None else np.asarray(weights, dtype=np.float64)

    def pick(choices: list[int]) -> int:
        w = weight[choices]
        return int(rng.choice(choices, p=w / w.sum())) if w.sum() > 0 else int(rng.choice(choices))

    for start, stop, focus in spans:
        main = pick([i for i in range(len(colors)) if i != previous] or [0])
        accent = pick([i for i in range(len(colors)) if i != main] or [main])
        chapters.append(Chapter(start_frame=int(start), end_frame=int(stop) - 1, focus=focus, colors=[colors[main], colors[accent]]))
        previous = main
    return chapters


# ----- elegir la mejor coreografía sin que el usuario tire los dados -----

# Acciones que una buena versión no debería dejar pasar sin efecto (gestos con significado y el
# objeto protagonista).
# En el solo de uno, el otro no enciende lo que sale de puro movimiento; un gesto con
# significado (la mano a la cabeza, un giro) sí sale: es su respuesta (video_34, seg. 11.5).
TURN_ACTIONS = ("spotlight", "fast_swing", "stomp", "step", "frenzy")
# Al unísono, estas se copian a la pareja aunque el análisis no la haya visto hacer lo mismo
# (lo que sale del movimiento y la entrada); un gesto solo si la pareja también lo hizo.
MIRROR_ALWAYS = (*TURN_ACTIONS, "entrance")
# Efectos de todo el cuadro (no de una persona): no se copian a la pareja.
SCENE_TYPES = ("disco_fx", "mirror_ball", "equalizer", "beat_pulse", "closing_stars", "season_fx")
KEY_ACTIONS = ("face_touch", "throw", "neck_slash", "prop_transfer", "prop_spin", "prop_worn")
CANDIDATES = 8
AMBIENT_ACTIONS = ("beat",)
# Más efectos por segundo que esto satura la escena.
MAX_DENSITY = 1.2
MAX_TOGETHER = 3
WINDOW_S = 1.2


def score_choreography(choreography: Choreography, brief: MotionBrief) -> float:
    """Qué tan buena es una coreografía, sin renderizar (docs/criterio_de_analisis.md):

    - momentos clave atendidos (gestos y objeto, peso 3),
    - tramos de atención con algún efecto encendido (peso 2): pocos huecos vacíos,
    - variedad de opciones (peso 1),
    - menos si satura (más de MAX_DENSITY efectos por segundo), si apila más de MAX_TOGETHER
      efectos a la vez o si repite lo mismo seguido.
    """
    fps = brief.video.fps or 30.0
    duration = max(brief.video.frame_count / fps, 1.0)
    # Los pulsos de música son muchos y cortos: no cuentan como cubrir un momento.
    # La copia en la pareja (espejo) es el mismo momento: no cuenta como otro efecto.
    active = [
        d for d in choreography.decisions
        if not d.choice.startswith("nada") and not d.choice.endswith("(espejo)") and d.action not in AMBIENT_ACTIONS
    ]
    keys = [d for d in choreography.decisions if d.action in KEY_ACTIONS]
    key_score = sum(not d.choice.startswith("nada") for d in keys) / len(keys) if keys else 1.0
    covered = 0.0
    spans = [s for s in brief.attention if s.primary != "prop"]
    for span in spans:
        start, end = span.start_frame / fps, span.end_frame / fps
        if any(start - WINDOW_S <= d.second <= end for d in active):
            covered += 1
    coverage = covered / len(spans) if spans else 1.0
    variety = len({d.choice for d in active}) / len(active) if active else 0.0
    density = len(active) / duration
    crowd = max(0.0, density - MAX_DENSITY)
    repeats = sum(
        1 for a, b in zip(active, active[1:]) if a.choice == b.choice and a.action == b.action and b.second - a.second < 3.0
    ) / max(len(active), 1)
    # Efectos simultáneos: cuadros con más de MAX_TOGETHER efectos encendidos a la vez.
    together = np.zeros(int(brief.video.frame_count) + 1)
    for d in active:
        if d.until >= d.frame:
            together[max(d.frame, 0) : min(d.until, len(together) - 1) + 1] += 1
    stacked = float(np.mean(together > MAX_TOGETHER)) if len(together) else 0.0
    return 3.0 * key_score + 2.0 * coverage + variety - 2.0 * crowd - repeats - 6.0 * stacked


def best_choreography(catalog: Catalog, brief: MotionBrief, take: int = 0, candidates: int = CANDIDATES, pins=None) -> tuple[EffectScript, Choreography]:
    """Prueba `candidates` semillas, las ordena por `score_choreography` y devuelve la del puesto
    `take` (0 = la mejor). "Otra versión" es pedir el puesto siguiente: siempre una versión
    buena y distinta, sin que el usuario elija semillas."""
    results = []
    # Solo lo fijado: no hay sorteo, todas las candidatas serían iguales.
    for k in range(1 if pins is not None and pins.solo_estos else max(candidates, 1)):
        seed = catalog.seed + 1009 * k
        script, choreo = choreograph(catalog, brief, seed, pins)
        results.append((score_choreography(choreo, brief), k, script, choreo))
    results.sort(key=lambda item: (-item[0], item[1]))
    score, _, script, choreo = results[take % len(results)]
    return script, choreo.model_copy(update={"take": take, "score": round(score, 3), "candidates": len(results)})


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


# Momentos de cara: mientras duran, piernas y torso no se encienden (nada compite con la cara).
FACE_ACTIONS = ("face_touch", "neck_slash", "prop_worn")
BODY_KINDS = ("legs", "feet", "torso")

# Reacciones que callan mientras hay un efecto de escena encendido.
YIELD_TO_EXCLUSIVE = ("spotlight", "still", "fast_swing", "beat", "stomp")


def _window(option: Option, event: MotionEvent) -> tuple[int, int]:
    """Fotogramas en que la opción tendrá algo encendido (con anticipación y `hold`)."""
    lead = max((effect.get("trigger", {}).get("lead", 0) for effect in option.effects), default=0)
    hold = max((effect.get("trigger", {}).get("hold", 8) for effect in option.effects), default=0)
    anchored = any(effect.get("trigger", {}).get("anchor") == "end" for effect in option.effects)
    start = (event.end_frame if anchored else event.start_frame) - lead
    return start, event.end_frame + hold


def _yields(option: Option, event: MotionEvent, brief: MotionBrief, seed: int, fps: float) -> bool:
    window = option.yield_window_s * fps
    if not any(e.name in option.yields_to and abs(e.start_frame - event.start_frame) <= window for e in brief.events):
        return False
    rng = np.random.default_rng(zlib.crc32(f"{seed}:yield:{option.name}:{event.start_frame}".encode()) & 0xFFFFFFFF)
    return bool(rng.random() < option.yield_chance)


WARDROBE_CHOICES = ("chaqueta", "vestido", "ambos", "ninguno")


def wardrobe_allows(option: Option, person: str | None, wardrobe: dict[str, str]) -> bool:
    """La prenda de la opción cabe en el vestuario que el usuario eligió para esa persona."""
    if not option.wardrobe:
        return True
    choice = wardrobe.get(person or "", "") or wardrobe.get("*", "") or "ninguno"
    return choice == "ambos" or choice == option.wardrobe


def _draw(reaction: Reaction, event: MotionEvent, seed: int, resting: set[str] = frozenset(), brief: MotionBrief | None = None, wardrobe: dict[str, str] | None = None) -> Option:
    limb = event.target.rsplit(":", 1)[-1]
    options = [
        o
        for o in reaction.options
        if not (o.requires_person and not event.target.startswith("person_"))
        and (not o.limbs or limb in o.limbs)
        and (not o.kinds or event.kind in o.kinds)
        and (not o.accessories or _wears(brief, event, o.accessories))
        and wardrobe_allows(o, _person(event), wardrobe or {})
        and event.peak_speed >= o.min_speed
        and (event.end_frame - event.start_frame + 1) >= o.min_duration_s * (brief.video.fps if brief else 30.0)
        and o.name not in resting
    ]
    if not options:
        return Option(name="nada")
    weights = np.array([max(o.weight, 0.0) for o in options], dtype=np.float64)
    if weights.sum() <= 0:
        return Option(name="nada")
    rng = np.random.default_rng(zlib.crc32(f"{seed}:{reaction.action}:{event.start_frame}:{event.target}".encode()) & 0xFFFFFFFF)
    return options[int(rng.choice(len(options), p=weights / weights.sum()))]


RESTLESS = ("jump", "flip", "tumble", "frenzy", "spin_body", "landing")


def ends_still(events: list[MotionEvent], frame_count: int, fps: float, seconds: float) -> bool:
    """Si en los últimos `seconds` la persona queda quieta o casi: al menos el 60% del tramo
    cubierto por pausas (`still`, `lull`) y ningún salto, giro ni voltereta."""
    start = max(frame_count - int(seconds * fps), 0)
    span = max(frame_count - start, 1)
    calm = np.zeros(span, bool)
    for event in events:
        if event.end_frame < start:
            continue
        if event.name in RESTLESS:
            return False
        if event.name in ("still", "lull"):
            calm[max(event.start_frame - start, 0) : max(event.end_frame + 1 - start, 0)] = True
    return float(calm.mean()) >= 0.6


def always_effects(catalog: Catalog, events: list[MotionEvent], frame_count: int, fps: float, seed: int | None = None) -> list[dict]:
    """Los efectos `always` del catálogo. Con `when: quieto_al_final`, solo si la persona termina
    quieta (la pared de fuego final tapa el piso; si sigue moviéndose o camina, no corresponde).
    Con `chance`, sale solo en esa fracción de los videos (sorteo fijo por video y semilla)."""
    seed = catalog.seed if seed is None else seed
    out = []
    for index, raw in enumerate(catalog.always):
        if raw.get("when") == "quieto_al_final" and not ends_still(events, frame_count, fps, float(raw.get("style", {}).get("size", 1.8))):
            continue
        if "chance" in raw:
            roll = np.random.default_rng(zlib.crc32(f"{seed}:always:{index}:{frame_count}".encode()) & 0xFFFFFFFF).random()
            if roll >= float(raw["chance"]):
                continue
        out.append(_effect(catalog, {k: v for k, v in raw.items() if k not in ("when", "chance")}, f"always_{index}"))
    return out


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
