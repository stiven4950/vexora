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
    return Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


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
        [(e, r) for r in catalog.reactions if r.action not in KEY_ACTIONS for e in events if e.name == r.action],
    ]
    if pins is not None:
        rest = [] if pins.solo_estos else [[pair for pair in pairs if (id(pair[0]), id(pair[1])) not in forced] for pairs in passes]
        passes = [pinned, *rest]
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
                key_name = f"{option.name}{PINNED}"
                chosen.setdefault((reaction.action, key_name), []).append((event.start_frame, event.target))
                memo["last"] = event.start_frame
                memo["used"][option.name] = event.start_frame
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
                twin = _twin(event, person, partner, events, fps, True) if mirror and partner and not whole_scene else None
                if twin is not None:
                    if twin not in events:
                        extra.append(twin)
                    mirrored.setdefault((reaction.action, key_name), []).append((twin.start_frame, twin.target))
                    busy[(partner, group)] = max(busy.get((partner, group), -1), end)
                    decisions.append(
                        Decision(frame=twin.start_frame, second=round(twin.start_frame / fps, 2), action=reaction.action, target=twin.target, choice=f"{option.name} (espejo)", until=end)
                    )
                decisions.append(
                    Decision(frame=event.start_frame, second=round(event.start_frame / fps, 2), action=reaction.action, target=event.target, choice=f"{option.name} (fijado)", until=end)
                )
                continue
            resting = {name for name, frame in memo["used"].items() if event.start_frame - frame < _option(reaction, name).cooldown}
            option = _draw(reaction, event, seed, resting, brief)
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
            elif option.effects and reaction.action in YIELD_TO_EXCLUSIVE and start <= exclusive_until:
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
                and sum(1 for ls, le in lit if ls <= start <= le) + sum(1 for ks, ke in key_windows if ks <= end and start <= ke) >= MAX_TOGETHER
            ):
                option = Option(name="nada (ya hay dos focos encendidos)")
            if option.effects:
                memo["last"] = event.start_frame
                memo["used"][option.name] = event.start_frame
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
                if twin is not None:
                    if twin not in events:
                        extra.append(twin)
                    mirrored.setdefault((reaction.action, option.name), []).append((twin.start_frame, twin.target))
                    busy[(partner, group)] = max(busy.get((partner, group), -1), end)
                    decisions.append(
                        Decision(
                            frame=twin.start_frame,
                            second=round(twin.start_frame / fps, 2),
                            action=reaction.action,
                            target=twin.target,
                            choice=f"{option.name} (espejo)",
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
    always = [] if pins is not None and pins.solo_estos else catalog.always
    effects: list[dict] = [_effect(catalog, raw, f"always_{index}") for index, raw in enumerate(always)]
    for reaction in catalog.reactions:
        for option, suffix in ((o, s) for o in reaction.options for s in ("", PINNED)):
            name = f"{option.name}{suffix}"
            tag = "_fijado" if suffix else ""
            picked = sorted(chosen.get((reaction.action, name), []))
            for index, raw in enumerate(option.effects if picked else []):
                effect = _effect(catalog, raw, f"{reaction.action}_{option.name}_{index}{tag}")
                if suffix:
                    # Lo fijado se ve aunque la línea de atención mire a otro lado.
                    effect["style"]["focus"] = False
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
                if suffix:
                    effect["style"]["focus"] = False
                trigger = dict(raw.get("trigger", {}))
                trigger.update(event=reaction.action, frames=[f for f, _t in twins], targets=[t for _f, t in twins])
                effect["triggers"] = [trigger]
                effects.append(effect)
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
    if catalog.chapters:
        palette = catalog.defaults.get("style", {}).get("palette") or catalog.colors
        weights = skin_scores(palette, luma) ** 2 if luma is not None else None
        script.chapters = build_chapters(events, palette, seed, fps, brief.video.frame_count, catalog.chapter_min_s, weights)
    decisions.sort(key=lambda d: (d.frame, d.action))
    return resolve_timing(script, brief.video.frame_count), Choreography(catalog=catalog.name, seed=seed, decisions=decisions)


# Clave de lo fijado a mano en `chosen` (sus efectos van aparte, sin apagarse fuera de foco).
PINNED = "#fijado"


def _partner(person: str | None, span, brief: MotionBrief) -> str | None:
    """La pareja: la del tramo de dúo o, sin él, la otra persona del video."""
    if span is not None:
        return span.partner if person == span.leader else span.leader
    others = [p for p in brief.people if p != person]
    return others[0] if person and others else None


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
    target = f"{partner}{event.target[len(person):]}" if event.target.startswith(person) else event.target
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
    if catalog.duet:
        style.setdefault("by_person", True)
    return effect
