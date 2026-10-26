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


class Follow(_Strict):
    """Cadena: esta opción es la consecuencia de otra (`after` = "acción:opción", o "*:opción").
    Si la otra salió hace menos de `within_s`, el peso se multiplica por `boost`."""

    after: str
    within_s: float = 1.2
    boost: float = 8.0


class Earn(_Strict):
    """La opción solo entra si, entre `within_s[0]` y `within_s[1]` segundos después, la misma
    extremidad hace una de estas acciones (la bestia que vuelve a la mano necesita el golpe que la
    use)."""

    actions: list[str]
    within_s: tuple[float, float] = (0.3, 1.6)


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
    # Cadenas (ver Follow). `requires_follow`: sin la opción anterior de la cadena, no entra.
    follows: list[Follow] = Field(default_factory=list)
    requires_follow: bool = False
    earns: Earn | None = None
    # El gesto manda la atención (una voltereta: la atención va a los pies): no cede ante el tope
    # de focos encendidos. Lo mismo vale para una consecuencia cuya opción anterior salió (la
    # caída que desbarata el fuego continúa el mismo foco de la voltereta).
    leads: bool = False
    # Grupo con tope compartido en el video (Catalog.group_limits): p. ej. "bestia", para que no
    # salgan más de dos bestias por video aunque cada una tenga su max_uses.
    group: str = ""
    # Peso visual: "pesado" (cubre mucha pantalla o es complejo: alfombra, aro grande, bestias),
    # "medio" (estelas, chorro, rayo) o "ligero" (chispas, la mirada). Un pesado no comparte su
    # tramo con nada que no sea ligero (unclutter). Vacío: según sus figuras (weight_class).
    weight_class: str = ""
    # Segundos que dura la parte pesada (0 = toda su ventana). La bestia lanzada vuela medio
    # segundo y después queda como una llama en la mano esperando el golpe: eso ya no tapa nada.
    heavy_s: float = 0.0
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
    # Tope de usos por video de cada grupo de opciones (Option.group).
    group_limits: dict[str, int] = Field(default_factory=dict)
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


def _element_catalog(path: Path, raw: dict) -> dict:
    """Un catálogo de un solo elemento sacado de otro (`extends: avatar`, `only_element: agua`):
    lleva las acciones y opciones de la base que son de ese elemento, sin capítulos de otros
    elementos y sin los efectos permanentes de la base (la luz del fuego, las brasas), que son de
    su elemento. Lo que el catálogo escribe (nombre, título, colores, `always`...) manda sobre la
    base. `keep: [mirada]` conserva opciones neutras (sin elemento) por nombre."""
    base_name, only = raw.pop("extends"), raw.pop("only_element", None)
    if not only:
        raise ValueError(f"{path.name}: extends pide only_element (el elemento que se queda)")
    keep = set(raw.pop("keep", None) or [])
    base = yaml.safe_load((path.parent / f"{base_name}.yaml").read_text(encoding="utf-8"))
    reactions = []
    for reaction in base["reactions"]:
        options = [
            option
            for option in reaction["options"]
            if (base.get("element", "") if option.get("element") is None else option["element"]) == only or option["name"] in keep
        ]
        if options:
            reactions.append({**reaction, "options": [{**option, "element": only} for option in options]})
    if not reactions:
        raise ValueError(f"{path.name}: {base_name} no tiene opciones del elemento {only}")
    return {**base, "always": [], "element_mix": {}, "group_limits": {}, **raw, "element": only, "reactions": reactions}


def load_catalog(path: Path) -> Catalog:
    """Lee un catálogo y le suma sus `include`: fragmentos (`configs/catalogs/_<nombre>.yaml`, solo
    con `reactions`) cuyas opciones se agregan a las de la misma acción, con el peso multiplicado
    por el `weight` del include (1 si se da solo el nombre). Una acción que el catálogo no tiene se
    agrega entera. Dos opciones con el mismo nombre en la misma acción son un error. Con `extends`,
    el catálogo es un solo elemento de otro (ver `_element_catalog`)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "extends" in raw:
        raw = _element_catalog(path, raw)
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
    heavy_starts: list[int] = []  # inicio de cada pesado elegido (en un video corto, separados)
    from vfxglow.analysis.beats import cut_frames

    cuts = cut_frames(brief.beats)
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

        varied = any(p.alternativas for p in pins.momentos)  # sin alternativas, todo igual que siempre
        for event, reaction, option, pin, made in resolve_pins(pins, catalog, events, brief, fps, seed=seed if varied else None):
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
    history: list[tuple[int, str, str]] = []  # (cuadro, acción, opción) de lo que ya salió (cadenas)
    plan = element_plan(catalog, events, brief.video.frame_count, fps, seed)
    if pins is not None and pins.capitulos:
        plan = voice_plan(catalog, pins, brief.video.frame_count, fps)
    elements: list[tuple[int, int, str]] = []  # tramos encendidos de cada elemento (capítulos)
    # Aire entre elementos; los capítulos de la voz caen en cortes de toma y no lo necesitan.
    voiced = pins is not None and bool(pins.capitulos)
    pad = int(round((RELAY_S if voiced else catalog.element_pad_s) * fps))
    closings = {"fire_wall", "fire_carpet_end"}
    # Si la voz dice que el final es de otro elemento (el aire), no hay cierre de fuego en el piso.
    fire_end = chapter_element(plan, brief.video.frame_count - 2) in ("", catalog.element)
    if catalog.element and fire_end and any(closings & set(raw.get("style", {}).get("shapes", [])) for raw in catalog.always):
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
                if option.group:
                    spent[f"grupo:{option.group}"] = spent.get(f"grupo:{option.group}", 0) + 1
                history.append((event.start_frame, reaction.action, option.name))
                if element_of(catalog, option):
                    elements.append((start, end, element_of(catalog, option)))
                if option.exclusive:
                    exclusive_until = max(exclusive_until, end)
                if reaction.action in KEY_ACTIONS:
                    key_windows.append((start, until_cut(start, end, cuts)))
                if reaction.action in FACE_ACTIONS:
                    face_windows.append((start, until_cut(start, end, cuts)))
                if reaction.action not in AMBIENT_ACTIONS and reaction.action not in KEY_ACTIONS and weight_class(option) != "ligero":
                    lit.append((start, until_cut(start, end, cuts)))  # lo ligero no ocupa lugar de foco; el corte lo apaga
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
            resting |= {o.name for o in reaction.options if o.group and spent.get(f"grupo:{o.group}", 0) >= catalog.group_limits.get(o.group, 10**6)}
            resting |= other_elements(catalog, reaction.options, elements, event, pad, cuts)
            chapter = chapter_element(plan, event.start_frame)
            if chapter:  # solo el elemento del capítulo (y lo neutro), sin meterse en el siguiente
                resting |= {o.name for o in reaction.options if element_of(catalog, o) and element_of(catalog, o) != chapter}
                resting |= {o.name for o in reaction.options if element_of(catalog, o) and crosses_chapter(plan, element_of(catalog, o), *_window(o, event), int(round(RELAY_S * fps)), cuts)}
            resting |= {o.name for o in reaction.options if o.earns and not _earns_ok(o.earns, event, events, fps)}
            option = _draw(_chained(reaction, event, history, fps, resting), event, seed, resting, brief, catalog.wardrobe)
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
            if option.effects and weight_class(option) == "pesado":
                total = brief.video.frame_count
                heavy_until = heavy_end(option, start, end, fps)  # la ventana del efecto (end) no cambia
                if heavy_until > total - 1 - int(round(RELAY_S * fps)):
                    # Su ciclo (la bestia que vuelve a la mano) no termina antes del final: el
                    # final quedaba solo con ella.
                    option = Option(name="nada (el pesado no cabe antes del final)")
                elif any(start < cut <= heavy_until for cut in cuts):
                    # Un corte de toma lo partiría: la bestia sale en una toma y "vuelve" en otra.
                    option = Option(name="nada (el pesado cruzaría un corte de toma)")
                elif total < SHORT_VIDEO_S * fps and any(abs(event.start_frame - f) < HEAVY_EVERY_S * fps for f in heavy_starts):
                    option = Option(name="nada (un pesado cada 5 s en un video corto)")
                else:
                    heavy_starts.append(event.start_frame)
            if option.effects:
                memo["last"] = event.start_frame
                memo["used"][option.name] = event.start_frame
                spent[option.name] = spent.get(option.name, 0) + 1
                if option.group:
                    spent[f"grupo:{option.group}"] = spent.get(f"grupo:{option.group}", 0) + 1
                history.append((event.start_frame, reaction.action, option.name))
                if element_of(catalog, option):
                    elements.append((start, end, element_of(catalog, option)))
                chosen.setdefault((reaction.action, option.name), []).append((event.start_frame, event.target))
                if option.exclusive:
                    exclusive_until = end
                if reaction.action in KEY_ACTIONS:
                    key_windows.append((start, until_cut(start, end, cuts)))
                if reaction.action in FACE_ACTIONS:
                    face_windows.append((start, until_cut(start, end, cuts)))
                if reaction.action not in AMBIENT_ACTIONS and reaction.action not in KEY_ACTIONS and weight_class(option) != "ligero":
                    lit.append((start, until_cut(start, end, cuts)))  # lo ligero no ocupa lugar de foco; el corte lo apaga
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
    always = [] if pins is not None and pins.solo_estos else always_effects(catalog, events, brief.video.frame_count, fps, seed)
    always = chapter_always(catalog, always, plan, brief.video.frame_count)
    opts = {(r.action, o.name): o for r in catalog.reactions for o in r.options}
    # Primero ceden los que se enciman con un pesado; después se rellena lo que quedó vacío, con un
    # relevo apenas termina cada pesado (sin pesado no hay que esperar: la escena no queda sola).
    heavies = unclutter(catalog, chosen, decisions, always, brief.video.frame_count, fps)
    # Los tramos de cada elemento, solo con lo que quedó (lo que cedió ya no bloquea a otro elemento).
    closing = [el for el in elements if el[1] == brief.video.frame_count and el[2] == catalog.element][:1]
    elements = closing + [
        (d.frame, d.until, element_of(catalog, opts[(d.action, d.choice.split(" (")[0])]))
        for d in decisions
        if not d.choice.startswith("nada") and (d.action, d.choice.split(" (")[0]) in opts and element_of(catalog, opts[(d.action, d.choice.split(" (")[0])])
    ]
    if catalog.max_gap_s > 0 and not (pins is not None and pins.solo_estos):
        fill_gaps(catalog, brief, events, extra, chosen, decisions, seed, fps, elements, plan, heavies, pad if voiced else None)
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
    return option.min_speed > 0 or option.min_duration_s > 0 or option.leads


# Figuras que cubren mucha pantalla o son complejas (pesadas) y las que casi no ocupan (ligeras); el
# resto, medias. Así una opción no tiene que decir su peso en el catálogo.
HEAVY_SHAPES = {
    "fire_landing", "fire_carpet", "fire_carpet_end", "fire_wall", "fire_halo", "fire_orbit", "body_blaze",
    "fire_dragon", "fire_skull", "fire_bird", "fire_serpent", "fire_breath", "fire_phoenix", "fire_dragon_launch",
    "fire_coil", "fire_kitsune", "fire_lion", "water_orb", "earth_shield", "earth_boulder", "earth_orbit", "earth_crystals",
}
LIGHT_SHAPES = {"sparks", "droplets", "avatar_mark", "cracks", "glow_eyes"}
LIGHT_TYPES = {"sparks", "droplets", "grade"}
UNCLUTTER_MARGIN_S = 0.3  # aire antes de un efecto pesado (lo anterior se apaga antes de que nazca)
RELAY_S = 0.1  # al terminar un pesado, lo siguiente entra enseguida (la escena no queda vacía)
SHORT_VIDEO_S = 15.0  # en un video más corto que esto...
HEAVY_EVERY_S = 5.0  # ...como mucho un pesado cada tantos segundos (si no, ocupan casi todo)
RELAY_KINDS = ("right_arm", "left_arm", "legs", "feet", "torso", "head")  # regiones que prueba un relevo


def weight_class(option: Option) -> str:
    """El peso visual de la opción: el que dice el catálogo o, si no, el de sus figuras."""
    if option.weight_class:
        return option.weight_class
    shapes = {shape for raw in option.effects for shape in (raw.get("style") or {}).get("shapes", [])}
    if shapes & HEAVY_SHAPES:
        return "pesado"
    def light(raw: dict) -> bool:
        figures = set((raw.get("style") or {}).get("shapes", []))
        return raw.get("type") in LIGHT_TYPES or bool(figures) and figures <= LIGHT_SHAPES

    return "ligero" if all(light(raw) for raw in option.effects) else "medio"


def heavy_end(option: Option, start: int, end: int, fps: float) -> int:
    """Último cuadro de la parte pesada de la opción (Option.heavy_s)."""
    return min(end, start + int(round(option.heavy_s * fps))) if option.heavy_s > 0 else end


def unclutter(catalog: Catalog, chosen: dict, decisions: list, always: list[dict], total: int, fps: float) -> list[tuple[int, int]]:
    """Los efectos pesados no se combinan: mientras uno está encendido (con UNCLUTTER_MARGIN_S de
    aire antes y RELAY_S después) no sale nada que no sea ligero, para no saturar la escena.
    Mandan, en orden, lo fijado a mano, la pared del cierre, lo que lleva la atención (leads), los
    pesados y lo que empieza antes; lo que choca con algo ya aceptado cede. Una consecuencia no
    choca con lo que la causa (la caída que desbarata el fuego de la voltereta).

    Devuelve los tramos de los pesados: al terminar cada uno tiene que entrar otro efecto enseguida
    y ningún relleno se les puede encimar (fill_gaps, `heavies`)."""
    options = {(r.action, o.name): o for r in catalog.reactions for o in r.options}
    before, after = int(round(UNCLUTTER_MARGIN_S * fps)), int(round(RELAY_S * fps))

    def too_close(a: tuple, b: tuple) -> bool:
        first, second = (a, b) if a[0] <= b[0] else (b, a)
        return second[0] <= first[1] + (after if first[2] == "pesado" else before)

    items = []  # (rango, inicio, fin, peso, acción, opción, decisión)
    for d in decisions:
        name = d.choice.split(" (")[0]
        option = options.get((d.action, name))
        if option is None or not option.effects or d.choice.startswith("nada"):
            continue
        heavy = weight_class(option)
        if heavy == "ligero":
            continue
        pinned = d.choice.endswith("(fijado)")
        rank = (0 if pinned else 1 if option.leads else 2 if heavy == "pesado" else 3, d.frame)
        items.append((rank, d.frame, heavy_end(option, d.frame, max(d.until, d.frame), fps), heavy, d.action, name, d))
    accepted = []
    if any("fire_wall" in (raw.get("style") or {}).get("shapes", []) for raw in always):
        from vfxglow.engine.firebend import closing_frames

        accepted.append((total - closing_frames(total, fps), total, "pesado", "always", "fire_wall"))
    for _rank, start, end, heavy, action, name, d in sorted(items, key=lambda item: item[0]):
        option = options[(action, name)]
        clash = next(
            (
                other
                for other in accepted
                if (heavy == "pesado" or other[2] == "pesado")
                and too_close((start, end, heavy), other)
                and not _chained_pair(option, options.get((other[3], other[4])), action, other)
            ),
            None,
        )
        if clash is None or d.choice.endswith(("(fijado)", "(espejo)")):
            accepted.append((start, end, heavy, action, name))
            continue
        picks = chosen.get((action, name), [])
        if (d.frame, d.target) in picks:
            picks.remove((d.frame, d.target))
        d.choice = f"nada (cede al efecto pesado {clash[4]})" if clash[2] == "pesado" else f"nada (es pesado y ya está encendido {clash[4]})"
        d.until = d.frame
    return sorted((start, end) for start, end, heavy, _action, _name in accepted if heavy == "pesado")


def _chained_pair(option: Option, other: Option | None, action: str, other_item: tuple) -> bool:
    """Si una de las dos opciones es la consecuencia de la otra (Option.follows)."""

    def causes(follows: list[Follow], cause_action: str, cause: str) -> bool:
        return any(f.after in (f"{cause_action}:{cause}", f"*:{cause}") for f in follows)

    return causes(option.follows, other_item[3], other_item[4]) or (other is not None and causes(other.follows, action, option.name))


ELEMENT_CUES = {
    "rayo": ("throw", "point", "finger_gun", "arms_open"),
    "aire": ("spin_body", "jump", "flip"),
}


def voice_plan(catalog: Catalog, pins, total: int, fps: float) -> list[tuple[int, int, str]]:
    """El reparto de elementos que dice la voz del video (pins.capitulos): cada tramo, del elemento
    nombrado; si el catálogo no tiene efectos de ese elemento, o entre capítulos, el del catálogo."""
    from vfxglow.director.pins import chapter_plan

    known = {element_of(catalog, o) for r in catalog.reactions for o in r.options if o.effects} - {""}
    plan, cursor = [], 0
    for start, end, element in chapter_plan(pins, fps):
        start, end = max(start, cursor), min(end, total)
        if start > cursor:
            plan.append((cursor, start, catalog.element))
        if end > start:
            plan.append((start, end, element if element in known else catalog.element))
            cursor = end
    if cursor < total:
        plan.append((cursor, total, catalog.element))
    return plan


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


def crosses_chapter(plan: list[tuple[int, int, str]], element: str, start: int, end: int, slack: int, cuts: list[int] | None = None) -> bool:
    """Si la ventana [start, end] se mete (más de `slack` cuadros) en un capítulo de otro elemento:
    un chorro de fuego que sigue encendido en el capítulo de aire bloqueaba todo el aire. Un
    capítulo que empieza en un corte de toma no cuenta: el motor apaga el efecto en el corte."""

    def at_cut(frame: int) -> bool:
        return any(abs(frame - c) <= slack for c in cuts or [])

    return any(el != element and s <= end - slack and start <= e and not at_cut(s) for s, e, el in plan if s > start)


def chapter_element(plan: list[tuple[int, int, str]], frame: int) -> str:
    """El elemento del capítulo en `frame`. Los capítulos son [inicio, fin): en el borde manda el
    que empieza (en el borde entraba una estela de fuego en el capítulo de aire)."""
    return next((el for s, e, el in plan if s <= frame < e), plan[-1][2] if plan and frame >= plan[-1][1] else "")


def _limb(target: str) -> str:
    name = target.rsplit(":", 1)[-1]
    return name if name.endswith(("_wrist", "_ankle")) else ""


def _earns_ok(earn: Earn, event: MotionEvent, events: list[MotionEvent], fps: float) -> bool:
    """Si después del evento llega un golpe que use lo que la opción deja (de la misma mano, si se
    sabe cuál)."""
    lo, hi = event.start_frame + earn.within_s[0] * fps, event.start_frame + earn.within_s[1] * fps
    mine = _limb(event.target)
    for e in events:
        if e.name in earn.actions and lo <= e.start_frame <= hi and e is not event:
            theirs = _limb(e.target)
            if not mine or not theirs or theirs == mine:
                return True
    return False


def _chained(reaction: Reaction, event: MotionEvent, history: list[tuple[int, str, str]], fps: float, resting: set[str]) -> Reaction:
    """Las opciones con cadenas (`follows`), con el peso de esta ocurrencia: multiplicado si su
    opción anterior salió hace poco; las que la exigen y no la tienen, a reposo."""
    if not any(o.follows for o in reaction.options):
        return reaction
    options = []
    for o in reaction.options:
        weight, linked = o.weight, False
        for link in o.follows:
            action, _, name = link.after.partition(":")
            window = link.within_s * fps
            if any(f <= event.start_frame and event.start_frame - f <= window and n == name and action in ("*", a) for f, a, n in history):
                weight *= link.boost
                linked = True
        if o.requires_follow and not linked:
            resting.add(o.name)
        options.append(o.model_copy(update={"weight": weight, "leads": o.leads or linked}) if weight != o.weight else o)
    return reaction.model_copy(update={"options": options})


def element_of(catalog: Catalog, option: Option) -> str:
    return catalog.element if option.element is None else option.element


def until_cut(start: int, end: int, cuts: list[int] | None) -> int:
    """El fin de una ventana que empieza en `start`: el motor apaga el efecto en el siguiente corte
    de toma, así que más allá no ocupa nada."""
    return min([end] + [c - 1 for c in cuts or [] if start < c <= end])


def other_elements(catalog: Catalog, options: list[Option], elements: list[tuple[int, int, str]], event: MotionEvent, pad: int, cuts: list[int] | None = None) -> set[str]:
    """Las opciones cuyo tramo (con `pad` de margen) se encima con uno de otro elemento ya
    encendido (capítulos de elemento). Cada tramo termina, a más tardar, en el corte de toma."""
    out = set()
    elements = [(s, until_cut(s, e, cuts), el) for s, e, el in elements]
    for o in options:
        mine = element_of(catalog, o)
        if not mine or not o.effects:
            continue
        start, end = _window(o, event)
        end = until_cut(start, end, cuts)
        if any(el != mine and s - pad <= end and start <= e + pad for s, e, el in elements):
            out.add(o.name)
    return out


def fill_gaps(catalog: Catalog, brief: MotionBrief, events, extra, chosen, decisions, seed: int, fps: float, elements: list | None = None, plan: list | None = None, heavies: list[tuple[int, int]] | None = None, element_pad: int | None = None) -> None:
    """Rellena los tramos sin ningún efecto más largos que `catalog.max_gap_s`: en cada hueco, un
    efecto del foco de ese momento (un `spotlight`), sorteado entre las opciones que dibujan algo y
    no son de escena ni pesadas. Si en el hueco no hay foco, se crea uno con la región de la línea
    de atención (o el cuerpo entero). Se repite hasta que no queden huecos o no haya qué poner.

    `heavies`: los tramos de los efectos pesados (unclutter). Al terminar cada uno entra un efecto
    enseguida (RELAY_S), aunque el hueco que sigue sea corto: después de una figura grande la
    escena no queda vacía. Ningún relleno se encima con un pesado (ni en el aire de antes)."""
    spot = next((r for r in catalog.reactions if r.action == "spotlight"), None)
    if spot is None:
        return
    total = brief.video.frame_count
    longest = int(round(catalog.max_gap_s * fps))
    covered = np.zeros(total + 1, dtype=bool)
    from vfxglow.analysis.beats import cut_frames

    shot_cuts = cut_frames(brief.beats)
    for d in decisions:
        if not d.choice.startswith("nada") and d.action not in AMBIENT_ACTIONS and d.until >= d.frame:
            covered[max(d.frame, 0) : min(until_cut(d.frame, d.until, shot_cuts), total) + 1] = True
    people = brief.people or [brief.person_id]
    heavies = heavies or []
    options = {(r.action, o.name): o for r in catalog.reactions for o in r.options}
    # Lo que ya está encendido sin contar lo ligero (la mirada, las chispas): eso no llena la escena.
    strong = np.zeros(total + 1, dtype=bool)
    for d in decisions:
        option = options.get((d.action, d.choice.split(" (")[0]))
        if option is not None and option.effects and not d.choice.startswith("nada") and weight_class(option) != "ligero":
            # De un pesado solo cuenta su parte pesada: la llama que queda en la mano no llena.
            until = heavy_end(option, d.frame, d.until, fps) if weight_class(option) == "pesado" else d.until
            until = until_cut(d.frame, until, shot_cuts)  # el motor lo apaga en el corte de toma
            strong[max(d.frame, 0) : min(until, total) + 1] = True
    before, after = int(round(UNCLUTTER_MARGIN_S * fps)), int(round(RELAY_S * fps))

    def fits(first: int, last: int) -> bool:
        """Que el relleno no se encime con un pesado ni con el aire de antes de que nazca."""
        return not any(first <= end + after - 1 and start - before <= last for start, end in heavies)

    def place(start: int, attempt: int, pad: int | None = None, length: int | None = None, chapters: bool = True, light: bool = True) -> bool:
        """Un efecto del foco que empieza en `start`. False si no hay nada que poner. `pad`: aire
        entre elementos (por defecto el del catálogo); `length`: cuadros del foco que se crea
        (por defecto un segundo); `chapters`: respetar el elemento del capítulo; `light`: admitir
        lo ligero (un relevo no: no llena la escena)."""
        # Un foco que empiece justo ahí (si empieza más tarde, el tramo de antes quedaría vacío):
        # si no lo hay, se crea uno ahí mismo.
        candidates = [e for e in events if e.name == "spotlight" and start <= e.start_frame <= start + 3]
        event = min(candidates, key=lambda e: (e.start_frame, -e.confidence)) if candidates else None
        if event is None:
            region = next((a.primary for a in brief.attention if a.start_frame <= start <= a.end_frame and a.primary != "prop"), "")
            event = MotionEvent(name="spotlight", target=people[attempt % len(people)], start_frame=start, end_frame=min(start + (int(fps) if length is None else length), total - 1),
                                confidence=1.0, detail="Relleno: ningún tramo sin efecto.", kind=region)
            events.append(event)
            extra.append(event)
        default_pad = int(round(catalog.element_pad_s * fps)) if element_pad is None else element_pad
        blocked = other_elements(catalog, spot.options, elements or [], event, default_pad if pad is None else pad, shot_cuts)
        chapter = chapter_element(plan or [], event.start_frame) if chapters else ""
        if chapter:
            blocked |= {o.name for o in spot.options if element_of(catalog, o) and element_of(catalog, o) != chapter}
        # Ni de escena ni pesadas: un relleno no tapa la escena ni se encima con lo que sigue.
        pool = Reaction(
            action="spotlight",
            options=[
                o
                for o in spot.options
                if o.effects and not o.exclusive and weight_class(o) not in ("pesado", "" if light else "ligero") and o.name not in blocked and fits(*_window(o, event))
            ],
        )
        option = _draw(pool, event, seed + 7919 * (attempt + 1), frozenset(), brief, catalog.wardrobe)
        if not option.effects:
            # Sin opción para esa región: el cuerpo entero sí admite casi todas.
            option = _draw(pool, event.model_copy(update={"kind": ""}), seed + 7919 * (attempt + 1), frozenset(), brief, catalog.wardrobe)
        if not option.effects and not light:
            # Un relevo no se queda sin nada: prueba las otras partes del cuerpo.
            for kind in RELAY_KINDS:
                option = _draw(pool, event.model_copy(update={"kind": kind}), seed + 7919 * (attempt + 1), frozenset(), brief, catalog.wardrobe)
                if option.effects:
                    event.kind = kind
                    break
        if not option.effects:
            return False
        first, last = _window(option, event)
        if elements is not None and element_of(catalog, option):
            elements.append((first, last, element_of(catalog, option)))
        chosen.setdefault(("spotlight", option.name), []).append((event.start_frame, event.target))
        decisions.append(
            Decision(frame=event.start_frame, second=round(event.start_frame / fps, 2), action="spotlight", target=event.target, choice=option.name, until=last)
        )
        covered[max(first, 0) : min(last, total) + 1] = True
        strong[max(first, 0) : min(last, total) + 1] = True
        return True

    attempt = 0
    for _start, end in heavies:
        frame = end + after
        if frame < total - 1 and not strong[frame]:  # nadie tomó el relevo: entra uno ya
            # El pesado ya se apagó: el relevo puede ser de otro elemento (el capítulo que sigue)
            # sin esperar el aire entre elementos.
            # Hasta lo que viene (hasta un segundo), con su propio hold. Si el capítulo no tiene nada
            # que poner ahí (el rayo pide un gesto fuerte), sigue el elemento que venía, sin
            # encimarse con otro.
            later = np.nonzero(strong[frame:])[0]
            length = int(np.clip((later[0] if len(later) else total - frame) - int(0.5 * fps), 2, fps))
            # Si el largo no cabe (choca con otro elemento o con un pesado), uno corto.
            for size, chapters in ((length, True), (2, True), (length, False), (2, False)):
                if place(frame, attempt, 0, size, chapters=chapters, light=False):
                    break
            attempt += 1
    for attempt in range(attempt, attempt + 200):
        gap = _first_gap(covered, longest)
        if gap is None:
            return
        start, end = gap
        # Si al principio del hueco no cabe nada (el aire entre elementos), se prueba más adelante.
        step = max(int(round(catalog.element_pad_s * fps)), 1)
        if not any(place(at, attempt) for at in range(start, max(end - step, start) + 1, step)):
            covered[start : end + 1] = True  # nada que poner aquí: no insistir


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
    # Solo lo fijado y sin alternativas: no hay sorteo, todas las candidatas serían iguales.
    fixed = pins is not None and pins.solo_estos and not any(p.alternativas for p in pins.momentos)
    for k in range(1 if fixed else max(candidates, 1)):
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


CLOSING_SHAPES = {"fire_wall", "fire_carpet_end"}  # se cronometran solos al final


def chapter_always(catalog: Catalog, always: list[dict], plan: list[tuple[int, int, str]], total: int) -> list[dict]:
    """Lo que está siempre (la luz del fuego, las brasas) es del elemento del catálogo: con
    capítulos de otro elemento (agua, aire), se enciende solo en los tramos del suyo. Si no, en un
    capítulo de agua salían brasas naranjas."""
    if not catalog.element or all(el == catalog.element for _s, _e, el in plan):
        return always
    spans: list[list[int]] = []
    for start, end, el in sorted(plan):
        if el != catalog.element:
            continue
        if spans and start <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    out = []
    fire_end = chapter_element(plan, total - 2) in ("", catalog.element)
    for effect in always:
        if set(effect.get("style", {}).get("shapes", [])) & CLOSING_SHAPES:
            if fire_end:  # el cierre de fuego, solo si el final es de fuego
                out.append(effect)
            continue
        for k, (start, end) in enumerate(spans):
            piece = copy.deepcopy(effect)
            piece["id"] = f"{effect['id']}_tramo{k}"
            piece["time"] = {**effect.get("time", {}), "start_frame": start, "end_frame": min(end, total - 1), "fade_in": 3, "fade_out": 6}
            out.append(piece)
    return out


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
